from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farm, Farmer
from apps.geography.models import District, Province, Ward
from apps.inputs.models import InputAllocation
from apps.production.models import FarmerProduction, GMBDelivery, SeasonalPlantingPlan
from apps.recovery.models import InputDebt
from apps.subscriptions.models import FarmerSubscription

from .calendar import (
    agricultural_year_for_date,
    crop_season_for_date,
    crop_seasons_for_date,
    ensure_current_agricultural_year,
    season_is_selectable,
)
from .models import Crop, Programme, Season

User = get_user_model()


class AgriculturalCalendarTests(TestCase):
    def test_agricultural_year_follows_october_boundary(self):
        expectations = {
            date(2026, 10, 17): "2026/2027",
            date(2026, 12, 15): "2026/2027",
            date(2027, 1, 15): "2026/2027",
            date(2027, 2, 15): "2026/2027",
            date(2027, 9, 30): "2026/2027",
            date(2027, 10, 1): "2027/2028",
        }
        for on_date, label in expectations.items():
            spec = agricultural_year_for_date(on_date)
            self.assertEqual(spec["name"], label, on_date)
            self.assertEqual(spec["start_date"], date(spec["start_year"], 10, 1))
            self.assertEqual(spec["end_date"], date(spec["end_year"], 9, 30))

    def test_april_transition_assigns_each_date_to_one_season(self):
        self.assertEqual(crop_season_for_date(date(2026, 10, 1)), "SUMMER")
        self.assertEqual(crop_season_for_date(date(2027, 4, 15)), "SUMMER")
        self.assertEqual(crop_season_for_date(date(2027, 4, 16)), "WINTER")
        self.assertEqual(crop_season_for_date(date(2027, 9, 30)), "WINTER")
        self.assertEqual(crop_season_for_date(date(2027, 10, 1)), "SUMMER")
        seasons = crop_seasons_for_date(date(2026, 10, 17))
        self.assertEqual(seasons[0]["start_date"], "2026-10-01")
        self.assertEqual(seasons[0]["end_date"], "2027-04-15")
        self.assertEqual(seasons[1]["start_date"], "2027-04-16")
        self.assertEqual(seasons[1]["end_date"], "2027-09-30")

    def test_repeated_initialization_does_not_duplicate_or_rewrite_years(self):
        first = ensure_current_agricultural_year(date(2026, 10, 17))
        for on_date in (date(2026, 12, 15), date(2027, 2, 15), date(2027, 4, 15), date(2027, 9, 30)):
            again = ensure_current_agricultural_year(on_date)
            self.assertEqual(again.pk, first.pk)
        self.assertEqual(Season.objects.filter(name="2026/2027").count(), 1)

        next_year = ensure_current_agricultural_year(date(2027, 10, 1))
        self.assertEqual(next_year.name, "2027/2028")
        self.assertNotEqual(next_year.pk, first.pk)
        self.assertEqual(Season.objects.filter(name="2026/2027").count(), 1)
        self.assertEqual(Season.objects.filter(name="2027/2028").count(), 1)

        legacy = Season.objects.get(name="2026/2027")
        legacy.start_date = date(2026, 10, 2)
        legacy.notes = "keep"
        legacy.status = Season.STATUS_DRAFT
        legacy.save(update_fields=["start_date", "notes", "status"])
        preserved = ensure_current_agricultural_year(date(2026, 11, 1))
        preserved.refresh_from_db()
        self.assertEqual(preserved.pk, legacy.pk)
        self.assertEqual(preserved.start_date, date(2026, 10, 2))
        self.assertEqual(preserved.notes, "keep")
        self.assertEqual(preserved.status, Season.STATUS_DRAFT)

    def test_single_matching_year_is_reused_and_ambiguous_years_are_not_merged(self):
        legacy = Season.objects.create(name="Legacy 2024/25", start_date="2024-10-01", end_date="2025-09-30", status=Season.STATUS_CLOSED)
        reused = ensure_current_agricultural_year(date(2025, 3, 1))
        self.assertEqual(reused.pk, legacy.pk)
        self.assertEqual(Season.objects.filter(start_date="2024-10-01", end_date="2025-09-30").count(), 1)

        Season.objects.create(name="Year A", start_date="2023-10-01", end_date="2024-09-30")
        Season.objects.create(name="Year B", start_date="2023-10-01", end_date="2024-09-30")
        created = ensure_current_agricultural_year(date(2024, 1, 15))
        self.assertEqual(created.name, "2023/2024")
        self.assertTrue(Season.objects.filter(name="Year A").exists())
        self.assertTrue(Season.objects.filter(name="Year B").exists())
        self.assertEqual(Season.objects.filter(name="2023/2024").count(), 1)


class AgriculturalPeriodApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="period@example.com",
            username="period-user",
            password="StrongPass123!",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.province = Province.objects.create(name="Midlands", code="MD")
        self.district = District.objects.create(province=self.province, name="Gweru")
        self.ward = Ward.objects.create(district=self.district, name="Ward 1")
        self.farmer = Farmer.objects.create(
            first_name="Tariro",
            surname="Moyo",
            national_id="63-2000001-A-11",
            phone_primary="0772000001",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.other_farmer = Farmer.objects.create(
            first_name="Rudo",
            surname="Dube",
            national_id="63-2000002-A-11",
            phone_primary="0772000002",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer,
            farm_name="Moyo Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="12.50",
            arable_hectares="10.00",
        )
        self.old_season = Season.objects.create(name="2025/2026", start_date="2025-10-01", end_date="2026-09-30", status=Season.STATUS_CLOSED)
        self.current_season = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        self.maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
        self.wheat = Crop.objects.create(name="Wheat", category=Crop.CATEGORY_WINTER)
        self.old_programme = Programme.objects.create(
            name="Old Maize", code="OLD-MAIZE", season=self.old_season, crop="MAIZE", announced_hectares="100.00",
        )
        self.current_programme = Programme.objects.create(
            name="Current Wheat", code="CURRENT-WHEAT", season=self.current_season, crop="Wheat", announced_hectares="100.00",
        )
        FarmerProduction.objects.create(farmer=self.farmer, season=self.old_season, crop="Maize", actual_production="4.00")
        FarmerProduction.objects.create(farmer=self.farmer, season=self.current_season, crop="Wheat", actual_production="9.00")
        FarmerProduction.objects.create(farmer=self.farmer, season=self.current_season, crop="Maize", actual_production="2.00")
        GMBDelivery.objects.create(
            farmer=self.farmer, season=self.old_season, crop="Maize", delivery_date="2026-03-01", tonnes="4.00", price="10.00",
        )
        GMBDelivery.objects.create(
            farmer=self.farmer, season=self.current_season, crop="Wheat", delivery_date="2027-06-01", tonnes="3.00", price="10.00",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, programme=self.old_programme, crop_reference=self.maize, crop="Maize", hectares="6.00",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, programme=self.current_programme, crop_reference=self.wheat, crop="Wheat", hectares="3.00",
        )
        InputDebt.objects.create(
            farmer=self.farmer, programme=self.old_programme, crop="Maize",
            required_recovery_tonnes="5.00", recovered_tonnes="1.00", outstanding_tonnes="4.00",
        )
        InputDebt.objects.create(
            farmer=self.farmer, programme=self.current_programme, crop="Wheat",
            required_recovery_tonnes="3.00", recovered_tonnes="0.00", outstanding_tonnes="3.00",
        )
        old_batch = ARDARequestBatch.objects.create(
            request_number="SGR9001", programme=self.old_programme, season=self.old_season, crop="Maize", requested_hectares="10.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=old_batch, farmer=self.farmer, requested_hectares="10.00", approved_hectares="8.00",
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        current_batch = ARDARequestBatch.objects.create(
            request_number="SGR9002", programme=self.current_programme, season=self.current_season, crop="Wheat", requested_hectares="2.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=current_batch, farmer=self.farmer, requested_hectares="2.00", approved_hectares="0.00",
        )
        SeasonalPlantingPlan.objects.create(
            farmer=self.farmer, farm=self.farm, season=self.old_season, summer_crop=self.maize, summer_hectares="5.00",
        )
        FarmerSubscription.objects.create(farmer=self.farmer, season="2025/2026", paid_amount="500.00", payment_date="2026-01-15")
        FarmerSubscription.objects.create(farmer=self.farmer, season="2026/2027", paid_amount="10.00", payment_date="2026-11-01")

    def _ids(self, response):
        return {row["id"] for row in response.data["results"]}

    def test_current_period_endpoint_is_authoritative_and_idempotent(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(reverse("season-current")).status_code, 401)

        with patch("apps.programmes.calendar.timezone.localdate", return_value=date(2026, 10, 17)):
            first = self.client.get(reverse("season-current"))
            second = self.client.get(reverse("season-current"))
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["agricultural_year"]["name"], "2026/2027")
        self.assertEqual(first.data["crop_season"], "SUMMER")
        self.assertIn("15 April", first.data["april_convention"])
        self.assertEqual(first.data["agricultural_year"]["id"], second.data["agricultural_year"]["id"])
        self.assertEqual(Season.objects.filter(name="2026/2027").count(), 1)
        self.assertTrue(first.data["agricultural_year"]["is_current"])
        self.assertTrue(first.data["agricultural_year"]["selectable"])
        self.assertFalse(season_is_selectable(self.old_season))
        self.assertEqual(first.data["agricultural_year"]["crop_seasons"][0]["code"], "SUMMER")
        self.assertEqual(first.data["agricultural_year"]["crop_seasons"][1]["code"], "WINTER")

        with patch("apps.programmes.calendar.timezone.localdate", return_value=date(2027, 4, 16)):
            winter = self.client.get(reverse("season-current"))
        self.assertEqual(winter.data["agricultural_year"]["name"], "2026/2027")
        self.assertEqual(winter.data["crop_season"], "WINTER")

        with patch("apps.programmes.calendar.timezone.localdate", return_value=date(2027, 10, 1)):
            following = self.client.get(reverse("season-current"))
        self.assertEqual(following.data["agricultural_year"]["name"], "2027/2028")
        self.assertEqual(following.data["crop_season"], "SUMMER")
        self.assertEqual(Season.objects.filter(name="2027/2028").count(), 1)

        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])
        with patch("apps.programmes.calendar.timezone.localdate", return_value=date(2026, 12, 15)):
            visible = self.client.get(reverse("season-current"))
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(visible.data["crop_season"], "SUMMER")

    def test_historical_period_filters_transactions_without_hiding_farmers(self):
        old_summer = {"season": self.old_season.id, "season_name": self.old_season.name, "crop_season": "SUMMER"}
        current_winter = {"season": self.current_season.id, "season_name": self.current_season.name, "crop_season": "WINTER"}
        empty_winter = {"season": self.old_season.id, "season_name": self.old_season.name, "crop_season": "WINTER"}

        productions = self.client.get(reverse("farmer-production-list"), old_summer)
        self.assertEqual(productions.status_code, 200)
        self.assertEqual([row["actual_production"] for row in productions.data["results"]], ["4.00"])
        current_productions = self.client.get(reverse("farmer-production-list"), current_winter)
        self.assertEqual([row["actual_production"] for row in current_productions.data["results"]], ["9.00"])
        self.assertEqual(self.client.get(reverse("farmer-production-list"), empty_winter).data["results"], [])

        deliveries = self.client.get(reverse("delivery-list"), old_summer)
        self.assertEqual([row["tonnes"] for row in deliveries.data["results"]], ["4.00"])
        self.assertEqual(self.client.get(reverse("delivery-list"), current_winter).data["results"][0]["tonnes"], "3.00")

        programmes = self.client.get(reverse("programme-list"), old_summer)
        self.assertEqual(self._ids(programmes), {self.old_programme.id})
        self.assertEqual(self._ids(self.client.get(reverse("programme-list"), current_winter)), {self.current_programme.id})

        allocations = self.client.get(reverse("input-allocation-list"), old_summer)
        self.assertEqual([row["hectares"] for row in allocations.data["results"]], ["6.00"])
        self.assertEqual(self.client.get(reverse("input-allocation-list"), empty_winter).data["results"], [])

        debts = self.client.get(reverse("input-debt-list"), old_summer)
        self.assertEqual([row["outstanding_tonnes"] for row in debts.data["results"]], ["4.00"])
        self.assertEqual(self.client.get(reverse("input-debt-list"), current_winter).data["results"][0]["outstanding_tonnes"], "3.00")

        batches = self.client.get(reverse("arda-request-batch-list"), old_summer)
        self.assertEqual(self._ids(batches), {ARDARequestBatch.objects.get(request_number="SGR9001").id})
        self.assertEqual(
            self._ids(self.client.get(reverse("arda-request-batch-list"), current_winter)),
            {ARDARequestBatch.objects.get(request_number="SGR9002").id},
        )

        plans = self.client.get(reverse("seasonal-planting-plan-list"), old_summer)
        self.assertEqual(len(plans.data["results"]), 1)
        self.assertEqual(self.client.get(reverse("seasonal-planting-plan-list"), empty_winter).data["results"], [])

        farmers = self.client.get(reverse("farmer-list"), {**old_summer, "search": "Moyo"})
        self.assertEqual(farmers.status_code, 200)
        self.assertEqual(len(farmers.data["results"]), 1)
        self.assertEqual(farmers.data["results"][0]["id"], self.farmer.id)

        invalid = self.client.get(reverse("farmer-production-list"), {"crop_season": "SPRING"})
        self.assertEqual(invalid.status_code, 400)

    def test_dashboard_uses_selected_period_and_keeps_permanent_totals(self):
        old_summer = {"season": self.old_season.id, "crop_season": "SUMMER"}
        current_winter = {"season": self.current_season.id, "crop_season": "WINTER"}
        historical = self.client.get(reverse("dashboard-summary"), old_summer)
        current = self.client.get(reverse("dashboard-summary"), current_winter)
        self.assertEqual(historical.status_code, 200, historical.data)
        self.assertEqual(historical.data["registered_farmers"], 2)
        self.assertEqual(float(historical.data["total_hectares"]), 12.5)
        self.assertEqual(float(historical.data["production"]), 4.0)
        self.assertEqual(float(historical.data["grain_delivered_tonnes"]), 4.0)
        self.assertEqual(float(historical.data["input_allocated_hectares"]), 6.0)
        self.assertEqual(float(historical.data["outstanding_recovery_tonnes"]), 4.0)
        self.assertEqual(float(historical.data["arda_requested_hectares"]), 10.0)
        self.assertEqual(float(historical.data["arda_approved_hectares"]), 8.0)
        self.assertEqual(float(current.data["production"]), 9.0)
        self.assertEqual(float(current.data["grain_delivered_tonnes"]), 3.0)
        self.assertEqual(float(current.data["input_allocated_hectares"]), 3.0)
        self.assertEqual(float(current.data["outstanding_recovery_tonnes"]), 3.0)
        self.assertEqual(float(current.data["arda_requested_hectares"]), 2.0)
        self.assertEqual(current.data["registered_farmers"], 2)

    def test_subscription_search_and_pagination_follow_the_agricultural_year(self):
        old = self.client.get(reverse("farmer-subscription-list"), {"season": "2025/2026", "search": "Moyo", "page": 1, "page_size": 25})
        current = self.client.get(reverse("farmer-subscription-list"), {"season": "2026/2027", "search": "Moyo", "page": 1, "page_size": 25})
        other = self.client.get(reverse("farmer-subscription-list"), {"season": "2025/2026", "search": "Dube", "page": 1, "page_size": 25})
        self.assertEqual(old.status_code, 200, old.data)
        self.assertEqual(old.data["count"], 1)
        self.assertEqual(old.data["results"][0]["paid_amount"], "500.00")
        self.assertEqual(old.data["results"][0]["season"], "2025/2026")
        self.assertEqual(current.data["results"][0]["paid_amount"], "10.00")
        self.assertEqual(current.data["results"][0]["season"], "2026/2027")
        self.assertEqual(other.data["count"], 1)
        self.assertEqual(other.data["results"][0]["paid_amount"], "0.00")
        self.assertNotEqual(other.data["results"][0]["farmer"], self.farmer.id)

    def test_historical_edits_are_rejected_without_weakening_rbac(self):
        active = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": self.current_programme.id, "season": self.current_season.id, "crop": "Maize", "requested_hectares": "5.00"},
            format="json",
        )
        self.assertEqual(active.status_code, 201, active.data)

        closed_batch = ARDARequestBatch.objects.get(request_number="SGR9001")
        viewed = self.client.get(reverse("arda-request-batch-detail", kwargs={"pk": closed_batch.pk}))
        self.assertEqual(viewed.status_code, 200)
        rejected = self.client.patch(
            reverse("arda-request-batch-detail", kwargs={"pk": closed_batch.pk}),
            {"requested_hectares": "12.00"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("active season", str(rejected.data).lower())
        closed_batch.refresh_from_db()
        self.assertEqual(str(closed_batch.requested_hectares), "10.00")

        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])
        readable = self.client.get(reverse("farmer-production-list"), {"season": self.old_season.id, "crop_season": "SUMMER"})
        self.assertEqual(readable.status_code, 200)
        self.assertEqual(len(readable.data["results"]), 1)
        denied = self.client.post(
            reverse("farmer-production-list"),
            {"farmer": self.farmer.id, "season": self.current_season.id, "crop": "Maize", "actual_production": "1.00"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)
        bypass = self.client.patch(
            reverse("arda-request-batch-detail", kwargs={"pk": closed_batch.pk}),
            {"requested_hectares": "20.00"},
            format="json",
        )
        self.assertEqual(bypass.status_code, 403)
        closed_batch.refresh_from_db()
        self.assertEqual(str(closed_batch.requested_hectares), "10.00")
