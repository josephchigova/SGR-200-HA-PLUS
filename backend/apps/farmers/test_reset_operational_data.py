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
