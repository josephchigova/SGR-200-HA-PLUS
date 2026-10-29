from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farmers.models import Farm, Farmer
from apps.geography.models import District, Province, Ward
from apps.programmes.models import Crop, Season

from .seasonal_services import SeasonalPlantingValidationService, SeasonalSubscriptionService

User = get_user_model()


class SeasonalPlantingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="seasonal@example.com", username="seasonal-user", password="StrongPass123!",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        province = Province.objects.create(name="Season Province", code="SP")
        district = District.objects.create(province=province, name="Season District")
        ward = Ward.objects.create(district=district, name="Season Ward")
        self.farmer = Farmer.objects.create(
            first_name="Season", surname="Farmer", national_id="63-1111111-X-91",
            phone_primary="0771111191", province=province, district=district, ward=ward,
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Season Farm", province=province, district=district,
            ward=ward, total_hectares="250.00", arable_hectares="200.00", irrigated_hectares="50.00",
        )
        self.season = Season.objects.create(
            name="2026/2027", start_date="2026-11-01", end_date="2027-10-31", status=Season.STATUS_ACTIVE,
        )
        call_command("seed_crops")
        self.maize = Crop.objects.get(name="Maize")
        self.sorghum = Crop.objects.get(name="Sorghum")
        self.wheat = Crop.objects.get(name="Wheat")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_both_summer_and_winter_crops_are_traceable(self):
        response = self.client.post(
            reverse("seasonal-planting-plan-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk,
                "summer_crop": self.maize.pk, "summer_hectares": "50.00",
                "winter_crop": self.wheat.pk, "winter_hectares": "150.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_planted_hectares"], "200.00")
        self.assertEqual(response.data["recommended_subscription_amount"], 1000)

    def test_one_crop_or_nothing_in_one_period_is_supported(self):
        summer_only = self.client.post(
            reverse("seasonal-planting-plan-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk,
                "summer_crop": self.sorghum.pk, "summer_hectares": "80.00", "winter_hectares": "0.00",
            },
            format="json",
        )
        self.assertEqual(summer_only.status_code, 201, summer_only.data)
        self.assertEqual(summer_only.data["winter_crop"], None)

    def test_crop_categories_and_arable_boundary_are_enforced(self):
        wrong_category = self.client.post(
            reverse("seasonal-planting-plan-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk,
                "summer_crop": self.wheat.pk, "summer_hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(wrong_category.status_code, 400)

        over_arable = self.client.post(
            reverse("seasonal-planting-plan-list"),
            {
                "farmer": self.farmer.pk, "farm": self.farm.pk, "season": self.season.pk,
                "summer_crop": self.maize.pk, "summer_hectares": "201.00",
            },
            format="json",
        )
        self.assertEqual(over_arable.status_code, 400)

    def test_subscription_threshold(self):
        self.assertEqual(SeasonalSubscriptionService.subscription_amount("199.99"), 500)
        self.assertEqual(SeasonalSubscriptionService.subscription_amount("200.00"), 1000)
        self.assertTrue(SeasonalPlantingValidationService.validate(
            summer_crop=self.maize, winter_crop=None, summer_hectares="10", winter_hectares="0", farm=self.farm,
        ))
