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
        from apps.programmes.models import Crop, CropSellingPrice
        maize = Crop.objects.create(name="Maize", category="SUMMER", active=True)
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="200.00", active=True)
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

    def test_delivery_uses_catalogue_price_and_crop_specific_debt(self):
        from decimal import Decimal

        from apps.farmers.models import Farm
        from apps.programmes.models import Crop, CropSellingPrice

        self.user.role = User.ROLE_RECOVERY_OFFICER
        self.user.save(update_fields=["role"])
        maize = Crop.objects.create(name="Maize", category="SUMMER", active=True)
        wheat = Crop.objects.create(name="Wheat", category="WINTER", active=True)
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="400.00", active=True)
        other_farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Other Farm", province=self.farm.province, district=self.farm.district,
            ward=self.farm.ward, total_hectares="4.00", arable_hectares="4.00", verification_status="VERIFIED",
        )
        maize_debt = InputDebt.objects.create(
            farmer=self.farmer, farm=self.farm, programme=self.programme, crop="Maize",
            input_value="2000.00", total_debt="2000.00", outstanding_monetary_balance="2000.00",
            selling_price_per_tonne="400.00", required_recovery_tonnes="5.00", outstanding_tonnes="5.00",
        )
        wheat_debt = InputDebt.objects.create(
            farmer=self.farmer, farm=self.farm, programme=self.programme, crop="Wheat",
            input_value="800.00", total_debt="800.00", outstanding_monetary_balance="800.00",
            selling_price_per_tonne="400.00", required_recovery_tonnes="2.00", outstanding_tonnes="2.00",
        )
        other_farmer = Farmer.objects.create(
            first_name="Rudo", surname="Dube", national_id="63-1111111-A-10", phone_primary="0773333333",
            province=self.farmer.province, district=self.farmer.district, ward=self.farmer.ward,
        )

        maize_preview = self.client.get(reverse("delivery-recovery-preview"), {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
        })
        self.assertEqual(maize_preview.status_code, 200, maize_preview.data)
        self.assertEqual(maize_preview.data["price_per_tonne"], "400.00")
        self.assertEqual(maize_preview.data["outstanding_input_debt"], "2000.00")
        self.assertEqual(maize_preview.data["expected_recovery_tonnes"], "5.000")

        other_farm_preview = self.client.get(reverse("delivery-recovery-preview"), {
            "farmer": self.farmer.pk, "farm": other_farm.pk, "season": self.season.pk, "crop": "Maize",
        })
        self.assertEqual(other_farm_preview.data["outstanding_input_debt"], "0.00")
        self.assertEqual(other_farm_preview.data["expected_recovery_tonnes"], "0.000")

        other_farmer_preview = self.client.get(reverse("delivery-recovery-preview"), {
            "farmer": other_farmer.pk, "season": self.season.pk, "crop": "Maize",
        })
        self.assertEqual(other_farmer_preview.data["outstanding_input_debt"], "0.00")
        self.assertEqual(other_farmer_preview.data["expected_recovery_tonnes"], "0.000")

        missing_price = self.client.get(reverse("delivery-recovery-preview"), {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Wheat",
        })
        self.assertEqual(missing_price.status_code, 400)
        self.assertIn("no configured price per tonne", str(missing_price.data).lower())
        self.assertIn("crop catalogue", str(missing_price.data).lower())

        rejected = self.client.post(reverse("delivery-list"), {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Wheat",
            "delivery_date": "2027-06-01", "gmb_depot": "GMB Gweru", "ticket_number": "WHEAT-1",
            "tonnes": "1.00", "price": "0.00", "recovery_tonnes": "1.00",
        }, format="json")
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertFalse(self.farmer.gmb_deliveries.filter(ticket_number="WHEAT-1").exists())
        wheat_debt.refresh_from_db()
        self.assertEqual(wheat_debt.outstanding_monetary_balance, Decimal("800.00"))

        saved = self.client.post(reverse("delivery-list"), {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
            "delivery_date": "2027-04-20", "gmb_depot": "GMB Gweru", "delivery_reference": "REF-20",
            "ticket_number": "GMB-20", "tonnes": "2.00", "price": "999.00", "recovery_tonnes": "1.00",
        }, format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["price"], "400.00")
        self.assertEqual(saved.data["tonnes"], "2.00")
        self.assertEqual(saved.data["recovery_tonnes"], "1.00")
        self.assertEqual(saved.data["ticket_number"], "GMB-20")
        self.assertEqual(saved.data["delivery_reference"], "REF-20")
        self.assertNotEqual(saved.data["recovery_tonnes"], "5.000")
        maize_debt.refresh_from_db()
        wheat_debt.refresh_from_db()
        self.assertEqual(maize_debt.outstanding_tonnes, Decimal("4.00"))
        self.assertEqual(maize_debt.outstanding_monetary_balance, Decimal("1600.00"))
        self.assertEqual(wheat_debt.outstanding_monetary_balance, Decimal("800.00"))
        self.assertEqual(wheat_debt.outstanding_tonnes, Decimal("2.00"))

        duplicate = self.client.post(reverse("delivery-list"), {
            "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk, "crop": "Maize",
            "delivery_date": "2027-04-21", "gmb_depot": "GMB Gweru", "ticket_number": "GMB-20",
            "tonnes": "1.00", "recovery_tonnes": "1.00",
        }, format="json")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)
        maize_debt.refresh_from_db()
        self.assertEqual(maize_debt.outstanding_tonnes, Decimal("4.00"))
        self.assertEqual(self.farmer.gmb_deliveries.filter(ticket_number="GMB-20").count(), 1)
