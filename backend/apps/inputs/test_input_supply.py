"""Admin sets variety caps. Lead farmers allocate them and submit. Admin approves.

Approval consumes the cap. A rejection, a return and a reversal do not. Two lead farmers
cannot be given more than the cap between them.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Notification
from apps.clusters.models import Cluster
from apps.inputs.models import InputAllocation, InputSupplyRequest, ProgrammeVarietyCap
from apps.inputs.test_programme_allocation import make_farmer, make_world
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

    def programme(self):
        response = self.admin.post(reverse("programme-list"), {
            "name": "ARDA", "season": self.season.id, "crops": [self.maize.id],
            "input_categories": ["SEED", "FERTILIZER", "CHEMICALS"], "capacity_status": "ACTIVE",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def line(self, programme, category, product, rate, price):
        response = self.admin.post(reverse("crop-input-requirement-list"), {
            "crop": self.maize.id, "programme": programme, "input_category": category,
            "input_product": product.id, "rate_per_hectare": rate, "cost_per_unit": price,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def cap(self, programme, requirement, quantity, client=None):
        response = (client or self.admin).post(reverse("programme-variety-cap-list"), {
            "programme": programme, "season": self.season.id, "crop": self.maize.id,
            "requirement": requirement, "cap_quantity": quantity,
        }, format="json")
        return response

    def farmers_payload(self, farmer, requirements, hectares="10.00"):
        return [{
            "farmer": farmer.id,
            "farm": farmer.farms.first().id,
            "hectares": hectares,
            "requirements": requirements,
        }]

    def save(self, client, programme, requirements, farmer=None, hectares="10.00"):
        return client.post(reverse("input-supply-request-list"), {
            "programme": programme, "season": self.season.id, "crop": self.maize.id,
            "farmers": self.farmers_payload(farmer or self.farmer, requirements, hectares),
        }, format="json")

    def test_lead_farmer_submits_and_approval_consumes_the_variety_cap(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        compound = self.line(programme, "FERTILIZER", self.compound_d, "400", "0.64")
        atrazine = self.line(programme, "CHEMICALS", self.atrazine, "2", "9.50")
        shumba = self.line(programme, "SEED", self.shumba, "20", "3.00")
        for requirement, quantity, unit in ((mbizi, "5000", "kg"), (shumba, "3000", "kg"), (compound, "20000", "kg"), (atrazine, "500", "litres")):
            created = self.cap(programme, requirement, quantity)
            self.assertEqual(created.status_code, 201, created.data)
            self.assertEqual(created.data["unit"], unit)
            self.assertEqual(created.data["remaining_quantity"], f"{Decimal(quantity):.4f}")

        # Admin does not allocate to farmers.
        refused = self.admin.post(reverse("input-supply-request-list"), {
            "programme": programme, "season": self.season.id, "crop": self.maize.id, "farmers": [],
        }, format="json")
        self.assertEqual(refused.status_code, 403)

        saved = self.save(self.lead_api, programme, [mbizi, compound, atrazine])
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["status"], "DRAFT")
        totals = {row["product_name"]: Decimal(row["quantity"]) for row in saved.data["totals"]}
        # 10 ha x catalogue rate. The lead farmer does not type these totals.
        self.assertEqual(totals, {"Mbizi": Decimal("250.0000"), "Compound D": Decimal("4000.0000"), "Atrazine": Decimal("20.0000")})
        self.assertEqual(saved.data["farmer_count"], 1)

        submitted = self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": saved.data["id"]}))
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], "SUBMITTED")
        self.assertTrue(Notification.objects.filter(kind=Notification.KIND_INPUT_SUPPLY_SUBMITTED, recipient=self.officer).exists())

        queue = self.officer_api.get(reverse("input-supply-request-list"), {"status": "SUBMITTED", "season": self.season.id})
        self.assertEqual(queue.status_code, 200)
        self.assertEqual(queue.data["results"][0]["lead_farmer_name"], "John Moyo")
        self.assertEqual(queue.data["results"][0]["crop_season_label"], "Summer")

        approved = self.officer_api.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), {"remarks": "Within the caps."}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "APPROVED")
        self.assertEqual(approved.data["reviewed_by_name"], "Ada Ncube")
        self.assertTrue(InputAllocation.objects.filter(farmer=self.farmer, allocation_reference=approved.data["reference"]).exists())
        self.assertTrue(InputDebt.objects.filter(farmer=self.farmer, status__in=["NOT_RECOVERED", "PARTIALLY_RECOVERED", "FULLY_RECOVERED"]).exists())

        mbizi_cap = ProgrammeVarietyCap.objects.get(requirement_id=mbizi)
        figures = self.admin.get(reverse("programme-variety-cap-detail", kwargs={"pk": mbizi_cap.id})).data
        self.assertEqual(Decimal(figures["approved_quantity"]), Decimal("250.0000"))
        self.assertEqual(Decimal(figures["remaining_quantity"]), Decimal("4750.0000"))
        self.assertTrue(Notification.objects.filter(kind=Notification.KIND_INPUT_SUPPLY_DECIDED, recipient=self.lead).exists())

        # An approved request is not edited in place, by the lead farmer or by Admin.
        self.assertIn(self.lead_api.patch(reverse("input-supply-request-detail", kwargs={"pk": saved.data["id"]}), {"farmers": []}, format="json").status_code, (403, 405))
        self.assertIn(self.admin.patch(reverse("input-supply-request-detail", kwargs={"pk": saved.data["id"]}), {"status": "DRAFT"}, format="json").status_code, (403, 405))
        self.assertEqual(InputSupplyRequest.objects.get(pk=saved.data["id"]).status, InputSupplyRequest.STATUS_APPROVED)
        too_much = self.save(self.lead_api, programme, [shumba], farmer=self.farmer, hectares="10")
        self.assertEqual(too_much.status_code, 400)
        self.assertIn("10.00 ha", str(too_much.data))

    def test_two_lead_farmers_cannot_exceed_one_cap(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        created = self.cap(programme, mbizi, "300")
        self.assertEqual(created.status_code, 201, created.data)

        first = self.save(self.lead_api, programme, [mbizi])
        second = self.save(self.other_api, programme, [mbizi], farmer=self.other_farmer)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": first.data["id"]})).status_code, 200)
        blocked = self.other_api.post(reverse("input-supply-request-submit", kwargs={"pk": second.data["id"]}))
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("Mbizi", str(blocked.data))
        self.assertEqual(InputSupplyRequest.objects.get(pk=second.data["id"]).status, InputSupplyRequest.STATUS_DRAFT)
        self.assertEqual(ProgrammeVarietyCap.objects.get(pk=created.data["id"]).cap_quantity, Decimal("300.0000"))
        self.assertFalse(InputAllocation.objects.filter(allocation_reference=second.data["reference"]).exists())

    def test_reject_and_return_do_not_consume_the_cap_and_a_return_can_be_resubmitted(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        shumba = self.line(programme, "SEED", self.shumba, "20", "3.00")
        self.cap(programme, mbizi, "1000")
        self.cap(programme, shumba, "1000")

        rejected = self.save(self.other_api, programme, [mbizi], farmer=self.other_farmer, hectares="4")
        self.other_api.post(reverse("input-supply-request-submit", kwargs={"pk": rejected.data["id"]}))
        no_reason = self.admin.post(reverse("input-supply-request-reject", kwargs={"pk": rejected.data["id"]}), {}, format="json")
        self.assertEqual(no_reason.status_code, 400)
        decision = self.admin.post(reverse("input-supply-request-reject", kwargs={"pk": rejected.data["id"]}), {"remarks": "Wrong variety for this cluster."}, format="json")
        self.assertEqual(decision.status_code, 200, decision.data)
        self.assertEqual(decision.data["status"], "REJECTED")
        self.assertEqual(self.other_api.get(reverse("input-supply-request-detail", kwargs={"pk": rejected.data["id"]})).data["decision_notes"], "Wrong variety for this cluster.")

        returned = self.save(self.lead_api, programme, [mbizi], hectares="4")
        self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": returned.data["id"]}))
        sent_back = self.admin.post(
            reverse("input-supply-request-return-for-corrections", kwargs={"pk": returned.data["id"]}),
            {"remarks": "Use Shumba, not Mbizi."}, format="json",
        )
        self.assertEqual(sent_back.status_code, 200, sent_back.data)
        self.assertEqual(sent_back.data["status_label"], "Returned for corrections")
        seen = self.lead_api.get(reverse("input-supply-request-detail", kwargs={"pk": returned.data["id"]})).data
        self.assertEqual(seen["decision_notes"], "Use Shumba, not Mbizi.")
        self.assertIn("RETURNED", [event["action"] for event in seen["events"]])

        # While it is returned, and after the rejection, nothing is reserved.
        mbizi_cap = self.admin.get(reverse("programme-variety-cap-detail", kwargs={"pk": ProgrammeVarietyCap.objects.get(requirement_id=mbizi).id})).data
        self.assertEqual(Decimal(mbizi_cap["approved_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(mbizi_cap["submitted_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(mbizi_cap["remaining_quantity"]), Decimal("1000"))

        corrected = self.save(self.lead_api, programme, [shumba], hectares="4")
        self.assertEqual(corrected.status_code, 200, corrected.data)
        self.assertEqual(corrected.data["id"], returned.data["id"])
        self.assertEqual(corrected.data["totals"][0]["product_name"], "Shumba")
        self.assertEqual(Decimal(corrected.data["totals"][0]["quantity"]), Decimal("80.0000"))
        resubmitted = self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": returned.data["id"]}))
        self.assertEqual(resubmitted.status_code, 200, resubmitted.data)
        self.assertEqual(resubmitted.data["status"], "SUBMITTED")
        self.assertIn("RESUBMITTED", [event["action"] for event in resubmitted.data["events"]])
        approved = self.admin.post(reverse("input-supply-request-approve", kwargs={"pk": returned.data["id"]}), format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        shumba_cap = self.admin.get(reverse("programme-variety-cap-detail", kwargs={"pk": ProgrammeVarietyCap.objects.get(requirement_id=shumba).id})).data
        self.assertEqual(Decimal(shumba_cap["approved_quantity"]), Decimal("80.0000"))
        self.assertEqual(Decimal(shumba_cap["remaining_quantity"]), Decimal("920.0000"))

    def test_reversal_releases_the_cap_and_the_lead_farmer_only_sees_their_farmers(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        self.cap(programme, mbizi, "1000")
        saved = self.save(self.lead_api, programme, [mbizi], hectares="2")
        self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": saved.data["id"]}))
        self.admin.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), format="json")

        not_mine = self.save(self.lead_api, programme, [mbizi], farmer=self.other_farmer, hectares="2")
        self.assertEqual(not_mine.status_code, 400)
        self.assertIn("not one of your farmers", str(not_mine.data))
        hidden = self.lead_api.get(reverse("input-supply-request-list"))
        self.assertEqual([row["lead_farmer_name"] for row in hidden.data["results"]], ["John Moyo"])

        reversed_request = self.admin.post(
            reverse("input-supply-request-reverse", kwargs={"pk": saved.data["id"]}),
            {"remarks": "Allocated to the wrong farmer."}, format="json",
        )
        self.assertEqual(reversed_request.status_code, 200, reversed_request.data)
        self.assertEqual(reversed_request.data["status"], "RETURNED")
        allocation = InputAllocation.objects.get(allocation_reference=saved.data["reference"])
        self.assertEqual(allocation.status, InputAllocation.STATUS_CANCELLED)
        debt = InputDebt.objects.get(input_allocation=allocation)
        self.assertEqual(debt.status, InputDebt.STATUS_CANCELLED)
        cap = self.admin.get(reverse("programme-variety-cap-detail", kwargs={"pk": ProgrammeVarietyCap.objects.get(requirement_id=mbizi).id})).data
        self.assertEqual(Decimal(cap["approved_quantity"]), Decimal("0"))
        self.assertEqual(Decimal(cap["remaining_quantity"]), Decimal("1000"))

        again = self.save(self.lead_api, programme, [mbizi], hectares="2")
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": again.data["id"]})).status_code, 200)

    def test_cap_cannot_drop_below_what_is_already_approved_and_catalogue_is_scoped(self):
        programme = self.programme()
        mbizi = self.line(programme, "SEED", self.mbizi, "25", "2.00")
        created = self.cap(programme, mbizi, "1000")
        saved = self.save(self.lead_api, programme, [mbizi], hectares="4")
        self.lead_api.post(reverse("input-supply-request-submit", kwargs={"pk": saved.data["id"]}))
        self.admin.post(reverse("input-supply-request-approve", kwargs={"pk": saved.data["id"]}), format="json")
        lowered = self.admin.patch(reverse("programme-variety-cap-detail", kwargs={"pk": created.data["id"]}), {"cap_quantity": "10"}, format="json")
        self.assertEqual(lowered.status_code, 400)
        self.assertIn("cannot be lower", str(lowered.data))

        catalogue = self.lead_api.get(reverse("input-supply-request-catalogue"), {"season": self.season.id, "crop_season": "SUMMER"})
        self.assertEqual(catalogue.status_code, 200, catalogue.data)
        self.assertEqual([farmer["name"] for farmer in catalogue.data["farmers"]], ["Chipo Moyo", "Tendai Moyo"])
        self.assertNotIn("Rudo Moyo", [farmer["name"] for farmer in catalogue.data["farmers"]])
        varieties = catalogue.data["programmes"][0]["crops"][0]["varieties"]
        self.assertEqual(varieties[0]["product_name"], "Mbizi")
        self.assertEqual(Decimal(varieties[0]["remaining_quantity"]), Decimal("900.0000"))

        combined = self.admin.get(reverse("input-supply-request-consolidated"), {"season": self.season.id, "crop_season": "SUMMER"})
        self.assertEqual(combined.status_code, 200)
        self.assertEqual(Decimal(combined.data["caps"][0]["approved_quantity"]), Decimal("100.0000"))
