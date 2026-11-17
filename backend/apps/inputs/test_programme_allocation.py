"""Programme -> programme crop catalogue -> approved input request -> input allocation -> farmer.

The whole chain is driven through the API the pages use, as an authorised officer would.
"""

import threading
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDARequestBatch
from apps.farmers.models import Farm, Farmer, RegistrationCropAllocation
from apps.geography.models import District, Province
from apps.inputs import programme_allocation
from apps.inputs.models import Input, InputAllocation
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Programme, ProgrammeCrop, Season
from apps.recovery.models import InputDebt
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()


def make_world(test):
    test.admin = User.objects.create_user(email="officer@example.com", username="officer", password="Str0ng!Passw0rd", role=User.ROLE_SUPER_ADMIN)
    test.viewer = User.objects.create_user(email="viewer@example.com", username="viewer", password="Str0ng!Passw0rd", role=User.ROLE_VIEWER)
    test.province = Province.objects.create(name="Mashonaland East", code="ME")
    test.district = District.objects.create(province=test.province, name="Marondera")
    test.season = Season.objects.create(name="2026/2027", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30), status=Season.STATUS_ACTIVE)
    test.maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
    test.sorghum = Crop.objects.create(name="Sorghum", category=Crop.CATEGORY_SUMMER)
    test.wheat = Crop.objects.create(name="Wheat", category=Crop.CATEGORY_WINTER)
    CropSellingPrice.objects.create(crop=test.maize, season=test.season, price_per_tonne=Decimal("300.00"))
    test.mbizi = Input.objects.create(name="Mbizi", category="SEED", unit="kg")
    test.shumba = Input.objects.create(name="Shumba", category="SEED", unit="kg")
    test.compound_d = Input.objects.create(name="Compound D", category="FERTILIZER", unit="kg")
    test.atrazine = Input.objects.create(name="Atrazine", category="CHEMICALS", unit="litres")
    test.farmer = make_farmer(test, "Tendai", "63-1234567A12", maize_hectares=10)
    test.other_farmer = make_farmer(test, "Rudo", "63-7654321B12", maize_hectares=10)


def make_farmer(test, name, national_id, maize_hectares):
    farmer = Farmer.objects.create(
        first_name=name, surname="Moyo", national_id=national_id, province=test.province, district=test.district,
        verification_status=Farmer.STATUS_VERIFIED, membership_status=Farmer.MEMBERSHIP_ACTIVE,
    )
    Farm.objects.create(farmer=farmer, farm_name=f"{name} Farm", province=test.province, district=test.district, total_hectares=40, arable_hectares=30)
    FarmerSubscription.objects.create(farmer=farmer, season=test.season.name, expected_amount=500, paid_amount=500, outstanding_amount=0, payment_status="PAID")
    RegistrationCropAllocation.objects.create(farmer=farmer, crop=test.maize, season=test.season, hectares=maize_hectares)
    return farmer


class ChainMixin:
    def api(self, user=None):
        client = APIClient()
        client.force_authenticate(user or self.admin)
        return client

    def programme(self, name, crops, categories, client=None):
        response = (client or self.client).post(reverse("programme-list"), {
            "name": name, "season": self.season.id, "crops": [crop.id for crop in crops],
            "input_categories": categories, "capacity_status": "ACTIVE",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return Programme.objects.get(pk=response.data["id"])

    def line(self, programme, crop, category, product, rate, price=None, pack_size=None, pack_price=None, pack_label=""):
        payload = {"crop": crop.id, "programme": programme.id, "input_category": category, "input_product": product.id, "rate_per_hectare": rate}
        if pack_size:
            payload.update({"pack_size": pack_size, "pack_price": pack_price, "pack_label": pack_label})
        else:
            payload["cost_per_unit"] = price
        response = self.client.post(reverse("crop-input-requirement-list"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return CropInputRequirement.objects.get(pk=response.data["id"])

    def request(self, programme, crop, hectares, category=""):
        response = self.client.post(reverse("arda-request-batch-list"), {
            "programme": programme.id, "season": self.season.id, "crop": crop.name, "requested_hectares": hectares, "input_category": category,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return ARDARequestBatch.objects.get(pk=response.data["id"])

    def approve(self, batch, hectares=None):
        self.assertEqual(self.client.post(reverse("arda-request-batch-submit", kwargs={"pk": batch.id})).status_code, 200)
        response = self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {"approved_hectares": hectares} if hectares else {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        batch.refresh_from_db()
        return batch

    def payload(self, programme, batch, hectares="10", farmer=None, crop=None, categories=None):
        farmer = farmer or self.farmer
        data = {
            "farmer": farmer.id, "farm": farmer.farms.first().id, "season": self.season.id, "crop": (crop or self.maize).id,
            "programme": programme.id, "request_batch": batch.id, "hectares": hectares,
        }
        if categories:
            data["input_categories"] = categories
        return data

    def allocate(self, *args, client=None, **kwargs):
        return (client or self.client).post(reverse("input-allocation-programme-allocate"), self.payload(*args, **kwargs), format="json")

    def preview(self, *args, **kwargs):
        return self.client.post(reverse("input-allocation-programme-preview"), self.payload(*args, **kwargs), format="json")

    def batch_row(self, batch):
        return self.client.get(reverse("arda-request-batch-detail", kwargs={"pk": batch.id})).data


class ProgrammeChainTests(ChainMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        make_world(cls)

    def setUp(self):
        self.client = self.api()

    # Programmes ------------------------------------------------------------------------

    def test_programme_supports_several_crops_and_input_types(self):
        arda = self.programme("ARDA", [self.maize, self.sorghum], ["SEED", "FERTILIZER"])
        row = self.client.get(reverse("programme-detail", kwargs={"pk": arda.id})).data
        self.assertEqual(row["crop_names"], ["Maize", "Sorghum"])
        self.assertEqual(row["input_category_labels"], ["Seed", "Fertilizer"])
        self.assertEqual((row["capacity_status"], row["code"] != ""), ("ACTIVE", True))
        self.assertEqual(row["figures"]["crops"], 2)
        # Removing a crop keeps the link as history but the crop is no longer offered.
        self.client.patch(reverse("programme-detail", kwargs={"pk": arda.id}), {"crops": [self.maize.id]}, format="json")
        self.assertEqual(list(arda.supported_crops().values_list("name", flat=True)), ["Maize"])
        self.assertFalse(ProgrammeCrop.objects.get(programme=arda, crop=self.sorghum).active)
        # The form asks for at least one crop and one input type, and a name only once per year.
        self.assertEqual(self.client.post(reverse("programme-list"), {"name": "No crops", "season": self.season.id, "input_categories": ["SEED"]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("programme-list"), {"name": "No inputs", "season": self.season.id, "crops": [self.maize.id]}, format="json").status_code, 400)
        again = self.client.post(reverse("programme-list"), {"name": "arda", "season": self.season.id, "crops": [self.maize.id], "input_categories": ["SEED"]}, format="json")
        self.assertEqual(again.status_code, 400)
        filtered = self.client.get(reverse("programme-list"), {"crop": self.sorghum.id}).data["results"]
        self.assertEqual(filtered, [])

    def test_same_crop_under_two_programmes_has_independent_catalogues(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        seedco = self.programme("Seed Co", [self.maize], ["SEED"])
        arda_mbizi = self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        seedco_mbizi = self.line(seedco, self.maize, "SEED", self.mbizi, "25", "2.50")
        self.line(seedco, self.maize, "SEED", self.shumba, "20", "3.00")
        self.client.patch(reverse("crop-input-requirement-detail", kwargs={"pk": arda_mbizi.id}), {"cost_per_unit": "1.75"}, format="json")
        seedco_mbizi.refresh_from_db()
        self.assertEqual(seedco_mbizi.cost_per_unit, Decimal("2.5000"))
        rows = self.client.get(reverse("crop-input-requirement-list"), {"crop": self.maize.id, "programme": arda.id}).data["results"]
        self.assertEqual([row["input_product_name"] for row in rows], ["Mbizi"])

    def test_catalogue_accepts_only_the_programmes_crops_and_input_types(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        wrong_crop = self.client.post(reverse("crop-input-requirement-list"), {
            "crop": self.wheat.id, "programme": arda.id, "input_category": "SEED", "input_product": self.mbizi.id, "rate_per_hectare": "25", "cost_per_unit": "2",
        }, format="json")
        self.assertEqual(wrong_crop.status_code, 400)
        self.assertIn("does not support Wheat", str(wrong_crop.data))
        wrong_type = self.client.post(reverse("crop-input-requirement-list"), {
            "crop": self.maize.id, "programme": arda.id, "input_category": "CHEMICALS", "input_product": self.atrazine.id, "rate_per_hectare": "2", "cost_per_unit": "9",
        }, format="json")
        self.assertEqual(wrong_type.status_code, 400)
        self.assertIn("does not supply chemicals", str(wrong_type.data))
        general = self.client.post(reverse("crop-input-requirement-list"), {
            "crop": self.maize.id, "group_name": "Seed", "item_name": "Loose", "rate_per_hectare": "2", "cost_per_unit": "9",
        }, format="json")
        self.assertEqual(general.status_code, 400)

    def test_pack_and_unit_calculations(self):
        arda = self.programme("ARDA", [self.maize], ["FERTILIZER", "CHEMICALS"])
        compound = self.line(arda, self.maize, "FERTILIZER", self.compound_d, "400", pack_size="50", pack_price="32", pack_label="50 kg bag")
        self.assertEqual((compound.cost_per_unit, compound.cost_per_hectare), (Decimal("0.6400"), Decimal("256.0000")))
        self.line(arda, self.maize, "CHEMICALS", self.atrazine, "2", "9.50")
        batch = self.approve(self.request(arda, self.maize, "100"))
        plan = self.preview(arda, batch, hectares="5")
        self.assertEqual(plan.status_code, 200, plan.data)
        lines = {line["product_name"]: line for entry in plan.data["categories"] for line in entry["lines"]}
        self.assertEqual((lines["Compound D"]["required_quantity"], lines["Compound D"]["cost"], lines["Compound D"]["packs"]), ("2000", "1280.00", "40"))
        self.assertEqual((lines["Atrazine"]["required_quantity"], lines["Atrazine"]["unit"], lines["Atrazine"]["cost"]), ("10", "litres", "95.00"))
        self.assertEqual(plan.data["total_cost"], "1375.00")

    # Input requests --------------------------------------------------------------------

    def test_request_workflow_and_only_approved_requests_can_be_allocated(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.request(arda, self.maize, "300")
        self.assertEqual(self.batch_row(batch)["status_label"], "Draft")
        self.assertEqual(self.allocate(arda, batch).status_code, 400)  # draft
        self.client.post(reverse("arda-request-batch-submit", kwargs={"pk": batch.id}))
        refused = self.allocate(arda, batch)
        self.assertEqual(refused.status_code, 400)  # submitted, not approved
        self.assertIn("Only approved requests", str(refused.data))
        # A submitted request cannot be edited, and approval cannot exceed what was requested.
        self.assertEqual(self.client.patch(reverse("arda-request-batch-detail", kwargs={"pk": batch.id}), {"requested_hectares": "10"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {"approved_hectares": "301"}, format="json").status_code, 400)
        approved = self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {"approved_hectares": "200", "notes": "Partial"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual((approved.data["requested_hectares"], approved.data["approved_hectares"], approved.data["remaining_hectares"]), ("300.00", Decimal("200.00"), Decimal("200.00")))
        self.assertEqual(approved.data["approved_by_name"], self.admin.username)
        self.assertEqual(self.allocate(arda, batch).status_code, 201)
        row = self.batch_row(batch)
        self.assertEqual((row["allocated_hectares"], row["remaining_hectares"], row["total_farmers"]), (Decimal("10.00"), Decimal("190.00"), 1))

    def test_rejected_requests_give_no_hectares(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.request(arda, self.maize, "50")
        self.client.post(reverse("arda-request-batch-submit", kwargs={"pk": batch.id}))
        self.assertEqual(self.client.post(reverse("arda-request-batch-reject", kwargs={"pk": batch.id}), {}, format="json").status_code, 400)
        rejected = self.client.post(reverse("arda-request-batch-reject", kwargs={"pk": batch.id}), {"notes": "No budget"}, format="json")
        self.assertEqual((rejected.status_code, rejected.data["status"], rejected.data["approved_hectares"]), (200, "REJECTED", Decimal("0.00")))
        self.assertEqual(self.allocate(arda, batch).status_code, 400)

    def test_request_must_match_its_programme(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        wheat = self.client.post(reverse("arda-request-batch-list"), {"programme": arda.id, "season": self.season.id, "crop": "Wheat", "requested_hectares": "10"}, format="json")
        self.assertEqual(wheat.status_code, 400)
        chemicals = self.client.post(reverse("arda-request-batch-list"), {
            "programme": arda.id, "season": self.season.id, "crop": "Maize", "requested_hectares": "10", "input_category": "CHEMICALS",
        }, format="json")
        self.assertEqual(chemicals.status_code, 400)
        self.request(arda, self.maize, "10")
        duplicate = self.client.post(reverse("arda-request-batch-list"), {"programme": arda.id, "season": self.season.id, "crop": "Maize", "requested_hectares": "5"}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    # Allocations -----------------------------------------------------------------------

    def test_allocation_cannot_exceed_approved_hectares(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "20"), hectares="12")
        too_much = self.preview(arda, batch, hectares="8")
        self.assertEqual(self.allocate(arda, batch, hectares="8").status_code, 201)
        self.assertTrue(too_much.data["can_confirm"])
        second = self.preview(arda, batch, hectares="5", farmer=self.other_farmer)
        self.assertFalse(second.data["can_confirm"])
        self.assertIn("4 ha of its 12 approved hectares left", second.data["problems"][0])
        self.assertEqual(self.allocate(arda, batch, hectares="5", farmer=self.other_farmer).status_code, 400)
        self.assertEqual(self.allocate(arda, batch, hectares="4", farmer=self.other_farmer).status_code, 201)

    def test_farmer_cannot_get_more_than_their_crop_hectares(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "100"))
        response = self.allocate(arda, batch, hectares="12")
        self.assertEqual(response.status_code, 400)
        self.assertIn("10 ha of Maize", str(response.data))

    def test_programme_catalogue_and_request_cannot_be_mixed(self):
        arda = self.programme("ARDA", [self.maize, self.sorghum], ["SEED"])
        seedco = self.programme("Seed Co", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        seedco_batch = self.approve(self.request(seedco, self.maize, "100"))
        sorghum_batch = self.approve(self.request(arda, self.sorghum, "100"))
        other_programme = self.allocate(arda, seedco_batch)
        self.assertEqual(other_programme.status_code, 400)
        self.assertIn("belongs to Seed Co", str(other_programme.data))
        other_crop = self.allocate(arda, sorghum_batch)
        self.assertEqual(other_crop.status_code, 400)
        self.assertIn("is for Sorghum", str(other_crop.data))

    def test_each_input_type_from_a_different_programme_but_never_twice(self):
        arda = self.programme("ARDA", [self.maize], ["SEED", "FERTILIZER"])
        seedco = self.programme("Seed Co", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "1.50")
        self.line(arda, self.maize, "FERTILIZER", self.compound_d, "50", "0.80")
        self.line(seedco, self.maize, "SEED", self.shumba, "25", "2.00")
        arda_batch = self.approve(self.request(arda, self.maize, "100"))
        seedco_batch = self.approve(self.request(seedco, self.maize, "100"))
        seed = self.allocate(seedco, seedco_batch)
        self.assertEqual(seed.status_code, 201, seed.data)
        # ARDA can still supply the fertilizer: its seed is left out because the farmer has seed.
        plan = self.preview(arda, arda_batch)
        self.assertEqual([entry["category"] for entry in plan.data["categories"]], ["FERTILIZER"])
        self.assertEqual(self.allocate(arda, arda_batch, categories=["SEED"]).status_code, 400)
        self.assertEqual(self.allocate(arda, arda_batch).status_code, 201)
        self.assertEqual(self.allocate(arda, arda_batch).status_code, 400)
        self.assertEqual(InputDebt.objects.filter(farmer=self.farmer).count(), 2)

    def test_prices_are_snapshotted_and_cancelling_restores_hectares(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        mbizi = self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "20"))
        made = self.allocate(arda, batch)
        self.assertEqual(made.status_code, 201, made.data)
        allocation = InputAllocation.objects.get(pk=made.data["id"])
        self.assertEqual((allocation.request_batch_id, allocation.programme_id, allocation.total_input_cost), (batch.id, arda.id, Decimal("500.00")))
        self.client.patch(reverse("crop-input-requirement-detail", kwargs={"pk": mbizi.id}), {"cost_per_unit": "9.00"}, format="json")
        line = allocation.calculation_lines.get()
        self.assertEqual((line.cost_per_unit, line.calculated_cost, line.required_quantity), (Decimal("2.0000"), Decimal("500.00"), Decimal("250.0000")))
        debt = InputDebt.objects.get(input_allocation=allocation)
        self.assertEqual(debt.input_value, Decimal("500.00"))
        # Submitting the same allocation again does not create a second allocation or debt.
        self.assertEqual(self.allocate(arda, batch).status_code, 400)
        self.assertEqual(InputDebt.objects.filter(farmer=self.farmer).count(), 1)
        self.assertEqual(self.batch_row(batch)["remaining_hectares"], Decimal("10.00"))

        self.assertEqual(self.client.delete(reverse("input-allocation-detail", kwargs={"pk": allocation.id})).status_code, 400)
        self.assertEqual(self.client.post(reverse("input-allocation-cancel", kwargs={"pk": allocation.id}), {}, format="json").status_code, 400)
        cancelled = self.client.post(reverse("input-allocation-cancel", kwargs={"pk": allocation.id}), {"reason": "Wrong farm"}, format="json")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(self.batch_row(batch)["remaining_hectares"], Decimal("20.00"))
        debt.refresh_from_db()
        self.assertEqual((debt.status, debt.outstanding_monetary_balance), (InputDebt.STATUS_CANCELLED, Decimal("0.00")))
        # The cancelled allocation stays on record and in the report.
        listed = self.client.get(reverse("input-allocation-list"), {"season": self.season.id}).data["results"]
        self.assertEqual([row["status"] for row in listed], ["CANCELLED"])
        report = self.client.get(reverse("report-preview", kwargs={"code": "arda-requests"}), {"agricultural_year": self.season.id})
        self.assertEqual(report.status_code, 200, report.data)
        self.assertEqual(report.data["rows"][0]["approved_hectares"], "20")

    def test_inactive_programme_gets_no_new_requests_or_allocations(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "100"))
        made = self.allocate(arda, batch, hectares="4")
        self.assertEqual(made.status_code, 201)
        self.client.patch(reverse("programme-detail", kwargs={"pk": arda.id}), {"capacity_status": "INACTIVE"}, format="json")
        refused = self.allocate(arda, batch, hectares="4", farmer=self.other_farmer)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("inactive", str(refused.data))
        self.assertEqual(self.client.post(reverse("arda-request-batch-list"), {
            "programme": arda.id, "season": self.season.id, "crop": "Maize", "requested_hectares": "5", "input_category": "SEED",
        }, format="json").status_code, 400)
        options = self.client.get(reverse("input-allocation-programme-options"), {"crop": self.maize.id, "season": self.season.id}).data
        self.assertEqual(options["options"], [])
        # Earlier records stay readable.
        self.assertEqual(self.client.get(reverse("input-allocation-detail", kwargs={"pk": made.data["id"]})).status_code, 200)
        self.assertEqual(self.client.get(reverse("programme-list"), {"capacity_status": "INACTIVE"}).data["results"][0]["id"], arda.id)

    def test_unauthorised_roles_cannot_change_anything(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.request(arda, self.maize, "100")
        self.client.post(reverse("arda-request-batch-submit", kwargs={"pk": batch.id}))
        viewer = self.api(self.viewer)
        self.assertEqual(viewer.get(reverse("programme-list")).status_code, 200)
        attempts = [
            viewer.post(reverse("programme-list"), {"name": "X", "season": self.season.id, "crops": [self.maize.id], "input_categories": ["SEED"]}, format="json"),
            viewer.patch(reverse("programme-detail", kwargs={"pk": arda.id}), {"capacity_status": "INACTIVE"}, format="json"),
            viewer.post(reverse("crop-input-requirement-list"), {"crop": self.maize.id, "programme": arda.id, "input_category": "SEED", "input_product": self.shumba.id, "rate_per_hectare": "1", "cost_per_unit": "1"}, format="json"),
            viewer.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {}, format="json"),
            self.allocate(arda, batch, client=viewer),
        ]
        self.assertEqual([response.status_code for response in attempts], [403] * len(attempts))
        self.approve_from_submitted(batch)
        made = self.allocate(arda, batch)
        self.assertEqual(viewer.post(reverse("input-allocation-cancel", kwargs={"pk": made.data["id"]}), {"reason": "x"}, format="json").status_code, 403)

    def approve_from_submitted(self, batch):
        response = self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_lines_without_a_programme_are_assigned_only_by_an_administrator(self):
        arda = self.programme("ARDA", [self.maize], ["FERTILIZER"])
        old = CropInputRequirement.objects.create(crop=self.maize, group_name="Seed & Fertilisers", item_name="COMP D", rate_per_hectare=6, unit="kg", cost_per_unit=31)
        copied = self.client.post(reverse("crop-input-requirement-assign", kwargs={"pk": old.id}), {"programme": arda.id, "input_category": "FERTILIZER"}, format="json")
        self.assertEqual(copied.status_code, 201, copied.data)
        self.assertEqual((copied.data["programme"], copied.data["input_category"], copied.data["cost_per_unit"]), (arda.id, "FERTILIZER", "31.0000"))
        old.refresh_from_db()
        self.assertFalse(old.active)

    def test_whole_chain_from_programme_to_farmer_with_matching_figures(self):
        arda = self.programme("ARDA", [self.maize, self.sorghum], ["SEED", "FERTILIZER"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        self.line(arda, self.maize, "FERTILIZER", self.compound_d, "400", pack_size="50", pack_price="32", pack_label="50 kg bag")
        batch = self.approve(self.request(arda, self.maize, "300"), hectares="200")
        options = self.client.get(reverse("input-allocation-programme-options"), {"crop": self.maize.id, "season": self.season.id, "farmer": self.farmer.id}).data
        self.assertEqual(options["crop_hectares"], "10.00")
        offered = options["options"][0]
        self.assertEqual((offered["programme_name"], [item["request_number"] for item in offered["batches"]]), ("ARDA", [batch.request_number]))
        self.assertEqual(self.allocate(arda, batch, hectares="5").status_code, 201)
        self.assertEqual(self.allocate(arda, batch, hectares="10", farmer=self.other_farmer).status_code, 201)
        figures = self.client.get(reverse("programme-figures", kwargs={"pk": arda.id})).data
        row = self.batch_row(batch)
        self.assertEqual(figures["totals"]["approved_hectares"], "200.00")
        self.assertEqual(Decimal(figures["totals"]["allocated_hectares"]), row["allocated_hectares"])
        self.assertEqual(Decimal(figures["totals"]["remaining_hectares"]), row["remaining_hectares"])
        self.assertEqual(figures["totals"]["farmers"], row["total_farmers"])
        maize = next(item for item in figures["crops"] if item["crop_name"] == "Maize")
        self.assertEqual((maize["allocated_hectares"], maize["remaining_hectares"], maize["inputs_configured"]), ("15.00", "185.00", 2))
        self.assertEqual(InputAllocation.objects.filter(request_batch=batch).count(), 2)
        debt = InputDebt.objects.get(farmer=self.farmer)
        self.assertEqual(debt.input_value, Decimal("1530.00"))  # 5 ha: seed 125 kg x 2.00 + fertilizer 2000 kg x 0.64


class ProgrammeCrudTests(ChainMixin, TestCase):
    """Create, read back, edit, read back and delete, as on the Programmes page."""

    @classmethod
    def setUpTestData(cls):
        make_world(cls)

    def setUp(self):
        self.client = self.api()

    def test_create_edit_and_delete_round_trip(self):
        created = self.client.post(reverse("programme-list"), {
            "name": "ARDA", "season": self.season.id, "crops": [self.maize.id, self.sorghum.id],
            "input_categories": ["SEED", "CHEMICALS"], "capacity_status": "ACTIVE",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        pk = created.data["id"]
        read = self.client.get(reverse("programme-detail", kwargs={"pk": pk})).data
        self.assertEqual((sorted(read["crops"]), read["input_categories"], read["capacity_status"]), (sorted([self.maize.id, self.sorghum.id]), ["SEED", "CHEMICALS"], "ACTIVE"))

        edited = self.client.patch(reverse("programme-detail", kwargs={"pk": pk}), {
            "name": "ARDA Inputs", "season": self.season.id, "crops": [self.maize.id, self.wheat.id],
            "input_categories": ["FERTILIZER"], "capacity_status": "INACTIVE",
        }, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        read = self.client.get(reverse("programme-detail", kwargs={"pk": pk})).data
        self.assertEqual(read["name"], "ARDA Inputs")
        self.assertEqual(read["crop_names"], ["Maize", "Wheat"])
        self.assertEqual((read["input_categories"], read["capacity_status"]), (["FERTILIZER"], "INACTIVE"))

        self.assertEqual(self.client.delete(reverse("programme-detail", kwargs={"pk": pk})).status_code, 204)
        self.assertFalse(Programme.objects.filter(pk=pk).exists())

    def test_delete_takes_its_requests_catalogue_allocations_and_debts(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "100"))
        self.assertEqual(self.allocate(arda, batch).status_code, 201)
        kept = self.programme("Seed Co", [self.maize], ["SEED"])
        deleted = self.client.delete(reverse("programme-detail", kwargs={"pk": arda.id}))
        self.assertEqual(deleted.status_code, 204, getattr(deleted, "data", None))
        self.assertFalse(ARDARequestBatch.objects.filter(programme_id=arda.id).exists())
        self.assertFalse(CropInputRequirement.objects.filter(programme_id=arda.id).exists())
        self.assertFalse(InputAllocation.objects.exists())
        self.assertFalse(InputDebt.objects.exists())
        self.assertTrue(Programme.objects.filter(pk=kept.id).exists())

    def test_delete_is_refused_once_grain_was_recovered(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "100"))
        self.allocate(arda, batch)
        InputDebt.objects.update(recovered_tonnes=Decimal("0.50"))
        refused = self.client.delete(reverse("programme-detail", kwargs={"pk": arda.id}))
        self.assertEqual(refused.status_code, 400)
        self.assertIn("recovered", str(refused.data))
        self.assertTrue(Programme.objects.filter(pk=arda.id).exists())


class RequestProductLineTests(ChainMixin, TestCase):
    """Requests name the exact products and varieties, each with its own hectares."""

    @classmethod
    def setUpTestData(cls):
        make_world(cls)

    def setUp(self):
        self.client = self.api()
        self.seedco = self.programme("SEEDCO", [self.maize], ["SEED", "FERTILIZER"])
        self.mbizi_line = self.line(self.seedco, self.maize, "SEED", self.mbizi, "25", "2.00")
        self.shumba_line = self.line(self.seedco, self.maize, "SEED", self.shumba, "20", "3.00")
        self.compound_line = self.line(self.seedco, self.maize, "FERTILIZER", self.compound_d, "400", pack_size="50", pack_price="32", pack_label="50 kg bag")

    def create(self, hectares, lines, programme=None):
        return self.client.post(reverse("arda-request-batch-list"), {
            "programme": (programme or self.seedco).id, "season": self.season.id, "crop": "Maize", "requested_hectares": hectares,
            "lines": [{"requirement": requirement.id, "requested_hectares": value} for requirement, value in lines],
        }, format="json")

    def request_with_varieties(self):
        made = self.create("20", [(self.mbizi_line, "8"), (self.shumba_line, "7"), (self.compound_line, "20")])
        self.assertEqual(made.status_code, 201, made.data)
        return ARDARequestBatch.objects.get(pk=made.data["id"])

    def products(self, batch):
        return {row["product_name"]: row for row in self.batch_row(batch)["products"]}

    def test_request_names_products_from_the_programme_catalogue(self):
        # Seed varieties share the land, so they cannot add up to more than the request.
        too_much_seed = self.create("20", [(self.mbizi_line, "15"), (self.shumba_line, "10")])
        self.assertEqual(too_much_seed.status_code, 400)
        self.assertIn("seed varieties add up to 25", str(too_much_seed.data))
        self.assertFalse(ARDARequestBatch.objects.exists())  # nothing half-saved
        batch = self.request_with_varieties()
        rows = self.products(batch)
        self.assertEqual(set(rows), {"Mbizi", "Shumba", "Compound D"})
        # Unit, rate and price come from the catalogue line, not from the request.
        self.assertEqual((rows["Mbizi"]["input_category"], rows["Mbizi"]["unit"], rows["Mbizi"]["rate_per_hectare"], rows["Mbizi"]["unit_price"]), ("SEED", "kg", "25.0000", "2.0000"))
        self.assertEqual((rows["Mbizi"]["requested_hectares"], rows["Shumba"]["requested_hectares"]), ("8.00", "7.00"))
        too_big = self.create("10", [(self.compound_line, "12")], programme=self.programme("Other", [self.maize], ["FERTILIZER"]))
        self.assertEqual(too_big.status_code, 400)
        other = self.programme("ARDA", [self.maize], ["SEED"])
        foreign = self.create("10", [(self.mbizi_line, "5")], programme=other)
        self.assertEqual(foreign.status_code, 400)
        self.assertIn("ARDA's Maize catalogue", str(foreign.data))
        # A catalogue line named in a request cannot be deleted.
        self.assertEqual(self.client.delete(reverse("crop-input-requirement-detail", kwargs={"pk": self.shumba_line.id})).status_code, 400)

    def test_each_product_is_approved_and_allocated_within_its_own_hectares(self):
        batch = self.request_with_varieties()
        self.client.post(reverse("arda-request-batch-submit", kwargs={"pk": batch.id}))
        mbizi, shumba = batch.lines.get(requirement=self.mbizi_line), batch.lines.get(requirement=self.shumba_line)
        over = self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {"approved_hectares": "20", "lines": {str(mbizi.id): "9"}}, format="json")
        self.assertEqual(over.status_code, 400)
        approved = self.client.post(reverse("arda-request-batch-approve", kwargs={"pk": batch.id}), {"approved_hectares": "20", "lines": {str(mbizi.id): "6"}}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        rows = self.products(batch)
        self.assertEqual((rows["Mbizi"]["approved_hectares"], rows["Shumba"]["approved_hectares"], rows["Compound D"]["approved_hectares"]), ("6.00", "7.00", "20.00"))

        # Two seed varieties on the same land, or no choice when there are two, is refused.
        self.assertEqual(self.allocate(self.seedco, batch, hectares="5").status_code, 400)
        both = self.client.post(reverse("input-allocation-programme-allocate"), {**self.payload(self.seedco, batch, hectares="5"), "request_lines": [mbizi.id, shumba.id]}, format="json")
        self.assertEqual(both.status_code, 400)
        compound = batch.lines.get(requirement=self.compound_line)
        made = self.client.post(reverse("input-allocation-programme-allocate"), {**self.payload(self.seedco, batch, hectares="5"), "request_lines": [mbizi.id, compound.id]}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        allocation = InputAllocation.objects.get(pk=made.data["id"])
        self.assertEqual({line.item_name: line.request_line_id for line in allocation.calculation_lines.all()}, {"Mbizi": mbizi.id, "Compound D": compound.id})
        self.assertEqual(allocation.total_input_cost, Decimal("1530.00"))  # 125 kg x 2.00 + 2000 kg x 0.64
        rows = self.products(batch)
        self.assertEqual((rows["Mbizi"]["remaining_hectares"], rows["Shumba"]["remaining_hectares"], rows["Compound D"]["remaining_hectares"]), ("1.00", "7.00", "15.00"))

        # Mbizi has 1 ha left, so the next farmer cannot get 5 ha of it, but can get Shumba.
        plan = self.client.post(reverse("input-allocation-programme-preview"), {**self.payload(self.seedco, batch, hectares="5", farmer=self.other_farmer), "request_lines": [mbizi.id]}, format="json")
        self.assertFalse(plan.data["can_confirm"])
        self.assertIn("Mbizi has 1 ha of its 6 approved hectares left", plan.data["problems"][0])
        made = self.client.post(reverse("input-allocation-programme-allocate"), {**self.payload(self.seedco, batch, hectares="5", farmer=self.other_farmer), "request_lines": [shumba.id]}, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        options = self.client.get(reverse("input-allocation-programme-options"), {"crop": self.maize.id, "season": self.season.id}).data
        offered = {product["name"]: product["remaining_hectares"] for product in options["options"][0]["batches"][0]["products"]}
        self.assertEqual(offered, {"Mbizi": "1.00", "Shumba": "2.00", "Compound D": "15.00"})

        # Cancelling gives the product's hectares back.
        first = InputAllocation.objects.filter(farmer=self.farmer).get()
        self.client.post(reverse("input-allocation-cancel", kwargs={"pk": first.id}), {"reason": "Wrong farmer"}, format="json")
        self.assertEqual(self.products(batch)["Mbizi"]["remaining_hectares"], "6.00")

    def test_requests_without_products_keep_working(self):
        batch = self.approve(self.request(self.seedco, self.maize, "20"))
        made = self.allocate(self.seedco, batch, hectares="5", categories=["FERTILIZER"])
        self.assertEqual(made.status_code, 201, made.data)


class ConcurrentAllocationTests(ChainMixin, TransactionTestCase):
    """Two officers allocating the last approved hectares at the same moment."""

    def setUp(self):
        make_world(self)
        self.client = self.api()

    def test_two_allocations_at_once_cannot_exceed_approved_hectares(self):
        arda = self.programme("ARDA", [self.maize], ["SEED"])
        self.line(arda, self.maize, "SEED", self.mbizi, "25", "2.00")
        batch = self.approve(self.request(arda, self.maize, "20"), hectares="10")
        barrier = threading.Barrier(2)
        results = []

        def allocate(farmer):
            try:
                barrier.wait()
                programme_allocation.confirm(
                    farmer=farmer, farm=farmer.farms.first(), season=self.season, crop=self.maize, hectares="6",
                    programme=arda, batch=batch, user=self.admin,
                )
                results.append("made")
            except programme_allocation.AllocationError:
                results.append("refused")
            finally:
                connection.close()

        threads = [threading.Thread(target=allocate, args=(farmer,)) for farmer in (self.farmer, self.other_farmer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["made", "refused"])
        self.assertEqual(InputAllocation.objects.filter(request_batch=batch).count(), 1)
