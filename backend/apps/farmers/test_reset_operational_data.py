from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.accounts.models import User
from apps.farmers.models import Farm, Farmer
from apps.finance.models import AccountingPeriod, JournalEntry, JournalLine, LedgerAccount
from apps.geography.models import District, Province
from apps.inputs.models import InputAllocation
from apps.programmes.models import Crop, Programme, Season
from apps.subscriptions.models import FarmerSubscription


class ResetOperationalDataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@example.com",
            username="admin-user",
            password="StrongPass123!",
            role=User.ROLE_SUPER_ADMIN,
        )
        self.province = Province.objects.create(name="Midlands", code="MD-RESET")
        self.district = District.objects.create(province=self.province, name="Gweru", code="GW-RESET")
        self.season = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status="ACTIVE")
        self.crop = Crop.objects.create(name="Maize", category="SUMMER", active=True)
        self.programme = Programme.objects.create(
            name="Maize Programme", code="MAIZE-RESET", season=self.season, crop="Maize",
            announced_hectares="20000.00", total_allocated_hectares="100.00", status="OPEN",
        )
        self.account = LedgerAccount.objects.create(
            code="4000", name="Subscription income", account_type="REVENUE", category="REVENUE", normal_balance="CREDIT",
        )
        self.farmer = Farmer.objects.create(
            first_name="Yusufu", surname="Banda", national_id="63-RESET-1", phone_primary="0774000001",
            province=self.province, district=self.district, membership_number="SGR-RESET-1",
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Victoria", province=self.province, district=self.district,
            total_hectares="8.00", arable_hectares="6.00",
        )
        FarmerSubscription.objects.create(
            farmer=self.farmer, expected_amount="500.00", paid_amount="0.00", outstanding_amount="500.00",
            payment_status="UNPAID", season="2026/2027",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, farm=self.farm, programme=self.programme, crop="Maize", hectares="100.00",
            quantity="1.00", unit="bags", allocation_reference="ALLOC-RESET",
        )
        period = AccountingPeriod.objects.create(name="Oct 2026", start_date="2026-10-01", end_date="2026-10-31")
        entry = JournalEntry.objects.create(reference="JNL-RESET", entry_date="2026-10-20", description="Test", period=period, status="POSTED", season=self.season)
        JournalLine.objects.create(entry=entry, account=self.account, credit="25.00")

    def test_dry_run_counts_records_without_deleting_them(self):
        output = StringIO()
        call_command("reset_operational_data", "--dry-run", stdout=output)
        text = output.getvalue()
        self.assertIn("Farmers: 1", text)
        self.assertIn("User accounts: 1", text)
        self.assertIn("Dry run only", text)
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_deletion_requires_confirm(self):
        with self.assertRaises(CommandError):
            call_command("reset_operational_data")
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())

    def test_confirm_deletes_operational_rows_and_keeps_configuration(self):
        call_command("reset_operational_data", "--confirm")
        self.assertFalse(Farmer.objects.exists())
        self.assertFalse(Farm.objects.exists())
        self.assertFalse(FarmerSubscription.objects.exists())
        self.assertFalse(InputAllocation.objects.exists())
        self.assertFalse(JournalEntry.objects.exists())
        self.assertFalse(JournalLine.objects.exists())
        self.assertTrue(User.objects.filter(email="admin@example.com").exists())
        self.assertTrue(Province.objects.filter(pk=self.province.pk).exists())
        self.assertTrue(District.objects.filter(pk=self.district.pk).exists())
        self.assertTrue(Season.objects.filter(pk=self.season.pk).exists())
        self.assertTrue(Crop.objects.filter(pk=self.crop.pk).exists())
        self.programme.refresh_from_db()
        self.assertEqual(self.programme.announced_hectares, Decimal("20000.00"))
        self.assertEqual(self.programme.total_allocated_hectares, Decimal("0.00"))
        self.assertTrue(LedgerAccount.objects.filter(pk=self.account.pk).exists())
        self.assertTrue(AccountingPeriod.objects.exists())

    def test_a_failure_during_deletion_rolls_back(self):
        from unittest.mock import patch

        with patch("apps.farmers.operational_reset.Farmer.objects") as farmers:
            farmers.count.return_value = 1
            farmers.all.return_value.delete.side_effect = RuntimeError("stop")
            with self.assertRaises(RuntimeError):
                call_command("reset_operational_data", "--confirm")
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())
        self.assertTrue(JournalEntry.objects.exists())

    def test_confirm_clears_request_batches_with_stock_and_every_farmer_record(self):
        """Batch inputs and their stock history point at batches and allocations with PROTECT."""
        from apps.accounts.models import Notification
        from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch, BatchStockMovement, RequestBatchInput
        from apps.farmers.models import FarmerChangeRequest, FarmerReviewEvent, RegistrationCropAllocation
        from apps.inputs.models import Input, InputAllocationLine
        from apps.programmes.models import CropInputRequirement, ProgrammeCrop
        from apps.recovery.models import InputDebt

        ProgrammeCrop.objects.create(programme=self.programme, crop=self.crop)
        seed = Input.objects.create(name="Reset seed", category="SEED", unit="kg")
        requirement = CropInputRequirement.objects.create(
            crop=self.crop, programme=self.programme, input_category="SEED", input_product=seed,
            group_name="Seed", item_name="Reset seed", rate_per_hectare="25", unit="kg", cost_per_unit="2",
        )
        batch = ARDARequestBatch.objects.create(
            request_number="SGR-RESET", programme=self.programme, season=self.season, crop="Maize",
            requested_hectares="100.00", approved_hectares="80.00", status=ARDARequestBatch.STATUS_APPROVED,
        )
        ARDAFarmerRequest.objects.create(request_batch=batch, farmer=self.farmer, farm=self.farm, requested_hectares="5.00")
        allocation = InputAllocation.objects.create(
            farmer=self.farmer, farm=self.farm, programme=self.programme, crop="Maize", crop_reference=self.crop,
            hectares="5.00", request_batch=batch, sourced_by_category=True,
        )
        line = InputAllocationLine.objects.create(
            allocation=allocation, source_requirement=requirement, input_category="SEED", programme=self.programme,
            input_product=seed, group_name="Seed", item_name="Reset seed", required_quantity="125",
        )
        InputDebt.objects.create(farmer=self.farmer, programme=self.programme, input_allocation=allocation, crop="Maize", total_debt="250.00")
        batch_input = RequestBatchInput.objects.create(batch=batch, input_product=seed, input_category="SEED", requested_quantity="1000", allocated_quantity="125")
        BatchStockMovement.objects.create(batch_input=batch_input, kind=BatchStockMovement.KIND_OPENING, quantity="1000", available_after="1000")
        BatchStockMovement.objects.create(
            batch_input=batch_input, kind=BatchStockMovement.KIND_ALLOCATION, quantity="-125", available_after="875",
            allocation=allocation, allocation_line=line,
        )
        RegistrationCropAllocation.objects.create(farmer=self.farmer, crop=self.crop, season=self.season, hectares="5.00")
        FarmerChangeRequest.objects.create(farmer=self.farmer, changes={"phone_primary": "0770000000"})
        FarmerReviewEvent.objects.create(farmer=self.farmer, action=FarmerReviewEvent.SUBMITTED)
        Notification.objects.create(recipient=self.user, kind=Notification.KIND_SUBSCRIPTION_OVERDUE, dedupe_key="reset", title="Overdue", farmer=self.farmer)

        output = StringIO()
        call_command("reset_operational_data", "--confirm", stdout=output)

        for model in (BatchStockMovement, RequestBatchInput, ARDARequestBatch, ARDAFarmerRequest, InputAllocation, InputAllocationLine,
                      InputDebt, RegistrationCropAllocation, FarmerChangeRequest, FarmerReviewEvent, Notification, Farmer):
            self.assertFalse(model.objects.exists(), model.__name__)
        # Programme configuration stays: the programme, its crops, its catalogue and the products.
        self.assertTrue(ProgrammeCrop.objects.filter(programme=self.programme, crop=self.crop).exists())
        self.assertTrue(CropInputRequirement.objects.filter(pk=requirement.pk).exists())
        self.assertTrue(Input.objects.filter(pk=seed.pk).exists())
        text = output.getvalue()
        self.assertIn("removed Request batch stock movements: 2", text)
        self.assertIn("removed Request batch inputs: 1", text)
        self.assertIn("removed ARDA request batches: 1", text)

    def test_confirm_deletes_input_supply_rows_that_protect_farms(self):
        from apps.inputs.models import Input, InputSupplyFarmer, InputSupplyLine, InputSupplyRequest
        from apps.programmes.models import CropInputRequirement

        seed = Input.objects.create(name="Supply seed", category="SEED", unit="kg")
        requirement = CropInputRequirement.objects.create(
            crop=self.crop, programme=self.programme, input_category="SEED", input_product=seed,
            group_name="Seed", item_name="Supply seed", rate_per_hectare="25", unit="kg", cost_per_unit="2",
        )
        supply = InputSupplyRequest.objects.create(
            reference="LF-RESET", lead_farmer=self.user, programme=self.programme, season=self.season, crop=self.crop,
        )
        entry = InputSupplyFarmer.objects.create(request=supply, farmer=self.farmer, farm=self.farm, hectares="5.00")
        InputSupplyLine.objects.create(
            farmer_entry=entry, requirement=requirement, hectares="5.00", rate_per_hectare="25",
            quantity="125", unit="kg", estimated_cost="250.00",
        )

        call_command("reset_operational_data", "--confirm")

        self.assertFalse(InputSupplyRequest.objects.exists())
        self.assertFalse(InputSupplyFarmer.objects.exists())
        self.assertFalse(InputSupplyLine.objects.exists())
        self.assertFalse(Farm.objects.exists())
        self.assertTrue(CropInputRequirement.objects.filter(pk=requirement.pk).exists())
