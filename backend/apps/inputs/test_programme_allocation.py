"""Programme catalogue, request batch stock and per-category input allocation."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.arda_requests import stock
from apps.arda_requests.models import ARDARequestBatch, BatchStockMovement, RequestBatchInput
from apps.farmers.models import Farm, Farmer, RegistrationCropAllocation
from apps.geography.models import District, Province
from apps.inputs.models import Input, InputAllocation
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Programme, Season
from apps.recovery.models import InputDebt
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()


class ProgrammeAllocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(email="officer@example.com", username="officer", password="Str0ng!Passw0rd", role=User.ROLE_SUPER_ADMIN)
        province = Province.objects.create(name="Mashonaland East", code="ME")
        district = District.objects.create(province=province, name="Marondera")
        cls.season = Season.objects.create(name="2026/2027", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30), status=Season.STATUS_ACTIVE)
        cls.maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
        CropSellingPrice.objects.create(crop=cls.maize, season=cls.season, price_per_tonne=Decimal("300.00"))
        cls.farmer = Farmer.objects.create(
            first_name="Tendai", surname="Moyo", national_id="63-1234567A12", province=province, district=district,
            verification_status=Farmer.STATUS_VERIFIED, membership_status=Farmer.MEMBERSHIP_ACTIVE,
        )
        cls.farm = Farm.objects.create(farmer=cls.farmer, farm_name="Moyo Farm", province=province, district=district, total_hectares=40, arable_hectares=30)
        FarmerSubscription.objects.create(farmer=cls.farmer, season=cls.season.name, expected_amount=500, paid_amount=500, outstanding_amount=0, payment_status="PAID")
        RegistrationCropAllocation.objects.create(farmer=cls.farmer, crop=cls.maize, season=cls.season, hectares=10)

        cls.seedco = Programme.objects.create(name="Seed Co Programme", code="SEEDCO", season=cls.season, input_categories=["SEED"])
        cls.arda = Programme.objects.create(name="ARDA Programme", code="ARDA", season=cls.season, input_categories=["SEED", "FERTILIZER", "CHEMICALS"])
        cls.govt = Programme.objects.create(name="Government Input Programme", code="GIP", season=cls.season, input_categories=["CHEMICALS"])
        cls.seed = Input.objects.create(name="SC 727 maize seed", category="SEED", unit="kg")
        cls.compound_d = Input.objects.create(name="Compound D", category="FERTILIZER", unit="kg")
        cls.herbicide = Input.objects.create(name="Atrazine", category="CHEMICALS", unit="litres")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def requirement(self, programme, category, product, rate, price):
        response = self.client.post("/api/crop-input-requirements/", {
            "crop": self.maize.id, "programme": programme.id, "input_category": category, "input_product": product.id,
            "rate_per_hectare": rate, "cost_per_unit": price,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return CropInputRequirement.objects.get(pk=response.data["id"])

    def batch(self, programme, number, status=ARDARequestBatch.STATUS_APPROVED, **quantities):
        batch = ARDARequestBatch.objects.create(request_number=number, programme=programme, season=self.season, status=status, requested_hectares=100)
        products = {"seed": (self.seed, "SEED"), "fertilizer": (self.compound_d, "FERTILIZER"), "chemicals": (self.herbicide, "CHEMICALS")}
        for key, quantity in quantities.items():
            product, category = products[key]
            response = self.client.post("/api/request-batch-inputs/", {
                "batch": batch.id, "input_product": product.id, "input_category": category, "requested_quantity": quantity,
            }, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        return batch

    def configure(self):
        self.requirement(self.seedco, "SEED", self.seed, "25", "2.00")
        self.requirement(self.arda, "SEED", self.seed, "25", "1.50")
        self.requirement(self.arda, "FERTILIZER", self.compound_d, "50", "0.80")
        self.requirement(self.govt, "CHEMICALS", self.herbicide, "2", "12.00")
        self.seedco_batch = self.batch(self.seedco, "SC-1", seed="1000")
        self.arda_batch = self.batch(self.arda, "AR-1", seed="2000", fertilizer="800")
        self.govt_batch = self.batch(self.govt, "GV-1", chemicals="100")

    def payload(self, **selections):
        return {
            "farmer": self.farmer.id, "farm": self.farm.id, "season": self.season.id, "crop": self.maize.id, "hectares": "10",
            "selections": {category: {"programme": programme.id} for category, programme in selections.items()},
        }

    def line(self, batch, product):
        return RequestBatchInput.objects.get(batch=batch, input_product=product)

    # Catalogue -------------------------------------------------------------------------

    def test_same_crop_has_independent_requirements_and_prices_per_programme(self):
        self.configure()
        seedco = CropInputRequirement.objects.get(programme=self.seedco, input_product=self.seed)
        arda = CropInputRequirement.objects.get(programme=self.arda, input_product=self.seed)
        self.assertEqual((seedco.cost_per_unit, arda.cost_per_unit), (Decimal("2.0000"), Decimal("1.5000")))
        self.assertEqual((seedco.group_name, seedco.item_name, seedco.unit), ("Seed", "SC 727 maize seed", "kg"))
        # A price change in one programme leaves the other alone.
        self.client.patch(f"/api/crop-input-requirements/{arda.id}/", {"cost_per_unit": "1.75"}, format="json")
        seedco.refresh_from_db()
        self.assertEqual(seedco.cost_per_unit, Decimal("2.0000"))
        listed = self.client.get("/api/crop-input-requirements/", {"crop": self.maize.id, "programme": self.seedco.id}).data
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual([row["input_product_name"] for row in rows], ["SC 727 maize seed"])

    def test_catalogue_refuses_wrong_category_and_duplicates(self):
        wrong = self.client.post("/api/crop-input-requirements/", {
            "crop": self.maize.id, "programme": self.arda.id, "input_category": "SEED", "input_product": self.compound_d.id,
            "rate_per_hectare": "10", "cost_per_unit": "1",
        }, format="json")
        self.assertEqual(wrong.status_code, 400)
        self.requirement(self.arda, "SEED", self.seed, "25", "1.50")
        again = self.client.post("/api/crop-input-requirements/", {
            "crop": self.maize.id, "programme": self.arda.id, "input_category": "SEED", "input_product": self.seed.id,
            "rate_per_hectare": "20", "cost_per_unit": "1",
        }, format="json")
        self.assertEqual(again.status_code, 400)

    # Allocation ------------------------------------------------------------------------

    def test_each_category_from_a_different_programme_and_batch(self):
        self.configure()
        preview = self.client.post("/api/input-allocations/programme-preview/", self.payload(SEED=self.seedco, FERTILIZER=self.arda, CHEMICALS=self.govt), format="json")
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertTrue(preview.data["can_confirm"])
        by_category = {entry["category"]: entry for entry in preview.data["categories"]}
        self.assertEqual(by_category["SEED"]["programme_name"], "Seed Co Programme")
        self.assertEqual(by_category["SEED"]["lines"][0]["required_quantity"], "250")  # 25 kg x 10 ha
        self.assertEqual(by_category["SEED"]["lines"][0]["cost"], "500.00")  # 250 kg x 2.00, Seed Co's price
        self.assertEqual(by_category["FERTILIZER"]["lines"][0]["available_after"], "300")
        self.assertEqual(preview.data["total_cost"], "1140.00")  # 500 + 400 + 240

        made = self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.seedco, FERTILIZER=self.arda, CHEMICALS=self.govt), format="json")
        self.assertEqual(made.status_code, 201, made.data)
        allocation = InputAllocation.objects.get(pk=made.data["id"])
        self.assertTrue(allocation.sourced_by_category)
        self.assertEqual(allocation.total_input_cost, Decimal("1140.00"))
        self.assertEqual({line.input_category: line.programme_id for line in allocation.calculation_lines.all()},
                         {"SEED": self.seedco.id, "FERTILIZER": self.arda.id, "CHEMICALS": self.govt.id})
        # Stock leaves exactly the chosen batches. The ARDA batch's seed, the same product, is untouched.
        self.assertEqual(self.line(self.seedco_batch, self.seed).allocated_quantity, Decimal("250"))
        self.assertEqual(self.line(self.arda_batch, self.seed).allocated_quantity, Decimal("0"))
        self.assertEqual(self.line(self.arda_batch, self.compound_d).available_quantity, Decimal("300"))
        self.assertEqual(self.line(self.govt_batch, self.herbicide).available_quantity, Decimal("80"))
        self.assertEqual(BatchStockMovement.objects.filter(kind=BatchStockMovement.KIND_ALLOCATION, allocation=allocation).count(), 3)
        debt = InputDebt.objects.get(input_allocation=allocation)
        self.assertEqual(debt.input_value, Decimal("1140.00"))
        self.assertEqual(debt.required_recovery_tonnes, Decimal("3.80"))

    def test_all_three_from_one_programme(self):
        self.requirement(self.arda, "SEED", self.seed, "25", "1.50")
        self.requirement(self.arda, "FERTILIZER", self.compound_d, "50", "0.80")
        self.requirement(self.arda, "CHEMICALS", self.herbicide, "2", "10.00")
        batch = self.batch(self.arda, "AR-2", seed="500", fertilizer="1000", chemicals="50")
        made = self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.arda, FERTILIZER=self.arda, CHEMICALS=self.arda), format="json")
        self.assertEqual(made.status_code, 201, made.data)
        self.assertEqual(Decimal(made.data["total_input_cost"]), Decimal("975.00"))  # 375 + 400 + 200
        self.assertEqual(self.line(batch, self.herbicide).available_quantity, Decimal("30"))

    def test_price_change_does_not_alter_a_made_allocation(self):
        self.configure()
        made = self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.seedco), format="json")
        self.assertEqual(made.status_code, 201, made.data)
        requirement = CropInputRequirement.objects.get(programme=self.seedco, input_product=self.seed)
        self.client.patch(f"/api/crop-input-requirements/{requirement.id}/", {"cost_per_unit": "9.00"}, format="json")
        allocation = InputAllocation.objects.get(pk=made.data["id"])
        line = allocation.calculation_lines.get()
        self.assertEqual((line.cost_per_unit, line.calculated_cost, allocation.total_input_cost), (Decimal("2.0000"), Decimal("500.00"), Decimal("500.00")))

    def test_cannot_allocate_more_than_the_batch_holds(self):
        self.requirement(self.arda, "FERTILIZER", self.compound_d, "50", "0.80")
        batch = self.batch(self.arda, "AR-3", fertilizer="300")
        preview = self.client.post("/api/input-allocations/programme-preview/", self.payload(FERTILIZER=self.arda), format="json")
        self.assertFalse(preview.data["can_confirm"])
        self.assertIn("Not enough Compound D", preview.data["problems"][0])
        refused = self.client.post("/api/input-allocations/programme-allocate/", self.payload(FERTILIZER=self.arda), format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.line(batch, self.compound_d).allocated_quantity, Decimal("0"))
        self.assertFalse(InputAllocation.objects.exists())

    def test_draft_batches_are_not_allocatable(self):
        self.requirement(self.arda, "SEED", self.seed, "25", "1.50")
        self.batch(self.arda, "AR-4", status=ARDARequestBatch.STATUS_PENDING, seed="1000")
        preview = self.client.post("/api/input-allocations/programme-preview/", self.payload(SEED=self.arda), format="json")
        self.assertFalse(preview.data["can_confirm"])
        self.assertIn("not in any submitted or approved request batch", preview.data["problems"][0])

    def test_hectares_are_limited_to_the_crop_allocation_and_duplicates_refused(self):
        self.configure()
        too_many = self.client.post("/api/input-allocations/programme-preview/", {**self.payload(SEED=self.seedco), "hectares": "12"}, format="json")
        self.assertEqual(too_many.status_code, 400)
        self.assertIn("10 ha of Maize", str(too_many.data))
        self.assertEqual(self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.seedco), format="json").status_code, 201)
        again = self.client.post("/api/input-allocations/programme-allocate/", self.payload(FERTILIZER=self.arda), format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(InputAllocation.objects.count(), 1)
        self.assertEqual(InputDebt.objects.count(), 1)

    def test_cancel_returns_stock_with_a_record_and_cancels_the_debt(self):
        self.configure()
        made = self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.seedco, CHEMICALS=self.govt), format="json")
        allocation_id = made.data["id"]
        self.assertEqual(self.client.delete(f"/api/input-allocations/{allocation_id}/").status_code, 400)
        self.assertEqual(self.client.post(f"/api/input-allocations/{allocation_id}/cancel/", {}, format="json").status_code, 400)
        cancelled = self.client.post(f"/api/input-allocations/{allocation_id}/cancel/", {"reason": "Farmer withdrew"}, format="json")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], "CANCELLED")
        self.assertEqual(self.line(self.seedco_batch, self.seed).allocated_quantity, Decimal("0"))
        self.assertEqual(self.line(self.govt_batch, self.herbicide).available_quantity, Decimal("100"))
        reversals = BatchStockMovement.objects.filter(kind=BatchStockMovement.KIND_REVERSAL, allocation_id=allocation_id)
        self.assertEqual(reversals.count(), 2)
        self.assertEqual(reversals.first().reason, "Farmer withdrew")
        self.assertTrue(InputAllocation.objects.filter(pk=allocation_id).exists())
        debt = InputDebt.objects.get(input_allocation_id=allocation_id)
        self.assertEqual((debt.status, debt.outstanding_monetary_balance), (InputDebt.STATUS_CANCELLED, Decimal("0.00")))
        # After cancelling, the farmer can be allocated again from the restored stock.
        self.assertEqual(self.client.post("/api/input-allocations/programme-allocate/", self.payload(SEED=self.seedco), format="json").status_code, 201)

    # Batch stock -----------------------------------------------------------------------

    def test_batch_quantities_and_ledger(self):
        self.configure()
        line = self.line(self.arda_batch, self.compound_d)
        self.client.post("/api/input-allocations/programme-allocate/", self.payload(FERTILIZER=self.arda), format="json")
        below = self.client.patch(f"/api/request-batch-inputs/{line.id}/", {"requested_quantity": "400"}, format="json")
        self.assertEqual(below.status_code, 400)
        raised = self.client.patch(f"/api/request-batch-inputs/{line.id}/", {"requested_quantity": "1000", "reason": "Second delivery"}, format="json")
        self.assertEqual(raised.status_code, 200, raised.data)
        self.assertEqual(Decimal(raised.data["available_quantity"]), Decimal("500"))
        self.assertEqual(self.client.delete(f"/api/request-batch-inputs/{line.id}/").status_code, 400)
        history = self.client.get(f"/api/request-batch-inputs/{line.id}/movements/").data
        self.assertEqual([row["kind"] for row in history], ["ADJUSTMENT", "ALLOCATION", "OPENING"])
        self.assertEqual(history[1]["farmer_name"], self.farmer.full_name)

    def test_stock_guard_refuses_overdraw_directly(self):
        self.configure()
        line = stock.lock([self.line(self.govt_batch, self.herbicide).pk])
        with self.assertRaises(stock.StockError):
            stock.allocate(next(iter(line.values())), "101", allocation=None, allocation_line=None)

    def test_options_list_programmes_per_category(self):
        self.configure()
        options = self.client.get("/api/input-allocations/programme-options/", {"crop": self.maize.id, "season": self.season.id, "farmer": self.farmer.id}).data
        self.assertEqual(options["crop_hectares"], "10.00")
        self.assertEqual(sorted(entry["programme_name"] for entry in options["categories"]["SEED"]), ["ARDA Programme", "Seed Co Programme"])
        self.assertEqual([entry["programme_name"] for entry in options["categories"]["CHEMICALS"]], ["Government Input Programme"])
        seedco = next(entry for entry in options["categories"]["SEED"] if entry["programme_name"] == "Seed Co Programme")
        self.assertEqual(seedco["products"][0]["unit_price"], "2.0000")
        self.assertEqual(seedco["batches"][0]["request_number"], "SC-1")
