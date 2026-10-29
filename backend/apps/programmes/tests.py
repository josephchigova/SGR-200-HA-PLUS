from io import StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farmers.models import Farmer
from apps.geography.models import District, Province, Ward

from .models import Programme
from .models import Crop, CropInputRequirement, Season
from .services import ProgrammeCapacityService, RoleAccessService

User = get_user_model()


class ProgrammeAllocationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="programme@example.com",
            username="programme-user",
            password="StrongPass123!",
            first_name="Moses",
            last_name="Ndlovu",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.province = Province.objects.create(name="Masvingo", code="MV")
        self.district = District.objects.create(province=self.province, name="Masvingo")
        self.ward = Ward.objects.create(district=self.district, name="Ward 2")
        self.farmer = Farmer.objects.create(
            first_name="Rudo",
            surname="Dube",
            national_id="63-9876543-Z-12",
            phone_primary="0772000000",
            email="rudo@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.programme = Programme.objects.create(
            name="2026 Input Support",
            code="2026-INPUT",
            description="Smallholder input assistance programme",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_programme_allocation_create(self):
        url = reverse("programme-allocations-list")
        response = self.client.post(
            url,
            {
                "programme": self.programme.id,
                "farmer": self.farmer.id,
                "input_type": "SEED",
                "quantity": 10,
                "unit": "bags",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["input_type"], "SEED")

    def test_programme_capacity_service_rejects_over_allocation(self):
        self.programme.announced_hectares = 100
        self.programme.total_allocated_hectares = 80
        self.programme.save(update_fields=["announced_hectares", "total_allocated_hectares"])

        result = ProgrammeCapacityService.validate_allocation(self.programme, 30)

        self.assertFalse(result["valid"])
        self.assertIn("capacity", result["error"].lower())

    def test_programme_capacity_boundary_values(self):
        self.programme.announced_hectares = 20000
        self.programme.total_allocated_hectares = 0
        self.programme.save(update_fields=["announced_hectares", "total_allocated_hectares"])

        self.assertTrue(ProgrammeCapacityService.validate_allocation(self.programme, 19999)["valid"])
        self.assertTrue(ProgrammeCapacityService.validate_allocation(self.programme, 20000)["valid"])
        self.assertFalse(ProgrammeCapacityService.validate_allocation(self.programme, 20001)["valid"])

    def test_role_access_service_allows_super_admin(self):
        self.user.role = User.ROLE_SUPER_ADMIN
        self.user.save(update_fields=["role"])
        other_user = User.objects.create_user(
            email="other-programme@example.com",
            username="other-programme-user",
            password="StrongPass123!",
            role=User.ROLE_VIEWER,
        )

        self.assertTrue(RoleAccessService.can_access_user(self.user, other_user))

    def test_viewer_cannot_create_programme(self):
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])

        response = self.client.post(
            reverse("programme-list"),
            {"name": "Restricted", "code": "RESTRICTED", "announced_hectares": "20"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_viewer_can_read_seasons_and_programmes_but_not_create_seasons(self):
        from .models import Season

        season = Season.objects.create(
            name="Public Season 2026/27",
            start_date="2026-10-01",
            end_date="2027-09-30",
        )
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])

        seasons_response = self.client.get(reverse("season-list"))
        programmes_response = self.client.get(reverse("programme-list"))
        create_response = self.client.post(
            reverse("season-list"),
            {"name": "Restricted Season", "start_date": "2027-10-01", "end_date": "2028-09-30"},
            format="json",
        )

        self.assertEqual(seasons_response.status_code, 200)
        self.assertEqual(seasons_response.data["results"][0]["id"], season.pk)
        self.assertEqual(programmes_response.status_code, 200)
        self.assertEqual(create_response.status_code, 403)

    def test_golden_path_seed_command_is_repeatable(self):
        call_command("seed_golden_path", stdout=StringIO())
        call_command("seed_golden_path", stdout=StringIO())

        self.assertEqual(Programme.objects.filter(code="SGR-200HA-2026").count(), 1)
        seeded_programme = Programme.objects.get(code="SGR-200HA-2026")
        self.assertEqual(seeded_programme.announced_hectares, 20000)
        self.assertEqual(seeded_programme.institution, "ARDA")


class CropCatalogueSeedTests(TestCase):
    def test_seed_crop_catalogue_is_idempotent_and_populates_expected_data(self):
        call_command("seed_crop_catalogue", stdout=StringIO())
        call_command("seed_crop_catalogue", stdout=StringIO())

        sorghum = Crop.objects.get(name="Sorghum")
        maize = Crop.objects.get(name="Maize")
        wheat = Crop.objects.get(name="Wheat")

        self.assertEqual(Crop.objects.filter(name="Sorghum").count(), 1)
        self.assertEqual(Crop.objects.filter(name="Maize").count(), 1)
        self.assertEqual(Crop.objects.filter(name="Wheat").count(), 1)

        self.assertGreater(CropInputRequirement.objects.filter(crop=sorghum).count(), 0)
        self.assertGreater(CropInputRequirement.objects.filter(crop=maize).count(), 0)
        self.assertEqual(CropInputRequirement.objects.filter(crop=wheat).count(), 0)

        self.assertEqual(Crop.objects.filter(name__iexact="maize").count(), 1)
        self.assertEqual(Crop.objects.filter(name__iexact="sorghum").count(), 1)
        self.assertEqual(Crop.objects.filter(name__iexact="wheat").count(), 1)

        self.assertEqual(maize.total_input_cost_per_hectare, Decimal("626.5000"))
        self.assertEqual(sorghum.total_input_cost_per_hectare, Decimal("54097.1500"))

        self.assertFalse(CropInputRequirement.objects.filter(crop=sorghum, item_name="Discing").exists())
        self.assertFalse(CropInputRequirement.objects.filter(crop=sorghum, item_name="Planting").exists())
        self.assertFalse(
            CropInputRequirement.objects.filter(crop=sorghum, item_name="Spraying and fertilisation (7 times)").exists()
        )
        self.assertFalse(CropInputRequirement.objects.filter(crop=sorghum, item_name="Packaging").exists())
        self.assertFalse(CropInputRequirement.objects.filter(crop=sorghum, item_name="Transport").exists())

    def test_deactivated_requirement_excluded_from_crop_total(self):
        crop = Crop.objects.create(name="Test Crop", category=Crop.CATEGORY_SUMMER, active=True)
        active_row = CropInputRequirement.objects.create(
            crop=crop,
            group_name="Seed",
            item_name="A",
            rate_per_hectare="1.00",
            cost_per_hectare="10.00",
            include_in_input_cost=True,
            active=True,
        )
        CropInputRequirement.objects.create(
            crop=crop,
            group_name="Seed",
            item_name="B",
            rate_per_hectare="1.00",
            cost_per_hectare="15.00",
            include_in_input_cost=True,
            active=False,
        )
        self.assertEqual(crop.total_input_cost_per_hectare, 10)
        active_row.active = False
        active_row.save(update_fields=["active", "updated_at"])
        self.assertEqual(crop.total_input_cost_per_hectare, 0)

    def test_cost_per_hectare_is_computed_from_rate_and_unit_cost(self):
        crop = Crop.objects.create(name="Computation Crop", category=Crop.CATEGORY_SUMMER, active=True)
        row = CropInputRequirement.objects.create(
            crop=crop,
            group_name="Seed",
            item_name="Computed Row",
            rate_per_hectare="6.0000",
            unit="kg",
            cost_per_unit="23.0000",
            cost_per_hectare="0.0000",
            include_in_input_cost=True,
            active=True,
        )
        row.refresh_from_db()
        self.assertEqual(row.cost_per_hectare, Decimal("138.0000"))


class ProgrammeAndPriceCrudTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="catalogue@example.com", username="catalogue-user", password="StrongPass123!",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.viewer = User.objects.create_user(
            email="catalogue-view@example.com", username="catalogue-view", password="StrongPass123!",
            role=User.ROLE_VIEWER,
        )
        self.year = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status="ACTIVE")
        self.next_year = Season.objects.create(name="2027/2028", start_date="2027-10-01", end_date="2028-09-30", status="DRAFT")
        self.maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER, active=True)
        self.wheat = Crop.objects.create(name="Wheat", category=Crop.CATEGORY_WINTER, active=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_programme_crud_and_protected_delete(self):
        created = self.client.post(reverse("programme-list"), {
            "name": "Summer Maize", "code": "MAIZE-26", "season": self.year.pk, "crop": "Maize",
            "institution": "ARDA", "announced_hectares": "100.00", "status": "OPEN",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["season_name"], "2026/2027")
        programme_id = created.data["id"]

        updated = self.client.patch(reverse("programme-detail", args=[programme_id]), {"announced_hectares": "80.00"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["announced_hectares"], "80.00")

        duplicate = self.client.post(reverse("programme-list"), {
            "name": "Copy", "code": "maize-26", "season": self.year.pk, "crop": "Maize", "announced_hectares": "1.00",
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)

        hidden_year = self.client.post(reverse("programme-list"), {
            "name": "Later", "code": "LATER", "season": self.next_year.pk, "crop": "Maize", "announced_hectares": "1.00",
        }, format="json")
        self.assertEqual(hidden_year.status_code, 201, hidden_year.data)
        seasons = self.client.get(reverse("season-list"))
        selectable = [row["name"] for row in seasons.data["results"] if row["selectable"]]
        self.assertEqual(selectable, ["2026/2027"])

        from apps.arda_requests.models import ARDARequestBatch
        ARDARequestBatch.objects.create(request_number="SGR9000", programme_id=programme_id, season=self.year, crop="Maize", requested_hectares="10.00")
        blocked = self.client.delete(reverse("programme-detail", args=[programme_id]))
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("ARDA", str(blocked.data))

        self.client.force_authenticate(self.viewer)
        forbidden = self.client.delete(reverse("programme-detail", args=[programme_id]))
        self.assertEqual(forbidden.status_code, 403)

    def test_selling_price_is_per_agricultural_year_and_historical_debt_keeps_its_price(self):
        created = self.client.post(reverse("crop-selling-price-list"), {
            "crop": self.maize.pk, "season": self.year.pk, "price_per_tonne": "300.00", "currency": "USD",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        duplicate = self.client.post(reverse("crop-selling-price-list"), {
            "crop": self.maize.pk, "season": self.year.pk, "price_per_tonne": "320.00", "currency": "USD",
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)
        future = self.client.post(reverse("crop-selling-price-list"), {
            "crop": self.maize.pk, "season": self.next_year.pk, "price_per_tonne": "400.00", "currency": "USD",
        }, format="json")
        self.assertEqual(future.status_code, 400)

        from apps.programmes.services import CropPricingService
        self.assertEqual(CropPricingService.resolve_price_per_tonne(crop=self.maize, season=self.year), Decimal("300.00"))
        with self.assertRaises(ValueError):
            CropPricingService.resolve_price_per_tonne(crop=self.wheat, season=self.year)
        from .models import CropSellingPrice
        CropSellingPrice.objects.create(crop=self.maize, season=self.next_year, price_per_tonne="410.00", active=True)
        self.assertEqual(CropPricingService.resolve_price_per_tonne(crop=self.maize, season=self.next_year), Decimal("410.00"))

        from apps.recovery.models import InputDebt
        from apps.farmers.models import Farmer
        from apps.geography.models import District, Province, Ward
        province = Province.objects.create(name="Price Province", code="PP")
        district = District.objects.create(province=province, name="Price District")
        ward = Ward.objects.create(district=district, name="Ward P")
        farmer = Farmer.objects.create(first_name="Price", surname="Farmer", national_id="63-PRICE-1", phone_primary="0773000001", province=province, district=district, ward=ward)
        programme = Programme.objects.create(name="Price Programme", code="PRICE-PROG", season=self.year, crop="Maize", announced_hectares="10.00")
        debt = InputDebt.objects.create(
            farmer=farmer, programme=programme, crop="Maize", input_value="100.00", total_debt="100.00",
            selling_price_per_tonne="300.00", required_recovery_tonnes="1.00",
        )
        self.client.patch(reverse("crop-selling-price-detail", args=[created.data["id"]]), {"price_per_tonne": "350.00"}, format="json")
        debt.refresh_from_db()
        self.assertEqual(debt.selling_price_per_tonne, Decimal("300.00"))
        blocked = self.client.delete(reverse("crop-selling-price-detail", args=[created.data["id"]]))
        self.assertEqual(blocked.status_code, 400)

    def test_a_season_label_cannot_be_an_agricultural_year_selling_price(self):
        winter = Season.objects.create(name="winter", start_date="2026-04-16", end_date="2026-09-30", status=Season.STATUS_ACTIVE)
        rejected = self.client.post(reverse("crop-selling-price-list"), {
            "crop": self.maize.pk, "season": winter.pk, "price_per_tonne": "250.00", "currency": "USD",
        }, format="json")
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("agricultural year", str(rejected.data).lower())
