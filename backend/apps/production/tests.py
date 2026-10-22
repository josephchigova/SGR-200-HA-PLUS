from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farm, Farmer
from apps.geography.models import District, Province, Ward
from apps.programmes.models import Programme, Season
from apps.recovery.models import InputDebt

User = get_user_model()


class FarmerProductionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="production@example.com", username="production-user", password="StrongPass123!",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        province = Province.objects.create(name="Harare", code="HA")
        district = District.objects.create(province=province, name="Harare")
        ward = Ward.objects.create(district=district, name="Ward 1")
        self.farmer = Farmer.objects.create(
            first_name="Tendai", surname="Moyo", national_id="63-9876543-X-10", phone_primary="0772222222",
            province=province, district=district, ward=ward,
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Moyo Farm", province=province, district=district, ward=ward,
            total_hectares="20.00", arable_hectares="8.00", verification_status="VERIFIED",
        )
        self.season = Season.objects.create(name="Production 2026/27", start_date="2026-10-01", end_date="2027-09-30")
        self.programme = Programme.objects.create(name="Production Programme", code="PROD-PROG", season=self.season, announced_hectares=100)
        batch = ARDARequestBatch.objects.create(request_number="PROD-BATCH", programme=self.programme, season=self.season)
        ARDAFarmerRequest.objects.create(
            request_batch=batch, farmer=self.farmer, farm=self.farm, requested_hectares=6,
            approved_hectares=6, status=ARDAFarmerRequest.STATUS_APPROVED,
        )

    def test_production_rejects_hectares_above_farm_or_approved_limit(self):
        response = self.client.post(
            reverse("farmer-production-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
                "contracted_hectares": "7.00", "planted_hectares": "6.00", "expected_yield": "8.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_production_accepts_valid_planted_hectares(self):
        response = self.client.post(
            reverse("farmer-production-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
                "contracted_hectares": "6.00", "planted_hectares": "5.00", "expected_yield": "8.00",
                "crop_stage": "VEGETATIVE", "status": "PLANTED",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_viewer_can_read_but_cannot_create_production_records(self):
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])
        list_response = self.client.get(reverse("farmer-production-list"))
        create_response = self.client.post(
            reverse("farmer-production-list"),
            {},
            format="json",
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(create_response.status_code, 403)

    def test_delivery_validates_positive_tonnes_and_calculates_value(self):
        self.user.role = User.ROLE_RECOVERY_OFFICER
        self.user.save(update_fields=["role"])
        debt = InputDebt.objects.create(
            farmer=self.farmer, farm=self.farm, programme=self.programme, crop="Maize",
            input_value="2500.00", total_debt="2500.00", selling_price_per_tonne="250.00",
            required_recovery_tonnes="10.00", outstanding_tonnes="10.00",
        )
        from apps.programmes.models import Crop, CropSellingPrice
        maize = Crop.objects.create(name="Maize", category="SUMMER", active=True)
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="250.00", active=True)
        payload = {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
            "delivery_date": "2027-04-20", "gmb_depot": "GMB Gweru", "ticket_number": "GMB-001",
            "tonnes": "5.00", "price": "250.00", "recovery_tonnes": "2.00",
        }
        response = self.client.post(reverse("delivery-list"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["value"], "1250.00")
        self.assertEqual(response.data["amount_recovered"], "500.00")
        debt.refresh_from_db()
        self.assertEqual(debt.outstanding_tonnes, 8)
        self.assertEqual(debt.recovery_percentage, 20)
        immutable_response = self.client.patch(
            reverse("delivery-detail", kwargs={"pk": response.data["id"]}),
            {"tonnes": "6.00"},
            format="json",
        )
        self.assertEqual(immutable_response.status_code, 405)

        payload["ticket_number"] = "GMB-002"
        payload["tonnes"] = "0.00"
        invalid = self.client.post(reverse("delivery-list"), payload, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_delivery_recovery_without_matching_debt_is_rejected_without_saving(self):
        self.user.role = User.ROLE_RECOVERY_OFFICER
        self.user.save(update_fields=["role"])
        response = self.client.post(
            reverse("delivery-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
                "delivery_date": "2027-04-20", "gmb_depot": "GMB Gweru", "ticket_number": "NO-DEBT",
                "tonnes": "1.00", "price": "200.00", "recovery_tonnes": "0.50",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.farmer.gmb_deliveries.filter(ticket_number="NO-DEBT").exists())
