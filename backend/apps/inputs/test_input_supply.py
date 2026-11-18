"""Lead farmers allocate, Admin issues hectare limits, lead farmers redistribute, Admin approves.

Every allocation is its own record: add, change and remove save straight to the database.
Quantities and costs are calculated on the server. There is no variety cap and no stock.
Only Admin's final approval makes allocations official and creates farmer input debts.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Notification
from apps.clusters.models import Cluster
from apps.farmers.models import RegistrationCropAllocation
from apps.inputs.models import InputAllocation, InputSupplyFarmer, InputSupplyRequest
from apps.inputs.test_programme_allocation import make_farmer, make_world
from apps.programmes.models import CropSellingPrice, ProgrammeCrop
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
        for farmer in (cls.farmer, cls.third):
            RegistrationCropAllocation.objects.create(farmer=farmer, crop=cls.sorghum, season=cls.season, hectares=6)
        CropSellingPrice.objects.create(crop=cls.sorghum, season=cls.season, price_per_tonne=Decimal("250.00"))

    def setUp(self):
        self.admin_api = APIClient()
        self.admin_api.force_authenticate(self.admin)
        self.lead_api = APIClient()
        self.lead_api.force_authenticate(self.lead)
        self.other_api = APIClient()
        self.other_api.force_authenticate(self.other_lead)
        self.officer_api = APIClient()
        self.officer_api.force_authenticate(self.officer)
        self.arda = self.programme("ARDA")
        # Catalogue line ids. The products themselves are on the class (Mbizi, Shumba, Compound D).
        self.mbizi = self.line(self.arda, self.maize, "SEED", type(self).mbizi, "25", "2.00")
        self.compound = self.line(self.arda, self.maize, "FERTILIZER", self.compound_d, "400", pack={"pack_size": "50", "pack_price": "32", "pack_label": "50 kg bag"})
        self.sorghum_seed = self.line(self.arda, self.sorghum, "SEED", self.shumba, "10", "4.00")

    def programme(self, name):
        response = self.admin_api.post(reverse("programme-list"), {
            "name": name, "season": self.season.id, "crops": [self.maize.id, self.sorghum.id],
            "input_categories": ["SEED", "FERTILIZER", "CHEMICALS"], "capacity_status": "ACTIVE",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def line(self, programme, crop, category, product, rate, price=None, pack=None):
        payload = {"crop": crop.id, "programme": programme, "input_category": category, "input_product": product.id, "rate_per_hectare": rate}
        payload.update(pack or {"cost_per_unit": price})
        response = self.admin_api.post(reverse("crop-input-requirement-list"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    # API helpers ------------------------------------------------------------------------

    def add(self, farmer, lines, crop=None, client=None, programme=None, submission=None):
        payload = {
            "programme": programme or self.arda, "season": self.season.id, "crop_season": "SUMMER",
            "farmer": farmer.id, "crop": (crop or self.maize).id,
            "lines": [{"requirement": requirement, "hectares": hectares, "quantity": "999", "estimated_cost": "1"} for requirement, hectares in lines],
        }
        if submission:
            payload["submission"] = submission
        return (client or self.lead_api).post(reverse("input-supply-request-allocations"), payload, format="json")

    def entry(self, submission, farmer, crop=None):
        crop = crop or self.maize
        return next(row for row in submission["allocations"] if row["farmer"] == farmer.id and row["crop"] == crop.id)

    def edit(self, row, lines, version=None, client=None):
        return (client or self.lead_api).patch(reverse("input-supply-request-allocation", kwargs={"entry_id": row["id"]}), {
            "version": row["version"] if version is None else version,
            "lines": [{"requirement": requirement, "hectares": hectares} for requirement, hectares in lines],
        }, format="json")

    def remove(self, row, version=None, client=None):
        url = reverse("input-supply-request-allocation", kwargs={"entry_id": row["id"]})
        return (client or self.lead_api).delete(f"{url}?version={row['version'] if version is None else version}")

    def fetch(self, pk, client=None):
        return (client or self.lead_api).get(reverse("input-supply-request-detail", kwargs={"pk": pk})).data

    def act(self, name, pk, client=None, **data):
        return (client or self.admin_api).post(reverse(f"input-supply-request-{name}", kwargs={"pk": pk}), data, format="json")

    def build(self):
        first = self.add(self.farmer, [(self.mbizi, "8"), (self.compound, "8")])
        self.assertEqual(first.status_code, 201, first.data)
        second = self.add(self.third, [(self.mbizi, "5")])
        self.assertEqual(second.status_code, 201, second.data)
        return second.data

    # The whole workflow ------------------------------------------------------------------

    def test_full_workflow_from_allocation_to_approved_debt(self):
        submission = self.build()
        pk = submission["id"]
        self.assertEqual((submission["status"], submission["programme_name"], submission["season_name"], submission["crop_season_label"]), ("DRAFT", "ARDA", "2026/2027", "Summer"))
        row = self.entry(submission, self.farmer)
        lines = {line["product_name"]: line for line in row["lines"]}
        # 8 ha x 25 kg = 200 kg at 2.00; 8 ha x 400 kg = 3,200 kg at 32 per 50 kg bag. Browser figures are ignored.
        self.assertEqual((lines["Mbizi"]["quantity"], lines["Mbizi"]["estimated_cost"]), ("200", "400.00"))
        self.assertEqual((lines["Compound D"]["quantity"], lines["Compound D"]["estimated_cost"]), ("3200", "2048.00"))
        self.assertEqual((submission["hectares_total"], submission["estimated_cost"]), ("13.00", "2698.00"))
        self.assertFalse(InputAllocation.objects.exists())
        self.assertFalse(InputDebt.objects.exists())

        self.assertEqual(self.act("submit", pk, client=self.lead_api).data["status"], "SUBMITTED")
        # Option B: Admin issues lower maximums.
        issued = self.act("set-hectares", pk, mode="distribute", remarks="Seed is short", limits=[
            {"scope": "CROP", "crop": self.maize.id, "approved_hectares": "10"},
            {"scope": "VARIETY", "requirement": self.mbizi, "approved_hectares": "10"},
            {"scope": "VARIETY", "requirement": self.compound, "approved_hectares": "8"},
        ])
        self.assertEqual(issued.status_code, 200, issued.data)
        self.assertEqual(issued.data["status_label"], "Approved limits issued")
        self.assertTrue(Notification.objects.filter(recipient=self.lead, kind=Notification.KIND_INPUT_SUPPLY_DECIDED).exists())
        view = self.fetch(pk)
        limits = {row["name"]: row for row in view["limits"]}
        self.assertEqual((limits["Mbizi"]["requested_hectares"], limits["Mbizi"]["approved_hectares"], limits["Mbizi"]["difference_hectares"], limits["Mbizi"]["distributed_hectares"]), ("13.00", "10.00", "-3.00", "13.00"))
        self.assertEqual((view["requested_hectares"], view["approved_hectares"]), ("13.00", "10.00"))

        # The distribution cannot go past an approved maximum.
        refused = self.act("submit", pk, client=self.lead_api)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Mbizi is limited to 10.00 ha", str(refused.data))
        reduced = self.edit(self.entry(view, self.third), [(self.mbizi, "2")])
        self.assertEqual(reduced.status_code, 200, reduced.data)
        self.assertEqual(self.entry(reduced.data, self.third)["lines"][0]["quantity"], "50")
        self.assertEqual({row["name"]: row["remaining_hectares"] for row in reduced.data["limits"]}["Maize"], "0.00")
        final = self.act("submit", pk, client=self.lead_api)
        self.assertEqual(final.data["status_label"], "Final distribution submitted")

        # Returned for corrections, corrected and resubmitted.
        self.assertEqual(self.act("return-for-corrections", pk, remarks="").status_code, 400)
        returned = self.act("return-for-corrections", pk, remarks="Chipo's farm is wrong")
        self.assertEqual(returned.data["status"], "RETURNED")
        corrected = self.edit(self.entry(returned.data, self.farmer), [(self.mbizi, "8"), (self.compound, "7")])
        self.assertEqual(corrected.status_code, 200, corrected.data)
        self.assertEqual(self.act("submit", pk, client=self.lead_api).data["status"], "CONFIRMATION")
        self.assertFalse(InputDebt.objects.exists())

        approved = self.act("approve", pk, remarks="OK")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "APPROVED")
        allocations = InputAllocation.objects.filter(allocation_reference=approved.data["reference"])
        self.assertEqual(allocations.count(), 2)
        debt = InputDebt.objects.get(input_allocation__farmer=self.farmer)
        self.assertEqual(debt.input_value, Decimal("2192.00"))  # 400.00 + 7 ha x 400 kg / 50 x 32
        self.assertEqual(InputDebt.objects.count(), 2)
        # Approving again creates nothing more.
        again = self.act("approve", pk)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(InputDebt.objects.count(), 2)
        # Approved allocations are locked against changes.
        self.assertEqual(self.edit(self.entry(approved.data, self.farmer), [(self.mbizi, "1")]).status_code, 400)
        actions = [event["action"] for event in approved.data["events"]]
        for expected in ("SUBMITTED", "LIMITS_DISTRIBUTED", "FINAL_SUBMITTED", "RETURNED", "FINAL_RESUBMITTED", "APPROVED"):
            self.assertIn(expected, actions)
        self.assertTrue(approved.data["events"][-1]["detail"]["debts"])

    def test_each_allocation_saves_edits_and_deletes_in_the_database(self):
        created = self.add(self.farmer, [(self.mbizi, "4")])
        self.assertEqual(created.status_code, 201, created.data)
        pk = created.data["id"]
        row = self.entry(created.data, self.farmer)
        # Editing changes the same record and recalculates.
        edited = self.edit(row, [(self.mbizi, "6"), (self.compound, "6")])
        self.assertEqual(edited.status_code, 200, edited.data)
        fresh = self.entry(self.fetch(pk), self.farmer)
        self.assertEqual((fresh["id"], fresh["version"], fresh["hectares"]), (row["id"], row["version"] + 1, "6.00"))
        self.assertEqual(InputSupplyFarmer.objects.count(), 1)
        # An edit from a screen that loaded the old version is refused, not merged.
        stale = self.edit(row, [(self.mbizi, "1")])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.entry(self.fetch(pk), self.farmer)["hectares"], "6.00")
        # The same farmer and crop cannot be added twice.
        self.assertEqual(self.add(self.farmer, [(self.mbizi, "1")]).status_code, 400)
        # A failed edit changes nothing.
        self.assertEqual(self.edit(fresh, [(self.mbizi, "-3")]).status_code, 400)
        self.assertEqual(self.entry(self.fetch(pk), self.farmer)["hectares"], "6.00")
        # Deleting removes the record; reading again does not bring it back.
        self.add(self.third, [(self.mbizi, "2")])
        removed = self.remove(fresh)
        self.assertEqual(removed.status_code, 200, removed.data)
        self.assertEqual([row["farmer"] for row in self.fetch(pk)["allocations"]], [self.third.id])
        self.assertFalse(InputSupplyFarmer.objects.filter(pk=fresh["id"]).exists())
        self.assertEqual(self.fetch(pk)["hectares_total"], "2.00")
        # Removing the last allocation of a draft removes the empty draft.
        last = self.entry(self.fetch(pk), self.third)
        self.assertIsNone(self.remove(last).data["submission"])
        self.assertFalse(InputSupplyRequest.objects.filter(pk=pk).exists())

    def test_one_submission_per_programme_year_and_season_covers_several_crops(self):
        self.add(self.farmer, [(self.mbizi, "5")])
        sorghum = self.add(self.farmer, [(self.sorghum_seed, "4")], crop=self.sorghum)
        self.assertEqual(sorghum.status_code, 201, sorghum.data)
        self.assertEqual(InputSupplyRequest.objects.count(), 1)
        crops = {row["crop_name"]: row for row in sorghum.data["crops"]}
        self.assertEqual((crops["Maize"]["hectares"], crops["Sorghum"]["hectares"]), ("5.00", "4.00"))
        self.assertEqual(crops["Sorghum"]["varieties"][0]["quantity"], "40")
        winter = self.add(self.farmer, [(self.mbizi, "1")], crop=self.wheat)
        self.assertEqual(winter.status_code, 400)
        # Approval creates one official allocation and debt per farmer and crop.
        pk = sorghum.data["id"]
        self.act("submit", pk, client=self.lead_api)
        self.act("set-hectares", pk, mode="approve")
        self.act("submit", pk, client=self.lead_api)
        self.assertEqual(self.act("approve", pk).status_code, 200)
        self.assertEqual(set(InputAllocation.objects.values_list("crop", flat=True)), {"Maize", "Sorghum"})
        self.assertEqual(InputDebt.objects.count(), 2)

    def test_a_lead_farmer_sends_farmers_in_several_submissions(self):
        # First submission: one farmer, sent to Admin.
        first = self.add(self.farmer, [(self.mbizi, "6")])
        self.assertEqual(first.status_code, 201, first.data)
        first_id = first.data["id"]
        self.assertEqual(self.act("submit", first_id, client=self.lead_api).data["status"], "SUBMITTED")
        # It stays as sent: nothing more can be added to it while Admin has it.
        late = self.add(self.third, [(self.mbizi, "4")], submission=first_id)
        self.assertEqual(late.status_code, 400)
        self.assertIn("Add more farmers in a new submission", str(late.data))
        # New farmers start a second submission for the same programme and season.
        second = self.add(self.third, [(self.mbizi, "4")])
        self.assertEqual(second.status_code, 201, second.data)
        second_id = second.data["id"]
        self.assertNotEqual(second_id, first_id)
        self.assertEqual(second.data["status"], "DRAFT")
        # Only one draft at a time: the next farmer joins it.
        sorghum = self.add(self.farmer, [(self.sorghum_seed, "3")], crop=self.sorghum)
        self.assertEqual(sorghum.data["id"], second_id)
        # The same farmer's crop cannot be sent twice while the first is undecided.
        twice = self.add(self.farmer, [(self.compound, "2")])
        self.assertEqual(twice.status_code, 400)
        self.assertIn(first.data["reference"], str(twice.data))
        self.assertEqual(self.act("submit", second_id, client=self.lead_api).data["status"], "SUBMITTED")
        # Admin decides on each independently; each approval adds to the programme's allocated hectares.
        figures = lambda: self.admin_api.get(reverse("programme-figures", kwargs={"pk": self.arda})).data["totals"]["allocated_hectares"]
        self.assertEqual(Decimal(figures()), Decimal("0"))
        for pk, expected in ((first_id, "6"), (second_id, "13")):
            self.act("set-hectares", pk, mode="approve")
            self.assertEqual(self.act("submit", pk, client=self.lead_api).data["status"], "CONFIRMATION")
            self.assertEqual(self.act("approve", pk).status_code, 200)
            self.assertEqual(Decimal(figures()), Decimal(expected))
        self.assertEqual(InputAllocation.objects.count(), 3)
        self.assertEqual(InputDebt.objects.count(), 3)
        # Once the first is approved, a later submission can still add that farmer's other inputs.
        fertilizer = self.add(self.farmer, [(self.compound, "2")])
        self.assertEqual(fertilizer.status_code, 201, fertilizer.data)
        self.assertNotIn(fertilizer.data["id"], (first_id, second_id))

    def test_eligibility_and_access_are_enforced_on_the_server(self):
        too_much = self.add(self.farmer, [(self.mbizi, "12")])
        self.assertEqual(too_much.status_code, 400)
        self.assertIn("intends to plant 10.00 ha", str(too_much.data))
        self.assertEqual(self.add(self.other_farmer, [(self.mbizi, "2")]).status_code, 400)  # not this lead's farmer
        made = self.add(self.farmer, [(self.mbizi, "8")])
        # Hectares in another programme's submission count too.
        seedco = self.programme("SEEDCO")
        seedco_mbizi = self.line(seedco, self.maize, "SEED", self.shumba, "20", "3.00")
        self.assertEqual(self.add(self.farmer, [(seedco_mbizi, "5")], programme=seedco).status_code, 400)
        self.assertEqual(self.add(self.farmer, [(seedco_mbizi, "2")], programme=seedco).status_code, 201)
        # Another lead farmer cannot see or change this lead farmer's allocations.
        row = self.entry(made.data, self.farmer)
        self.assertEqual(self.other_api.get(reverse("input-supply-request-detail", kwargs={"pk": made.data["id"]})).status_code, 404)
        self.assertEqual(self.edit(row, [(self.mbizi, "1")], client=self.other_api).status_code, 400)
        self.assertEqual(self.remove(row, client=self.other_api).status_code, 400)
        # Lead farmers cannot decide; officers can.
        self.act("submit", made.data["id"], client=self.lead_api)
        self.assertEqual(self.act("set-hectares", made.data["id"], client=self.lead_api, mode="approve").status_code, 403)
        self.assertEqual(self.act("set-hectares", made.data["id"], client=self.officer_api, mode="approve").status_code, 200)
        self.assertEqual(self.officer_api.post(reverse("input-supply-request-allocations"), {}, format="json").status_code, 403)

    def test_changing_limits_after_the_final_submission_sends_it_back_for_review(self):
        pk = self.build()["id"]
        self.act("submit", pk, client=self.lead_api)
        self.act("set-hectares", pk, mode="approve")
        self.assertEqual(self.act("submit", pk, client=self.lead_api).data["status"], "CONFIRMATION")
        lowered = self.act("set-hectares", pk, mode="distribute", limits=[{"scope": "VARIETY", "requirement": self.mbizi, "approved_hectares": "9"}])
        self.assertEqual(lowered.status_code, 200, lowered.data)
        self.assertEqual((lowered.data["status"], lowered.data["limits_changed"]), ("LIMITS_SET", True))
        notice = Notification.objects.filter(recipient=self.lead).order_by("-id").first()
        self.assertIn("no longer fits", notice.body)
        self.assertEqual(self.act("approve", pk).status_code, 400)
        history = [event for event in lowered.data["events"] if event["action"] == "LIMITS_ADJUSTED"]
        self.assertTrue(history and history[-1]["detail"]["previous"])

    def test_rejected_submission_stays_in_history_without_debt(self):
        pk = self.build()["id"]
        self.act("submit", pk, client=self.lead_api)
        self.assertEqual(self.act("reject", pk, remarks="").status_code, 400)
        rejected = self.act("reject", pk, remarks="Not in this programme")
        self.assertEqual(rejected.data["status"], "REJECTED")
        self.assertFalse(InputAllocation.objects.exists())
        self.assertTrue(InputSupplyRequest.objects.filter(pk=pk).exists())
        self.assertEqual(self.fetch(pk)["decision_notes"], "Not in this programme")
        # The farmer's hectares are free again for a new submission.
        self.assertEqual(self.add(self.farmer, [(self.mbizi, "8")]).status_code, 201)
        self.assertEqual(InputSupplyRequest.objects.exclude(pk=pk).count(), 1)

    def test_consolidated_view_for_admin(self):
        ruth_farmer = make_farmer(type(self), "Panashe", "63-2222222D12", maize_hectares=10)
        ruth_farmer.cluster = self.other_cluster
        ruth_farmer.save(update_fields=["cluster"])
        self.build()
        self.add(ruth_farmer, [(self.mbizi, "9")], client=self.other_api)
        summary = self.admin_api.get(reverse("input-supply-request-consolidated"), {"season": self.season.id, "crop_season": "SUMMER"}).data
        self.assertEqual(sorted(row["lead_farmer_name"] for row in summary["lead_farmers"]), ["John Moyo", "Ruth Dube"])
        mbizi = next(row for row in summary["varieties"] if row["product_name"] == "Mbizi")
        self.assertEqual((mbizi["hectares"], mbizi["quantity"], mbizi["lead_farmers"]), ("22.00", "550", 2))
        self.assertEqual(self.lead_api.get(reverse("input-supply-request-consolidated"), {"season": self.season.id}).status_code, 403)

    def test_earlier_records_are_left_alone(self):
        # An allocation made through the earlier admin screen stays official and blocks a second seed allocation.
        ProgrammeCrop.objects.get_or_create(programme_id=self.arda, crop=self.maize)
        InputAllocation.objects.create(farmer=self.farmer, programme_id=self.arda, season=self.season, crop_reference=self.maize, crop="Maize", hectares=4, status="ALLOCATED")
        self.assertEqual(self.add(self.farmer, [(self.mbizi, "8")]).status_code, 400)
        self.assertEqual(self.add(self.farmer, [(self.mbizi, "6")]).status_code, 400)  # earlier allocations cover every input
        self.assertEqual(InputSupplyRequest.objects.count(), 0)
