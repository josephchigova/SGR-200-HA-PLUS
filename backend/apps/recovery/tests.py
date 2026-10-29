from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inputs.models import InputAllocation
from apps.farmers.models import Farmer
from apps.geography.models import District, Province, Ward
from apps.production.models import GMBDelivery
from apps.programmes.models import Crop, CropSellingPrice, Programme, Season

from .models import InputDebt
from .services import RecoveryCalculationService

User = get_user_model()


class RecoveryRecordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="recovery@example.com",
            username="recovery-user",
            password="StrongPass123!",
            first_name="Tatenda",
            last_name="Muzenda",
            role=User.ROLE_RECOVERY_OFFICER,
        )
        self.province = Province.objects.create(name="Manicaland", code="MN")
        self.district = District.objects.create(province=self.province, name="Mutare")
        self.ward = Ward.objects.create(district=self.district, name="Ward 7")
        self.farmer = Farmer.objects.create(
            first_name="Anesu",
            surname="Ncube",
            national_id="63-1122334-X-89",
            phone_primary="0774000000",
            email="anesu@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.farm = self.farmer.farms.create(
            farm_name="Anesu Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="120.00",
            arable_hectares="100.00",
            verification_status="VERIFIED",
        )
        self.season = Season.objects.create(name="Recovery 2026/27", start_date="2026-10-01", end_date="2027-09-30")
        self.programme = Programme.objects.create(name="Recovery Test", code="REC-TEST", season=self.season, announced_hectares=100)
        self.crop = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        CropSellingPrice.objects.create(crop=self.crop, season=self.season, price_per_tonne="300.00", active=True)
        self.allocation = InputAllocation.objects.create(
            farmer=self.farmer,
            farm=self.farm,
            programme=self.programme,
            crop_reference=self.crop,
            crop=self.crop.name,
            hectares="200.00",
            total_input_cost="37200.00",
            calculated_input_cost_per_hectare="186.00",
        )
        self.debt = RecoveryCalculationService.create_or_update_from_allocation(
            allocation=self.allocation,
            selling_price_per_tonne="300.00",
        )

    def test_recovery_record_can_be_created(self):
        url = reverse("recovery-record-list")
        response = self.client.post(
            url,
            {
                "farmer": self.farmer.id,
                "debt_amount": 420.00,
                "currency": "USD",
                "status": "PENDING",
                "notes": "Outstanding input repayment",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PENDING")

    def test_recovery_calculation_service_tracks_outstanding_and_percentage(self):
        summary = RecoveryCalculationService.calculate_summary("50", "15")

        self.assertEqual(summary["outstanding_tonnes"], 35)
        self.assertEqual(summary["recovery_percentage"], 30)
        self.assertEqual(summary["status"], InputDebt.STATUS_PARTIALLY_RECOVERED)

    def test_recovery_calculation_boundaries(self):
        self.assertEqual(RecoveryCalculationService.calculate_summary("50", "0")["recovery_percentage"], 0)
        self.assertEqual(RecoveryCalculationService.calculate_summary("50", "50")["outstanding_tonnes"], 0)
        with self.assertRaises(ValueError):
            RecoveryCalculationService.calculate_summary("50", "-1")
        capped = RecoveryCalculationService.calculate_summary("50", "51")
        self.assertEqual(capped["recovery_percentage"], 100)

    def test_input_debt_api_rejects_manual_creation_and_supports_patch(self):
        create_response = self.client.post(
            reverse("input-debt-list"),
            {
                "farmer": self.farmer.pk,
                "programme": self.programme.pk,
                "required_recovery_tonnes": "10.00",
                "recovered_tonnes": "2.50",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 405)

        response = self.client.patch(
            reverse("input-debt-detail", kwargs={"pk": self.debt.pk}),
            {"recovered_tonnes": "2.50"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["outstanding_tonnes"], "121.50")
        self.assertEqual(response.data["recovery_percentage"], "2.02")

        invalid = self.client.patch(
            reverse("input-debt-detail", kwargs={"pk": self.debt.pk}),
            {"recovered_tonnes": "-1.00"},
            format="json",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_apply_delivery_updates_outstanding_tonnes_balance_and_status(self):
        delivery = GMBDelivery.objects.create(
            farmer=self.farmer,
            farm=self.farm,
            season=self.season,
            crop=self.crop.name,
            delivery_date="2027-02-01",
            gmb_depot="GMB Mutare",
            ticket_number="REC-001",
            tonnes="40.00",
            price="300.00",
            value="12000.00",
            recovery_tonnes="40.00",
            amount_recovered="12000.00",
            farmer_balance="0.00",
        )
        RecoveryCalculationService.apply_delivery(delivery)
        self.debt.refresh_from_db()
        self.assertEqual(self.debt.recovered_tonnes, 40)
        self.assertEqual(self.debt.outstanding_tonnes, 84)
        self.assertEqual(self.debt.amount_recovered, 12000)
        self.assertEqual(self.debt.outstanding_monetary_balance, 25200)
        self.assertEqual(self.debt.status, InputDebt.STATUS_PARTIALLY_RECOVERED)
