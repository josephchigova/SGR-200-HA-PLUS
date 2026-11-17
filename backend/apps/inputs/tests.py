from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farmer
from apps.geography.models import District, Province, Ward
from apps.inputs.services import InputAllocationService
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Programme, Season
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()


class InputIssueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="inputs@example.com",
            username="inputs-user",
            password="StrongPass123!",
            first_name="Leroy",
            last_name="Chikoto",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.province = Province.objects.create(name="Bulawayo", code="BU")
        self.district = District.objects.create(province=self.province, name="Bulawayo")
        self.ward = Ward.objects.create(district=self.district, name="Ward 3")
        self.farmer = Farmer.objects.create(
            first_name="Nyaradzo",
            surname="Khumalo",
            national_id="63-4567890-Q-77",
            phone_primary="0773000000",
            email="nyaradzo@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_VERIFIED,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_input_issue_can_be_created(self):
        response = self.client.post(
            reverse("input-issue-list"),
            {
                "farmer": self.farmer.id,
                "input_name": "Seed Pack",
                "batch_number": "SEED-2026-001",
                "quantity": 25,
                "unit": "bags",
                "issue_status": "ISSUED",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["input_name"], "Seed Pack")


class InputAllocationCatalogueFlowTests(TestCase):
    """Checks of the older allocation service, kept for allocations made before programme catalogues.

    New allocations come only from a programme's catalogue and an approved input request; that
    flow is tested in test_programme_allocation.py.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="allocations@example.com",
            username="allocations-user",
            password="StrongPass123!",
            first_name="Leroy",
            last_name="Moyo",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.province = Province.objects.create(name="Bulawayo", code="BU")
        self.district = District.objects.create(province=self.province, name="Bulawayo")
        self.ward = Ward.objects.create(district=self.district, name="Ward 3")
        self.farmer = Farmer.objects.create(
            first_name="Nyaradzo",
            surname="Khumalo",
            national_id="63-4567890-Q-77",
            phone_primary="0773000000",
            email="nyaradzo@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_VERIFIED,
        )
        self.farm = self.farmer.farms.create(
            farm_name="Nyaradzo Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="220.00",
            arable_hectares="200.00",
            verification_status="VERIFIED",
        )
        self.season = Season.objects.create(name="Inputs 2026/27", start_date="2026-10-01", end_date="2027-09-30")
        FarmerSubscription.objects.create(
            farmer=self.farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount="500.00",
            outstanding_amount="0.00",
            payment_status="PAID",
            season=self.season.name,
        )
        self.programme = Programme.objects.create(name="Input Programme", code="INPUT-PROG", season=self.season, announced_hectares=500)
        batch = ARDARequestBatch.objects.create(
            request_number="INPUT-BATCH",
            programme=self.programme,
            season=self.season,
            crop="Sorghum",
            requested_hectares="200.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares=200,
            approved_hectares=200,
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        self.crop = Crop.objects.create(name="Sorghum", category=Crop.CATEGORY_SUMMER, active=True)
        CropInputRequirement.objects.create(
            crop=self.crop,
            group_name="Chemicals",
            item_name="Metolachlor",
            rate_per_hectare="6.00",
            unit="kg",
            cost_per_unit="23.00",
            cost_per_hectare="138.00",
            active=True,
        )
        CropInputRequirement.objects.create(
            crop=self.crop,
            group_name="Chemicals",
            item_name="Atrazine",
            rate_per_hectare="4.00",
            unit="kg",
            cost_per_unit="12.00",
            cost_per_hectare="48.00",
            active=True,
        )
        CropInputRequirement.objects.create(
            crop=self.crop,
            group_name="Machinery",
            item_name="Discing",
            rate_per_hectare="1.00",
            unit="ha",
            cost_per_unit="100.00",
            cost_per_hectare="100.00",
            cost_type=CropInputRequirement.COST_TYPE_MACHINERY,
            active=True,
        )
        CropSellingPrice.objects.create(crop=self.crop, season=self.season, price_per_tonne="300.00", active=True)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _make_farmer_and_farm(self, suffix):
        farmer = Farmer.objects.create(
            first_name=f"Approval{suffix}",
            surname="Farmer",
            national_id=f"63-TEST-{suffix}",
            phone_primary="0773999999",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_VERIFIED,
        )
        FarmerSubscription.objects.create(
            farmer=farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount="500.00",
            outstanding_amount="0.00",
            payment_status="PAID",
            season=self.season.name,
        )
        farm = farmer.farms.create(
            farm_name=f"Approval Farm {suffix}",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="100.00",
            arable_hectares="100.00",
            verification_status="VERIFIED",
        )
        return farmer, farm

    def test_input_allocation_hectares_validation_boundaries(self):
        base_url = reverse("input-allocation-list")
        for hectares in ("0", "-1"):
            with self.subTest(hectares=hectares):
                response = self.client.post(
                    base_url,
                    {
                        "farmer": self.farmer.pk,
                        "farm": self.farm.pk,
                        "programme": self.programme.pk,
                        "crop_reference": self.crop.pk,
                        "hectares": hectares,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400)

        over_response = self.client.post(
            base_url,
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "201.00",
            },
            format="json",
        )
        self.assertEqual(over_response.status_code, 400)

    def test_unauthorized_user_cannot_create_allocation(self):
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])
        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_wrong_crop_approval_does_not_apply_to_selected_crop(self):
        farmer, farm = self._make_farmer_and_farm("CROP")
        batch = ARDARequestBatch.objects.create(
            request_number="INPUT-WRONG-CROP",
            programme=self.programme,
            season=self.season,
            crop=self.crop.name,
            requested_hectares="50.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=farmer,
            farm=farm,
            requested_hectares="50.00",
            approved_hectares="50.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)

        with self.assertRaisesRegex(ValueError, "No ARDA request hectares"):
            InputAllocationService._validate_hectares(
                farmer=farmer,
                farm=farm,
                programme=self.programme,
                crop_reference=maize,
                crop_name=maize.name,
                hectares="20.00",
            )

    def test_approval_from_another_batch_season_does_not_apply(self):
        farmer, farm = self._make_farmer_and_farm("SEASON")
        other_season = Season.objects.create(
            name="Other season",
            start_date="2027-10-01",
            end_date="2028-09-30",
        )
        batch = ARDARequestBatch.objects.create(
            request_number="INPUT-WRONG-SEASON",
            programme=self.programme,
            season=other_season,
            crop="Maize",
            requested_hectares="50.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=farmer,
            farm=farm,
            requested_hectares="50.00",
            approved_hectares="50.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)

        with self.assertRaisesRegex(ValueError, "No ARDA request hectares"):
            InputAllocationService._validate_hectares(
                farmer=farmer,
                farm=farm,
                programme=self.programme,
                crop_reference=maize,
                crop_name=maize.name,
                hectares="20.00",
            )

    def test_eligible_farmer_can_allocate_on_any_registered_farm(self):
        other_farm = self.farmer.farms.create(
            farm_name="Second Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="100.00",
            arable_hectares="100.00",
            verification_status="VERIFIED",
        )

        _, hectares = InputAllocationService._validate_hectares(
            farmer=self.farmer,
            farm=other_farm,
            programme=self.programme,
            crop_reference=self.crop,
            crop_name=self.crop.name,
            hectares="20.00",
        )
        self.assertEqual(hectares, Decimal("20.00"))

    def test_farmer_level_approval_with_no_farm_link_applies_to_farmer_farm(self):
        farmer, farm = self._make_farmer_and_farm("GENERAL")
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        batch = ARDARequestBatch.objects.create(
            request_number="INPUT-FARMER-LEVEL",
            programme=self.programme,
            season=self.season,
            crop="Maize",
            requested_hectares="20.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=farmer,
            farm=None,
            requested_hectares="20.00",
            approved_hectares="20.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        _, hectares = InputAllocationService._validate_hectares(
            farmer=farmer,
            farm=farm,
            programme=self.programme,
            crop_reference=maize,
            crop_name=maize.name,
            hectares="20.00",
        )
        self.assertEqual(hectares, Decimal("20.00"))

    def test_missing_batch_capacity_reports_missing_record_not_false_overallocation(self):
        farmer, farm = self._make_farmer_and_farm("MISSING")
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)

        with self.assertRaisesRegex(ValueError, "No ARDA request hectares"):
            InputAllocationService._validate_hectares(
                farmer=farmer,
                farm=farm,
                programme=self.programme,
                crop_reference=maize,
                crop_name=maize.name,
                hectares="20.00",
            )

    def test_farmer_search_and_farm_filtering_endpoints_for_async_selector(self):
        second_farmer = Farmer.objects.create(
            first_name="Tatenda",
            surname="Moyo",
            national_id="63-5566778-Q-19",
            phone_primary="0773222222",
            email="tatenda@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_VERIFIED,
        )
        FarmerSubscription.objects.create(
            farmer=second_farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount="500.00",
            outstanding_amount="0.00",
            payment_status="PAID",
            season=self.season.name,
        )
        second_farm = second_farmer.farms.create(
            farm_name="Tatenda Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="100.00",
            arable_hectares="80.00",
            verification_status="VERIFIED",
        )

        search_response = self.client.get(reverse("farmer-list") + "?search=tat")
        self.assertEqual(search_response.status_code, 200)
        search_results = search_response.data.get("results", [])
        self.assertTrue(any(row["id"] == second_farmer.pk for row in search_results))

        farms_response = self.client.get(reverse("farm-list") + f"?farmer={second_farmer.pk}")
        self.assertEqual(farms_response.status_code, 200)
        farm_results = farms_response.data.get("results", [])
        self.assertTrue(any(row["id"] == second_farm.pk for row in farm_results))
        self.assertFalse(any(row["id"] == self.farm.pk for row in farm_results))
