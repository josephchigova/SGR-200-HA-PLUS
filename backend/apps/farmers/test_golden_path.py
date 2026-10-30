from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.geography.models import District, Province, Ward
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Season

User = get_user_model()


class GoldenPathSystemTest(TestCase):
    def setUp(self):
        self.verification_user = self.make_user("verify", User.ROLE_VERIFICATION_OFFICER)
        self.finance_user = self.make_user("finance", User.ROLE_FINANCE_OFFICER)
        self.programme_user = self.make_user("programme", User.ROLE_PROGRAMME_OFFICER)
        self.recovery_user = self.make_user("recovery", User.ROLE_RECOVERY_OFFICER)
        self.dashboard_user = self.make_user("executive", User.ROLE_SGR_EXECUTIVE)
        self.province = Province.objects.create(name="Golden Province", code="GOLD")
        self.district = District.objects.create(province=self.province, name="Golden District")
        self.ward = Ward.objects.create(district=self.district, name="Golden Ward")
        self.client = APIClient()

    @staticmethod
    def make_user(prefix, role):
        return User.objects.create_user(
            email=f"{prefix}@example.test",
            username=f"{prefix}-user",
            password="StrongPass123!",
            role=role,
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_golden_path_from_farmer_registration_to_dashboard_recovery(self):
        self.authenticate_as(self.verification_user)
        farmer_response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Golden",
                "surname": "Farmer",
                "national_id": "63-1111111-X-01",
                "phone_primary": "0771111111",
                "province": self.province.pk,
                "district": self.district.pk,
                "ward": self.ward.pk,
                "farm_name": "Golden Demonstration Farm",
                "total_hectares": "12.50",
            },
            format="json",
        )
        self.assertEqual(farmer_response.status_code, 201, farmer_response.data)
        farmer_id = farmer_response.data["id"]
        farm_id = farmer_response.data["farms"][0]

        verification_response = self.client.post(
            reverse("farmer-verify", kwargs={"pk": farmer_id}),
            {"verification_status": "VERIFIED"},
            format="json",
        )
        self.assertEqual(verification_response.status_code, 200, verification_response.data)
        self.assertEqual(verification_response.data["verification_status"], "VERIFIED")

        self.authenticate_as(self.programme_user)
        season_response = self.client.post(
            reverse("season-list"),
            {"name": "2026/2027", "start_date": "2026-10-01", "end_date": "2027-09-30", "status": "ACTIVE"},
            format="json",
        )
        self.assertEqual(season_response.status_code, 201, season_response.data)
        season_id = season_response.data["id"]
        season_name = season_response.data["name"]

        self.authenticate_as(self.finance_user)
        subscription_response = self.client.post(
            reverse("farmer-subscription-list"),
            {
                "farmer": farmer_id,
                "paid_amount": "500.00",
                "payment_date": "2026-08-04",
                "season": season_name,
            },
            format="json",
        )
        self.assertEqual(subscription_response.status_code, 201, subscription_response.data)
        self.assertEqual(subscription_response.data["payment_status"], "PAID")

        self.authenticate_as(self.programme_user)
        Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        programme_response = self.client.post(
            reverse("programme-list"),
            {
                "name": "SGR 200HA+ Golden 2026/27",
                "code": "GOLDEN-200HA-2026",
                "season": season_id,
                "crop": "Maize",
                "institution": "ARDA",
                "announced_hectares": "20000.00",
                "status": "OPEN",
            },
            format="json",
        )
        self.assertEqual(programme_response.status_code, 201, programme_response.data)
        programme_id = programme_response.data["id"]

        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {
                "programme": programme_id,
                "season": season_id,
                "crop": "Maize",
                "requested_hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.data)
        line_response = self.client.post(
            reverse("arda-farmer-request-list"),
            {
                "request_batch": batch_response.data["id"],
                "farmer": farmer_id,
                "farm": farm_id,
                "requested_hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(line_response.status_code, 201, line_response.data)
        approval_response = self.client.post(
            reverse("arda-farmer-request-approve", kwargs={"pk": line_response.data["id"]}),
            {"approved_hectares": "10.00"},
            format="json",
        )
        self.assertEqual(approval_response.status_code, 200, approval_response.data)

        crop = Crop.objects.get(name="Maize")
        CropInputRequirement.objects.create(
            crop=crop,
            group_name="Seed",
            item_name="Golden Seed",
            rate_per_hectare="2.00",
            unit="bags",
            cost_per_unit="10.00",
            cost_per_hectare="20.00",
            include_in_input_cost=True,
            active=True,
        )
        CropSellingPrice.objects.create(crop=crop, season_id=season_id, price_per_tonne="200.00", active=True)
        allocation_response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": farmer_id,
                "farm": farm_id,
                "programme": programme_id,
                "crop_reference": crop.id,
                "hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(allocation_response.status_code, 201, allocation_response.data)

        production_response = self.client.post(
            reverse("farmer-production-list"),
            {
                "farmer": farmer_id,
                "farm": farm_id,
                "season": season_id,
                "crop": "Maize",
                "contracted_hectares": "10.00",
                "planted_hectares": "9.00",
                "expected_yield": "5.00",
                "actual_production": "4.00",
                "crop_stage": "HARVESTED",
                "status": "HARVESTED",
            },
            format="json",
        )
        self.assertEqual(production_response.status_code, 201, production_response.data)

        self.authenticate_as(self.recovery_user)
        delivery_response = self.client.post(
            reverse("delivery-list"),
            {
                "farmer": farmer_id,
                "farm": farm_id,
                "season": season_id,
                "crop": "Maize",
                "delivery_date": "2027-04-20",
                "gmb_depot": "GMB Golden Depot",
                "ticket_number": "GOLDEN-TICKET-001",
                "tonnes": "4.00",
                "price": "200.00",
                "recovery_tonnes": "0.50",
            },
            format="json",
        )
        self.assertEqual(delivery_response.status_code, 201, delivery_response.data)
        self.assertEqual(delivery_response.data["value"], "800.00")

        self.authenticate_as(self.dashboard_user)
        dashboard_response = self.client.get(reverse("dashboard-summary"))
        self.assertEqual(dashboard_response.status_code, 200, dashboard_response.data)
        self.assertEqual(dashboard_response.data["registered_farmers"], 1)
        self.assertEqual(float(dashboard_response.data["total_hectares"]), 12.5)
        self.assertEqual(float(dashboard_response.data["arda_requested_hectares"]), 10.0)
        self.assertNotIn("arda_approved_hectares", dashboard_response.data)
        self.assertNotIn("approved", dashboard_response.data["charts"]["arda_hectares"])
        self.assertEqual(float(dashboard_response.data["input_allocated_hectares"]), 10.0)
        self.assertEqual(float(dashboard_response.data["production"]), 4.0)
        self.assertEqual(float(dashboard_response.data["grain_delivered_tonnes"]), 4.0)
        self.assertEqual(float(dashboard_response.data["outstanding_recovery_tonnes"]), 0.5)
        self.assertEqual(float(dashboard_response.data["recovery_percentage"]), 50.0)
