from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farmer
from apps.geography.models import District, Province, Ward
from apps.inputs.models import InputAllocation
from apps.inputs.services import InputAllocationService
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Programme, Season
from apps.recovery.models import InputDebt
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
            include_in_input_cost=True,
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
            include_in_input_cost=True,
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
            include_in_input_cost=False,
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

    def test_preview_calculates_all_active_requirements_and_total_cost(self):
        response = self.client.get(
            reverse("input-allocation-preview") + f"?farmer={self.farmer.pk}&farm={self.farm.pk}&programme={self.programme.pk}&crop_reference={self.crop.pk}&hectares=200",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_input_cost"], "37200.00")
        self.assertEqual(response.data["required_recovery_tonnes"], "124.00")
        self.assertEqual(len(response.data["lines"]), 3)
        metolachlor = [line for line in response.data["lines"] if line["item_name"] == "Metolachlor"][0]
        atrazine = [line for line in response.data["lines"] if line["item_name"] == "Atrazine"][0]
        discing = [line for line in response.data["lines"] if line["item_name"] == "Discing"][0]
        self.assertEqual(metolachlor["required_quantity"], "1200.0000")
        self.assertEqual(metolachlor["calculated_cost"], "27600.00")
        self.assertEqual(atrazine["required_quantity"], "800.0000")
        self.assertEqual(atrazine["calculated_cost"], "9600.00")
        self.assertFalse(discing["included_in_total"])

    def test_allocation_creates_snapshot_lines_and_debt(self):
        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "200.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        allocation = InputAllocation.objects.get(pk=response.data["id"])
        self.assertEqual(allocation.total_input_cost, 37200)
        self.assertEqual(allocation.calculation_lines.count(), 3)

        debt = InputDebt.objects.get(input_allocation=allocation)
        self.assertEqual(debt.input_value, 37200)
        self.assertEqual(debt.required_recovery_tonnes, 124)
        self.assertEqual(debt.status, InputDebt.STATUS_NOT_RECOVERED)

    def test_historical_debt_snapshot_does_not_change_after_catalogue_update(self):
        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "100.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        allocation = InputAllocation.objects.get(pk=response.data["id"])
        original_cost = allocation.total_input_cost
        debt = InputDebt.objects.get(input_allocation=allocation)
        original_required_tonnes = debt.required_recovery_tonnes

        requirement = CropInputRequirement.objects.get(item_name="Metolachlor")
        requirement.cost_per_unit = 99
        requirement.cost_per_hectare = 594
        requirement.save(update_fields=["cost_per_unit", "cost_per_hectare", "updated_at"])

        allocation.refresh_from_db()
        debt.refresh_from_db()
        self.assertEqual(allocation.total_input_cost, original_cost)
        self.assertEqual(debt.required_recovery_tonnes, original_required_tonnes)

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

    def test_crop_scoped_approved_hectare_validation_matrix(self):
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        CropInputRequirement.objects.create(
            crop=maize,
            group_name="Seed",
            item_name="Maize Seed",
            rate_per_hectare="1.00",
            unit="bag",
            cost_per_unit="10.00",
            cost_per_hectare="10.00",
            include_in_input_cost=True,
            active=True,
        )
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="300.00", active=True)

        maize_batch = ARDARequestBatch.objects.create(
            request_number="INPUT-MAIZE-BATCH",
            programme=self.programme,
            season=self.season,
            crop="maize",
            requested_hectares="250.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=maize_batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares="40.00",
            approved_hectares="40.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        second_farmer = Farmer.objects.create(
            first_name="Themba",
            surname="Ncube",
            national_id="63-9876543-Q-77",
            phone_primary="0773111111",
            email="themba@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        second_farm = second_farmer.farms.create(
            farm_name="Themba Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="120.00",
            arable_hectares="100.00",
            verification_status="VERIFIED",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=maize_batch,
            farmer=second_farmer,
            farm=second_farm,
            requested_hectares="99.00",
            approved_hectares="99.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        second_programme = Programme.objects.create(
            name="Secondary Programme",
            code="INPUT-PROG-2",
            season=self.season,
            announced_hectares=500,
        )
        second_batch = ARDARequestBatch.objects.create(
            request_number="INPUT-BATCH-2",
            programme=second_programme,
            season=self.season,
            crop="maize",
            requested_hectares="80.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=second_batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares="80.00",
            approved_hectares="80.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        base_payload = {
            "farmer": self.farmer.pk,
            "farm": self.farm.pk,
            "programme": self.programme.pk,
            "crop_reference": maize.pk,
        }
        allocation_url = reverse("input-allocation-list")

        # Exact approved hectares should pass.
        exact_response = self.client.post(
            allocation_url,
            {**base_payload, "hectares": "40.00"},
            format="json",
        )
        self.assertEqual(exact_response.status_code, 201, exact_response.data)

        # Exceeding remaining approved hectares should fail.
        exceed_response = self.client.post(
            allocation_url,
            {**base_payload, "hectares": "0.01"},
            format="json",
        )
        self.assertEqual(exceed_response.status_code, 400)

        # Decimal approvals should pass when exactly matched.
        decimal_batch = ARDARequestBatch.objects.create(
            request_number="INPUT-MAIZE-DECIMAL",
            programme=self.programme,
            season=self.season,
            crop="maize",
            requested_hectares="3.50",
        )
        decimal_farmer, decimal_farm = self._make_farmer_and_farm("DECIMAL")
        ARDAFarmerRequest.objects.create(
            request_batch=decimal_batch,
            farmer=decimal_farmer,
            farm=decimal_farm,
            requested_hectares="3.50",
            approved_hectares="3.50",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        decimal_pass_response = self.client.post(
            allocation_url,
            {
                **base_payload,
                "farmer": decimal_farmer.pk,
                "farm": decimal_farm.pk,
                "hectares": "3.50",
            },
            format="json",
        )
        self.assertEqual(decimal_pass_response.status_code, 201, decimal_pass_response.data)

        # Different programme approvals must not leak into this programme's limit.
        other_programme_response = self.client.post(
            allocation_url,
            {**base_payload, "hectares": "76.51"},
            format="json",
        )
        self.assertEqual(other_programme_response.status_code, 400)

    def test_matching_twenty_hectare_maize_approval_accepts_exact_allocation(self):
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        CropInputRequirement.objects.create(
            crop=maize,
            group_name="Seed",
            item_name="Maize Seed",
            rate_per_hectare="1.00",
            unit="bag",
            cost_per_unit="10.00",
            cost_per_hectare="10.00",
            include_in_input_cost=True,
            active=True,
        )
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="300.00", active=True)
        batch = ARDARequestBatch.objects.create(
            request_number="INPUT-MAIZE-20",
            programme=self.programme,
            season=self.season,
            crop="Maize",
            requested_hectares="20.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares="20.00",
            approved_hectares="20.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": maize.pk,
                "hectares": "20.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

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

    def test_remaining_batch_capacity_is_consumed_across_eligible_farmers(self):
        allocation_url = reverse("input-allocation-list")
        payload = {
            "farmer": self.farmer.pk,
            "farm": self.farm.pk,
            "programme": self.programme.pk,
            "crop_reference": self.crop.pk,
        }

        first_response = self.client.post(
            allocation_url,
            {**payload, "hectares": "120.00"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201, first_response.data)

        second_farmer, second_farm = self._make_farmer_and_farm("REMAINING")
        remaining_response = self.client.post(
            allocation_url,
            {
                **payload,
                "farmer": second_farmer.pk,
                "farm": second_farm.pk,
                "hectares": "80.00",
            },
            format="json",
        )
        self.assertEqual(remaining_response.status_code, 201, remaining_response.data)

        third_farmer, third_farm = self._make_farmer_and_farm("OVER")
        over_response = self.client.post(
            allocation_url,
            {
                **payload,
                "farmer": third_farmer.pk,
                "farm": third_farm.pk,
                "hectares": "0.01",
            },
            format="json",
        )
        self.assertEqual(over_response.status_code, 400)

    def test_duplicate_allocation_for_same_farmer_farm_crop_programme_season_is_rejected(self):
        allocation_url = reverse("input-allocation-list")
        payload = {
            "farmer": self.farmer.pk,
            "farm": self.farm.pk,
            "programme": self.programme.pk,
            "crop_reference": self.crop.pk,
        }
        first_response = self.client.post(
            allocation_url,
            {**payload, "hectares": "10.00"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201, first_response.data)

        duplicate_response = self.client.post(
            allocation_url,
            {**payload, "hectares": "5.00"},
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, 400)
        self.assertIn("already exists", " ".join(duplicate_response.data.get("non_field_errors", [])).lower())

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

    def test_allocations_from_other_crop_do_not_reduce_available_hectares(self):
        maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        CropInputRequirement.objects.create(
            crop=maize,
            group_name="Seed",
            item_name="Maize Seed",
            rate_per_hectare="1.00",
            unit="bag",
            cost_per_unit="10.00",
            cost_per_hectare="10.00",
            include_in_input_cost=True,
            active=True,
        )
        CropSellingPrice.objects.create(crop=maize, season=self.season, price_per_tonne="300.00", active=True)

        maize_batch = ARDARequestBatch.objects.create(
            request_number="ISO-MAIZE-BATCH",
            programme=self.programme,
            season=self.season,
            crop="maize",
            requested_hectares="20.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=maize_batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares="20.00",
            approved_hectares="20.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        sorghum_response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "150.00",
            },
            format="json",
        )
        self.assertEqual(sorghum_response.status_code, 201, sorghum_response.data)

        maize_response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": maize.pk,
                "hectares": "20.00",
            },
            format="json",
        )
        self.assertEqual(maize_response.status_code, 201, maize_response.data)

    def test_allocations_from_other_season_do_not_reduce_available_hectares(self):
        next_season = Season.objects.create(name="Inputs 2027/28", start_date="2027-10-01", end_date="2028-09-30")
        next_programme = Programme.objects.create(name="Input Programme 2027", code="INPUT-PROG-2027", season=next_season, announced_hectares=500)
        next_batch = ARDARequestBatch.objects.create(
            request_number="INPUT-BATCH-2027",
            programme=next_programme,
            season=next_season,
            crop="sorghum",
            requested_hectares="50.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=next_batch,
            farmer=self.farmer,
            farm=self.farm,
            requested_hectares="50.00",
            approved_hectares="50.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        FarmerSubscription.objects.create(
            farmer=self.farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount="500.00",
            outstanding_amount="0.00",
            payment_status="PAID",
            season=next_season.name,
        )
        CropSellingPrice.objects.create(crop=self.crop, season=next_season, price_per_tonne="300.00", active=True)

        current_response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "200.00",
            },
            format="json",
        )
        self.assertEqual(current_response.status_code, 201, current_response.data)

        next_response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": next_programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "50.00",
            },
            format="json",
        )
        self.assertEqual(next_response.status_code, 201, next_response.data)

    def test_rejection_message_includes_approved_remaining_breakdown(self):
        first = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "200.00",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)

        second_farmer, second_farm = self._make_farmer_and_farm("CAP-MSG")

        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": second_farmer.pk,
                "farm": second_farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "1.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        message = " ".join(response.data.get("non_field_errors", []))
        self.assertIn("Requested in ARDA batches:", message)
        self.assertIn("already allocated:", message)
        self.assertIn("requested now:", message)
        self.assertIn("remaining:", message)

    def test_verified_paid_farmer_without_farmer_level_arda_line_can_allocate(self):
        farmer, farm = self._make_farmer_and_farm("AUTO")
        response = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": farmer.pk,
                "farm": farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "20.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_partly_paid_farmer_can_be_allocated_without_changing_the_balance_or_approved_limit(self):
        farmer = Farmer.objects.create(
            first_name="Partial",
            surname="Allocator",
            national_id="63-PARTIAL-ALLOC",
            phone_primary="0774555666",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_VERIFIED,
        )
        farm = farmer.farms.create(
            farm_name="Partial Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="100.00",
            arable_hectares="100.00",
            verification_status="VERIFIED",
        )
        subscription = FarmerSubscription.objects.create(
            farmer=farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount="250.00",
            outstanding_amount="250.00",
            payment_status="Partly Paid",
            season=self.season.name,
        )
        batch = ARDARequestBatch.objects.create(
            request_number="PARTIAL-LIMIT",
            programme=self.programme,
            season=self.season,
            crop=self.crop.name,
            requested_hectares="50.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=farmer,
            farm=farm,
            requested_hectares="10.00",
            approved_hectares="10.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )

        eligible = self.client.get(reverse("farmer-eligible"), {"season": self.season.name, "search": "Allocator"})
        self.assertEqual(eligible.status_code, 200, eligible.data)
        self.assertIn(farmer.pk, {row["id"] for row in eligible.data["results"]})
        self.assertEqual(eligible.data["results"][0]["subscription_status"], "PARTIALLY_PAID")

        over_limit = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": farmer.pk,
                "farm": farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "11.00",
            },
            format="json",
        )
        self.assertEqual(over_limit.status_code, 400)
        self.assertIn("approved", " ".join(over_limit.data.get("non_field_errors", [])).lower())

        allocated = self.client.post(
            reverse("input-allocation-list"),
            {
                "farmer": farmer.pk,
                "farm": farm.pk,
                "programme": self.programme.pk,
                "crop_reference": self.crop.pk,
                "hectares": "10.00",
            },
            format="json",
        )
        self.assertEqual(allocated.status_code, 201, allocated.data)

        subscription.refresh_from_db()
        self.assertEqual(subscription.payment_status, "Partly Paid")
        self.assertEqual(subscription.paid_amount, Decimal("250.00"))
        self.assertEqual(subscription.outstanding_amount, Decimal("250.00"))

    def test_unverified_or_unpaid_farmer_is_rejected_for_input_allocation(self):
        for suffix, verification_status, payment_status in [
            ("UNVERIFIED", Farmer.STATUS_DRAFT, "PAID"),
            ("UNPAID", Farmer.STATUS_VERIFIED, "UNPAID"),
        ]:
            with self.subTest(suffix=suffix):
                farmer = Farmer.objects.create(
                    first_name=f"{suffix} Farmer",
                    surname="Inputs",
                    national_id=f"63-INPUT-{suffix}",
                    phone_primary=f"0774{len(suffix):07d}",
                    province=self.province,
                    district=self.district,
                    ward=self.ward,
                    verification_status=verification_status,
                )
                farm = farmer.farms.create(
                    farm_name=f"{suffix} Farm",
                    province=self.province,
                    district=self.district,
                    ward=self.ward,
                    total_hectares="100.00",
                    arable_hectares="100.00",
                    verification_status="VERIFIED",
                )
                FarmerSubscription.objects.create(
                    farmer=farmer,
                    category="UNDER_200HA",
                    expected_amount="500.00",
                    paid_amount="500.00" if payment_status == "PAID" else "0.00",
                    outstanding_amount="0.00" if payment_status == "PAID" else "500.00",
                    payment_status=payment_status,
                    season=self.season.name,
                )

                response = self.client.post(
                    reverse("input-allocation-list"),
                    {
                        "farmer": farmer.pk,
                        "farm": farm.pk,
                        "programme": self.programme.pk,
                        "crop_reference": self.crop.pk,
                        "hectares": "5.00",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("ineligible", " ".join(response.data.get("non_field_errors", [])).lower())

    def test_winter_crop_is_rejected_for_a_summer_allocation(self):
        winter = Crop.objects.create(name="Winter Wheat", category=Crop.CATEGORY_WINTER, active=True)
        response = self.client.post(
            reverse("input-allocation-list") + "?crop_season=SUMMER",
            {
                "farmer": self.farmer.pk,
                "farm": self.farm.pk,
                "programme": self.programme.pk,
                "crop_reference": winter.pk,
                "hectares": "5.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Summer", str(response.data))
