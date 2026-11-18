"""Lead farmers allocate hectares. Admin sets the maximum, then confirms the distribution.

Quantities and costs are calculated on the server. There is no variety cap and no stock.
A submission is not an allocation until Admin confirms the final distribution.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Notification
from apps.clusters.models import Cluster
from apps.inputs.models import InputAllocation, InputSupplyLimit, InputSupplyRequest
from apps.inputs.test_programme_allocation import make_farmer, make_world
from apps.programmes.models import Season
from apps.recovery.models import InputDebt

User = get_user_model()


class InputSupplyWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_world(cls)
        cls.cluster = Cluster.objects.create(name="Marondera Central", province=cls.province, district=cls.district)
        cls.other_cluster = Cluster.objects.create(name="Marondera West", province=cls.province, district=cls.district)
        cls.lead = User.objects.create_user(
            email="john.moyo@example.com", username="john.moyo", password="Str0ng!Passw0rd",
            role=User.ROLE_LEAD_FARMER, first_name="John", last_name="Moyo", assigned_cluster=cls.cluster,
        )
        cls.other_lead = User.objects.create_user(
            email="ruth.dube@example.com", username="ruth.dube", password="Str0ng!Passw0rd",
            role=User.ROLE_LEAD_FARMER, first_name="Ruth", last_name="Dube", assigned_cluster=cls.other_cluster,
        )
        cls.officer = User.objects.create_user(
            email="programme.officer@example.com", username="programme.officer", password="Str0ng!Passw0rd",
            role=User.ROLE_PROGRAMME_OFFICER, first_name="Ada", last_name="Ncube",
        )
        cls.farmer.cluster = cls.cluster
        cls.farmer.save(update_fields=["cluster"])
        cls.other_farmer.cluster = cls.other_cluster
        cls.other_farmer.save(update_fields=["cluster"])
        cls.third = make_farmer(cls, "Chipo", "63-1111111C12", maize_hectares=10)
        cls.third.cluster = cls.cluster
        cls.third.save(update_fields=["cluster"])

    def setUp(self):
        self.admin = APIClient()
        self.admin.force_authenticate(self.__class__.admin)
        self.lead_api = APIClient()
        self.lead_api.force_authenticate(self.lead)
        self.other_api = APIClient()
        self.other_api.force_authenticate(self.other_lead)
        self.officer_api = APIClient()
        self.officer_api.force_authenticate(self.officer)

    def programme(self, name="ARDA"):
        response = self.admin.post(reverse("programme-list"), {
            "name": name, "season": self.season.id, "crops": [self.maize.id],
            "input_categories": ["SEED", "FERTILIZER", "CHEMICALS"], "capacity_status": "ACTIVE",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def line(self, programme, category, product, rate, price=None, pack=None):
        payload = {
            "crop": self.maize.id, "programme": programme, "input_category": category,
            "input_product": product.id, "rate_per_hectare": rate,
        }
        if pack:
            payload.update(pack)
        else:
            payload["cost_per_unit"] = price
        response = self.admin.post(reverse("crop-input-requirement-list"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def farmers_payload(self, lines_by_farmer):
        farmers = []
        for farmer, lines in lines_by_farmer:
            farmers.append({
                "farmer": farmer.id,
                "farm": farmer.farms.first().id,
                "lines": [{"requirement": requirement, "hectares": hectares, "quantity": "1", "estimated_cost": "1"} for requirement, hectares in lines],
            })
        return farmers

    def save(self, client, programme, lines_by_farmer):
        return client.post(reverse("input-supply-request-list"), {
            "programme": programme, "season": self.season.id, "crop": self.maize.id,
            "farmers": self.farmers_payload(lines_by_farmer),
        }, format="json")

    def submit(self, client, pk):
        return client.post(reverse("input-supply-request-submit", kwargs={"pk": pk}))

    def limits(self, crop, categories, varieties):
        payload = [{"scope": "CROP", "approved_hectares": crop}]
        payload += [{"scope": "CATEGORY", "input_category": category, "approved_hectares": hectares} for category, hectares in categories]
        payload += [{"scope": "VARIETY", "requirement": requirement, "approved_hectares": hectares} for requirement, hectares in varieties]
        return payload

    def test_quantities_and_costs_are_calculated_and_only_final_approval_allocates(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        compound = self.line(programme, "FERTILIZER", self.compound_d, "400", pack={
            "pack_label": "50 kg bag", "pack_size": "50", "pack_price": "32",
        })

        refused = self.admin.post(reverse("input-supply-request-list"), {
            "programme": programme, "season": self.season.id, "crop": self.maize.id, "farmers": [],
        }, format="json")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.lead_api.post(reverse("input-supply-request-set-hectares", kwargs={"pk": 1}), {}, format="json").status_code, 403)

        saved = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "10"), (compound, "10")])])
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["status"], "DRAFT")
        self.assertEqual(saved.data["hectares_total"], "10.00")
        totals = {row["product_name"]: row for row in saved.data["totals"]}
        # 10 ha x 25 kg, priced at $2. The quantity and cost sent by the browser are ignored.
        self.assertEqual(Decimal(totals["Mbizi"]["quantity"]), Decimal("250.0000"))
        self.assertEqual(totals["Mbizi"]["estimated_cost"], "500.00")
        # 10 ha x 400 kg, sold in 50 kg bags at $32: 4,000 / 50 x 32 = 2,560.
        self.assertEqual(Decimal(totals["Compound D"]["quantity"]), Decimal("4000.0000"))
        self.assertEqual(totals["Compound D"]["estimated_cost"], "2560.00")
        self.assertEqual(saved.data["estimated_cost"], "3060.00")

        too_much = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "6"), (self.line(programme, "SEED", self.shumba, "20", "3.00"), "5")])])
        self.assertEqual(too_much.status_code, 400)
        self.assertIn("10.00 ha", str(too_much.data))

        saved = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "10"), (compound, "10")])])
        self.assertEqual(saved.status_code, 200, saved.data)
        submitted = self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], "SUBMITTED")
        self.assertTrue(Notification.objects.filter(kind=Notification.KIND_INPUT_SUPPLY_SUBMITTED, recipient=self.officer).exists())

        early = self.officer_api.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), {}, format="json")
        self.assertEqual(early.status_code, 400)
        self.assertFalse(InputAllocation.objects.filter(allocation_reference=saved.data["reference"]).exists())

        approved_hectares = self.officer_api.post(
            reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}),
            {"mode": "approve", "limits": [{"scope": "CROP", "approved_hectares": "1"}]},
            format="json",
        )
        self.assertEqual(approved_hectares.status_code, 200, approved_hectares.data)
        self.assertEqual(approved_hectares.data["status"], "LIMITS_SET")
        self.assertEqual(approved_hectares.data["stage"], "DISTRIBUTION")
        crop_limit = next(row for row in approved_hectares.data["limits"] if row["scope"] == "CROP")
        # Approve-as-requested ignores the 1 ha the browser sent.
        self.assertEqual(crop_limit["requested_hectares"], "10.00")
        self.assertEqual(crop_limit["approved_hectares"], "10.00")
        self.assertEqual(approved_hectares.data["reviewed_by_name"], "Ada Ncube")
        self.assertFalse(InputAllocation.objects.filter(allocation_reference=saved.data["reference"]).exists())

        final = self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(final.status_code, 200, final.data)
        self.assertEqual(final.data["status"], "CONFIRMATION")
        self.assertIn("FINAL_SUBMITTED", [event["action"] for event in final.data["events"]])

        confirmed = self.officer_api.post(
            reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}),
            {"remarks": "Distribution matches the approved hectares."}, format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["status"], "APPROVED")
        allocation = InputAllocation.objects.get(farmer=self.farmer, allocation_reference=confirmed.data["reference"])
        self.assertEqual(allocation.hectares, Decimal("10.00"))
        self.assertEqual(allocation.total_input_cost, Decimal("3060.00"))
        self.assertEqual(allocation.status, InputAllocation.STATUS_ALLOCATED)
        debt = InputDebt.objects.get(input_allocation=allocation)
        self.assertEqual(debt.total_debt, Decimal("3060.00"))
        self.assertNotEqual(debt.status, InputDebt.STATUS_CANCELLED)

    def test_admin_distributes_a_lower_maximum_and_the_lead_farmer_cannot_exceed_it(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        shumba = self.line(programme, "SEED", self.shumba, "20", "3.00")
        saved = self.save(self.lead_api, programme, [
            (self.farmer, [(mbizi, "10")]),
            (self.third, [(shumba, "10")]),
        ])
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["hectares_total"], "20.00")
        self.assertEqual({row["farmer_name"] for row in saved.data["farmers"]}, {"Tendai Moyo", "Chipo Moyo"})
        self.submit(self.lead_api, saved.data["id"])

        distributed = self.officer_api.post(
            reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}),
            {"mode": "distribute", "remarks": "150 ha is not available; 15 ha is.", "limits": self.limits("15", [("SEED", "15")], [(mbizi, "9"), (shumba, "6")])},
            format="json",
        )
        self.assertEqual(distributed.status_code, 200, distributed.data)
        event = next(row for row in distributed.data["events"] if row["action"] == "LIMITS_DISTRIBUTED")
        self.assertEqual(event["actor_name"], "Ada Ncube")
        self.assertEqual(event["detail"]["limits"][0]["requested_hectares"], "20.00")
        self.assertEqual(event["detail"]["limits"][0]["approved_hectares"], "15.00")
        self.assertEqual(InputSupplyLimit.objects.filter(request_id=saved.data["id"], scope="VARIETY").count(), 2)

        over = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "10")]), (self.third, [(shumba, "10")])])
        self.assertEqual(over.status_code, 400)
        self.assertIn("limited to 15.00 ha", str(over.data))
        variety_over = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "10")]), (self.third, [(shumba, "5")])])
        self.assertEqual(variety_over.status_code, 400)
        self.assertIn("Mbizi", str(variety_over.data))

        within = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "8")]), (self.third, [(shumba, "4")])])
        self.assertEqual(within.status_code, 200, within.data)
        self.assertEqual(within.data["hectares_total"], "12.00")
        crop_limit = next(row for row in within.data["limits"] if row["scope"] == "CROP")
        self.assertEqual(crop_limit["remaining_hectares"], "3.00")
        self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(InputAllocation.objects.filter(allocation_reference=saved.data["reference"]).count(), 0)
        confirmed = self.officer_api.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(InputAllocation.objects.filter(allocation_reference=saved.data["reference"]).count(), 2)
        mbizi_line = InputAllocation.objects.get(farmer=self.farmer, allocation_reference=saved.data["reference"]).calculation_lines.get()
        self.assertEqual(mbizi_line.required_quantity, Decimal("200.0000"))

        adjusted = self.officer_api.post(
            reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}),
            {"mode": "distribute", "limits": self.limits("12", [("SEED", "12")], [(mbizi, "8"), (shumba, "4")])},
            format="json",
        )
        self.assertEqual(adjusted.status_code, 400)

    def test_limits_can_be_lowered_before_confirmation_and_history_keeps_the_change(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        saved = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "10")])])
        self.submit(self.lead_api, saved.data["id"])
        self.officer_api.post(
            reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}),
            {"mode": "approve"}, format="json",
        )
        lowered = self.officer_api.post(
            reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}),
            {"mode": "distribute", "remarks": "Only 4 ha can be supplied.", "limits": self.limits("4", [("SEED", "4")], [(mbizi, "4")])},
            format="json",
        )
        self.assertEqual(lowered.status_code, 200, lowered.data)
        self.assertEqual(lowered.data["status"], "LIMITS_SET")
        change = next(row for row in lowered.data["events"] if row["action"] == "LIMITS_ADJUSTED")
        self.assertEqual(change["detail"]["previous"][0]["approved_hectares"], "10.00")
        self.assertEqual(change["detail"]["limits"][0]["approved_hectares"], "4.00")
        self.assertEqual(change["detail"]["limits"][0]["requested_hectares"], "10.00")
        blocked = self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(blocked.status_code, 400)
        fixed = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "4")])])
        self.assertEqual(fixed.status_code, 200, fixed.data)
        self.assertEqual(self.submit(self.lead_api, saved.data["id"]).status_code, 200)

    def test_return_reject_resubmit_and_reversal(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        shumba = self.line(programme, "SEED", self.shumba, "20", "3.00")

        rejected = self.save(self.other_api, programme, [(self.other_farmer, [(mbizi, "4")])])
        self.submit(self.other_api, rejected.data["id"])
        self.assertEqual(self.admin.post(reverse("input-supply-request-reject", kwargs={"pk": rejected.data["id"]}), {}, format="json").status_code, 400)
        decision = self.admin.post(
            reverse("input-supply-request-reject", kwargs={"pk": rejected.data["id"]}),
            {"remarks": "Wrong variety for this cluster."}, format="json",
        )
        self.assertEqual(decision.status_code, 200, decision.data)
        self.assertEqual(decision.data["status"], "REJECTED")
        self.assertFalse(InputAllocation.objects.filter(allocation_reference=rejected.data["reference"]).exists())

        returned = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "4")])])
        self.submit(self.lead_api, returned.data["id"])
        sent_back = self.admin.post(
            reverse("input-supply-request-return-for-corrections", kwargs={"pk": returned.data["id"]}),
            {"remarks": "Use Shumba, not Mbizi."}, format="json",
        )
        self.assertEqual(sent_back.data["status_label"], "Returned for corrections")
        corrected = self.save(self.lead_api, programme, [(self.farmer, [(shumba, "4")])])
        self.assertEqual(corrected.data["id"], returned.data["id"])
        self.assertEqual(corrected.data["totals"][0]["product_name"], "Shumba")
        self.assertEqual(Decimal(corrected.data["totals"][0]["quantity"]), Decimal("80.0000"))
        resubmitted = self.submit(self.lead_api, returned.data["id"])
        self.assertIn("RESUBMITTED", [event["action"] for event in resubmitted.data["events"]])

        self.admin.post(reverse("input-supply-request-set-hectares", kwargs={"pk": returned.data["id"]}), {"mode": "approve"}, format="json")
        self.submit(self.lead_api, returned.data["id"])
        sent_back = self.admin.post(
            reverse("input-supply-request-return-for-corrections", kwargs={"pk": returned.data["id"]}),
            {"remarks": "Give Chipo some of the hectares."}, format="json",
        )
        self.assertEqual(sent_back.data["stage"], "DISTRIBUTION")
        shared = self.save(self.lead_api, programme, [(self.farmer, [(shumba, "3")]), (self.third, [(shumba, "1")])])
        self.assertEqual(shared.status_code, 200, shared.data)
        again = self.submit(self.lead_api, returned.data["id"])
        self.assertIn("FINAL_RESUBMITTED", [event["action"] for event in again.data["events"]])
        confirmed = self.admin.post(reverse("input-supply-request-approve", kwargs={"pk": returned.data["id"]}), {}, format="json")
        self.assertEqual(confirmed.status_code, 200, confirmed.data)

        not_mine = self.save(self.lead_api, programme, [(self.other_farmer, [(mbizi, "2")])])
        self.assertEqual(not_mine.status_code, 400)
        self.assertIn("not one of your farmers", str(not_mine.data))
        hidden = self.lead_api.get(reverse("input-supply-request-list"))
        self.assertEqual({row["lead_farmer_name"] for row in hidden.data["results"]}, {"John Moyo"})

        reversed_request = self.admin.post(
            reverse("input-supply-request-reverse", kwargs={"pk": returned.data["id"]}),
            {"remarks": "Allocated to the wrong farmer."}, format="json",
        )
        self.assertEqual(reversed_request.status_code, 200, reversed_request.data)
        self.assertEqual(reversed_request.data["status"], "RETURNED")
        allocation = InputAllocation.objects.filter(allocation_reference=returned.data["reference"]).first()
        self.assertEqual(allocation.status, InputAllocation.STATUS_CANCELLED)
        self.assertEqual(InputDebt.objects.get(input_allocation=allocation).status, InputDebt.STATUS_CANCELLED)
        restored = self.save(self.lead_api, programme, [(self.farmer, [(shumba, "4")])])
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertEqual(self.submit(self.lead_api, returned.data["id"]).data["status"], "CONFIRMATION")

    def test_catalogue_is_the_lead_farmers_own_and_programmes_keep_their_own_prices(self):
        arda = self.programme("ARDA prices")
        seedco = self.programme("Seed Co prices")
        arda_mbizi = self.line(arda, "SEED", self.mbizi, "25", "2.00")
        seedco_mbizi = self.line(seedco, "SEED", self.mbizi, "25", "2.50")
        first = self.save(self.lead_api, arda, [(self.farmer, [(arda_mbizi, "4")])])
        second = self.save(self.lead_api, seedco, [(self.third, [(seedco_mbizi, "4")])])
        self.assertEqual(first.data["totals"][0]["estimated_cost"], "200.00")
        self.assertEqual(second.data["totals"][0]["estimated_cost"], "250.00")
        self.assertNotEqual(first.data["id"], second.data["id"])

        catalogue = self.lead_api.get(reverse("input-supply-request-catalogue"), {"season": self.season.id, "crop_season": "SUMMER"})
        self.assertEqual(catalogue.status_code, 200, catalogue.data)
        self.assertEqual([farmer["name"] for farmer in catalogue.data["farmers"]], ["Chipo Moyo", "Tendai Moyo"])
        names = [variety["product_name"] for programme in catalogue.data["programmes"] for crop in programme["crops"] for variety in crop["varieties"]]
        self.assertIn("Mbizi", names)
        self.assertNotIn("cap_quantity", catalogue.data["programmes"][0]["crops"][0]["varieties"][0])
        winter = self.lead_api.get(reverse("input-supply-request-catalogue"), {"season": self.season.id, "crop_season": "WINTER"})
        self.assertEqual(winter.data["programmes"], [])

        self.season.status = Season.STATUS_CLOSED
        self.season.save(update_fields=["status"])
        closed = self.save(self.lead_api, arda, [(self.farmer, [(arda_mbizi, "4")])])
        self.assertEqual(closed.status_code, 400)
        self.assertIn("not the active agricultural year", str(closed.data))

    def test_a_lead_farmer_only_confirms_through_admin_and_cannot_review(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        saved = self.save(self.lead_api, programme, [(self.farmer, [(mbizi, "2")])])
        self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(
            self.lead_api.post(reverse("input-supply-request-set-hectares", kwargs={"pk": saved.data["id"]}), {"mode": "approve"}, format="json").status_code,
            403,
        )
        self.assertEqual(self.lead_api.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), {}, format="json").status_code, 403)
        self.assertEqual(InputSupplyRequest.objects.get(pk=saved.data["id"]).status, InputSupplyRequest.STATUS_SUBMITTED)
        queue = self.officer_api.get(reverse("input-supply-request-list"), {"status": "SUBMITTED", "season": self.season.id})
        self.assertEqual(queue.data["results"][0]["lead_farmer_name"], "John Moyo")
        added = self.save(self.lead_api, programme, [
            (self.farmer, [(mbizi, "2")]),
            (self.third, [(mbizi, "3")]),
        ])
        self.assertEqual(added.status_code, 200, added.data)
        self.assertEqual(added.data["id"], saved.data["id"])
        self.assertEqual(added.data["status"], "SUBMITTED")
        self.assertEqual(added.data["farmer_count"], 2)
        again = self.submit(self.lead_api, saved.data["id"])
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["status"], "SUBMITTED")
        self.assertEqual(again.data["events"][-1]["action"], "RESUBMITTED")
        self.assertEqual(queue.data["results"][0]["crop_season_label"], "Summer")
        summary = self.officer_api.get(reverse("input-supply-request-consolidated"), {"season": self.season.id, "crop_season": "SUMMER"})
        self.assertEqual(summary.data["submitted_count"], 1)
        self.assertEqual(summary.data["confirmation_count"], 0)
