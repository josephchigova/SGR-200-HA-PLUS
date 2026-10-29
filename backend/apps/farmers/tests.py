from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.geography.models import District, Province, Ward
from apps.programmes.models import Season

from apps.subscriptions.models import FarmerSubscription

from .models import Farm, Farmer
from .services import FarmerApprovalEligibilityService, FarmerRegistrationService

User = get_user_model()


class FarmerVerificationActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="verification@example.com",
            username="verification-user",
            password="StrongPass123!",
            first_name="Anna",
            last_name="Moyo",
            role=User.ROLE_VERIFICATION_OFFICER,
        )
        self.province = Province.objects.create(name="Mashonaland Central", code="MC")
        self.district = District.objects.create(province=self.province, name="Bindura")
        self.ward = Ward.objects.create(district=self.district, name="Ward 1")
        self.farmer = Farmer.objects.create(
            first_name="Tapiwa",
            surname="Moyo",
            national_id="63-1234567-X-45",
            phone_primary="0771000000",
            email="tapiwa@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer,
            farm_name="Moyo Demonstration Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="12.50",
            arable_hectares="10.00",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_farmer_verification_action_updates_status(self):
        url = reverse("farmer-verify", kwargs={"pk": self.farmer.pk})

        response = self.client.post(
            url,
            {"verification_status": "VERIFIED", "rejection_reason": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.verification_status, "VERIFIED")
        self.assertEqual(self.farmer.verified_by, self.user)
        self.assertIsNotNone(self.farmer.verification_date)
        self.farm.refresh_from_db()
        self.assertEqual(self.farm.verification_status, "VERIFIED")
        self.assertEqual(self.farm.verified_by, self.user)

    def test_farmer_registration_creates_submitted_farmer_and_farm(self):
        response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Kundai", "surname": "Moyo", "national_id": "63-3456789-X-01",
                "phone_primary": "0771234568", "province": self.province.pk, "district": self.district.pk,
                "ward": self.ward.pk, "farm_name": "Kundai Farm", "total_hectares": "6.25",
                "arable_hectares": "4.75", "irrigated_hectares": "2.25",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        registered = Farmer.objects.get(pk=response.data["id"])
        self.assertEqual(registered.verification_status, Farmer.STATUS_SUBMITTED)
        self.assertEqual(registered.farms.get().total_hectares, 6.25)
        self.assertEqual(registered.farms.get().arable_hectares, 4.75)
        self.assertEqual(registered.farms.get().irrigated_hectares, 2.25)

    def test_farmer_registration_rejects_arable_hectares_above_total(self):
        response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Area", "surname": "Farmer", "national_id": "63-8888888-X-01",
                "phone_primary": "0778888888", "province": self.province.pk, "district": self.district.pk,
                "ward": self.ward.pk, "total_hectares": "10.00", "arable_hectares": "10.01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("arable_hectares", response.data)

    def test_farmer_registration_rejects_irrigated_hectares_above_arable(self):
        response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Irrigated", "surname": "Farmer", "national_id": "63-8888888-X-02",
                "phone_primary": "0778888889", "province": self.province.pk, "district": self.district.pk,
                "ward": self.ward.pk, "total_hectares": "10.00", "arable_hectares": "5.00",
                "irrigated_hectares": "5.01",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("irrigated_hectares", response.data)

    def test_farm_crud_supports_annual_arable_hectare_update(self):
        create_response = self.client.post(
            reverse("farm-list"),
            {
                "farmer": self.farmer.pk, "farm_name": "Annual Farm", "province": self.province.pk,
                "district": self.district.pk, "ward": self.ward.pk, "total_hectares": "20.00",
                "arable_hectares": "12.00", "verification_status": "PENDING",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        farm_id = create_response.data["id"]

        update_response = self.client.patch(
            reverse("farm-detail", kwargs={"pk": farm_id}),
            {"arable_hectares": "15.00"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200, update_response.data)
        self.assertEqual(update_response.data["arable_hectares"], "15.00")

        delete_response = self.client.delete(reverse("farm-detail", kwargs={"pk": farm_id}))
        self.assertEqual(delete_response.status_code, 204)

    def test_farmer_registration_rejects_duplicate_national_id(self):
        response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Another", "surname": "Farmer", "national_id": self.farmer.national_id,
                "phone_primary": "0771234569", "province": self.province.pk, "district": self.district.pk,
                "ward": self.ward.pk, "total_hectares": "5.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("national_id", response.data)

    def test_farmer_registration_hectare_equivalence_partitions(self):
        base_payload = {
            "first_name": "Partition", "surname": "Farmer", "national_id": "63-4444444-X-01",
            "phone_primary": "0771234511", "province": self.province.pk, "district": self.district.pk,
            "ward": self.ward.pk,
        }
        for index, amount in enumerate(("0", "-1", "not-a-number")):
            with self.subTest(amount=amount):
                response = self.client.post(
                    reverse("farmer-list"),
                    {**base_payload, "national_id": f"63-4444444-X-{index + 1:02d}", "total_hectares": amount},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)

    def test_farmer_registration_rejects_invalid_optional_and_identity_fields(self):
        valid_payload = {
            "first_name": "Valid",
            "surname": "Farmer",
            "national_id": "63-1111111-X-01",
            "phone_primary": "0771234567",
            "province": self.province.pk,
            "district": self.district.pk,
            "ward": self.ward.pk,
            "total_hectares": "5.00",
        }
        invalid_cases = [
            ("first_name", "Farmer7"),
            ("middle_name", "Middle2"),
            ("national_id", "bad id!"),
            ("phone_primary", "077abc1234567"),
            ("phone_primary", "12345678"),
            ("phone_primary", "1234567890123"),
            ("phone_secondary", "077xyz4567"),
            ("phone_secondary", "12345678"),
            ("email", "not-an-email"),
            ("gender", "INVALID"),
            ("date_of_birth", "2027-01-01"),
            ("farm_name", "F" * 181),
            ("address", "A" * 501),
            ("total_hectares", "10000000000.00"),
        ]

        for index, (field, value) in enumerate(invalid_cases):
            with self.subTest(field=field):
                payload = {**valid_payload, "national_id": f"63-1111111-X-{index + 2:02d}", field: value}
                response = self.client.post(reverse("farmer-list"), payload, format="json")
                self.assertEqual(response.status_code, 400, response.data)

    def test_farmer_registration_rejects_district_from_another_province(self):
        other_province = Province.objects.create(name="Bulawayo", code="BU")
        other_district = District.objects.create(province=other_province, name="Bulawayo Central")
        response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Valid", "surname": "Farmer", "national_id": "63-5555555-X-77",
                "phone_primary": "0775555555", "province": self.province.pk,
                "district": other_district.pk, "ward": self.ward.pk, "total_hectares": "5.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("district", response.data)

    def test_farm_api_rejects_arable_hectares_above_total(self):
        response = self.client.post(
            reverse("farm-list"),
            {
                "farmer": self.farmer.pk, "farm_name": "Invalid Area Farm", "province": self.province.pk,
                "district": self.district.pk, "ward": self.ward.pk, "total_hectares": "10.00",
                "arable_hectares": "10.01", "irrigated_hectares": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("arable_hectares", response.data)

    def test_farmer_verification_requires_verification_role(self):
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])

        response = self.client.post(
            reverse("farmer-verify", kwargs={"pk": self.farmer.pk}),
            {"verification_status": "VERIFIED"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_farmer_list_is_scoped_to_district_coordinator(self):
        other_province = Province.objects.create(name="Matabeleland North", code="MN")
        other_district = District.objects.create(province=other_province, name="Lupane")
        other_ward = Ward.objects.create(district=other_district, name="Ward 4")
        Farmer.objects.create(
            first_name="Other",
            surname="District",
            national_id="63-9876543-Z-91",
            phone_primary="0771999000",
            province=other_province,
            district=other_district,
            ward=other_ward,
        )
        self.user.role = User.ROLE_DISTRICT_COORDINATOR
        self.user.district = self.district
        self.user.save(update_fields=["role", "district"])

        response = self.client.get(reverse("farmer-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], self.farmer.pk)
        other_farmer = Farmer.objects.exclude(pk=self.farmer.pk).get()
        detail_response = self.client.get(reverse("farmer-detail", kwargs={"pk": other_farmer.pk}))
        self.assertEqual(detail_response.status_code, 404)
        create_response = self.client.post(
            reverse("farmer-list"),
            {
                "first_name": "Outside", "surname": "District", "national_id": "63-9876543-Z-92",
                "phone_primary": "0771999001", "province": other_province.pk, "district": other_district.pk,
                "ward": other_ward.pk, "total_hectares": "5.00",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 400)

    def test_dashboard_summary_endpoint_returns_counts(self):
        url = reverse("dashboard-summary")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("registered_farmers", response.data)
        self.assertEqual(response.data["registered_farmers"], 1)
        self.assertEqual(response.data["verified_farmers"], 0)
        self.assertEqual(response.data["total_hectares"], 12.5)


class FarmerDomainServiceTests(TestCase):
    def setUp(self):
        self.province = Province.objects.create(name="Mashonaland West", code="MW")
        self.district = District.objects.create(province=self.province, name="Chinhoyi")
        self.ward = Ward.objects.create(district=self.district, name="Ward 2")

    def test_farmer_approval_requires_verified_status_and_active_subscription(self):
        farmer = Farmer.objects.create(
            first_name="Sarah",
            surname="Maposa",
            national_id="65-1234567-A-18",
            phone_primary="0771234567",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=Farmer.STATUS_DRAFT,
        )
        Farm.objects.create(
            farmer=farmer,
            farm_name="Maposa Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="25.00",
            verification_status="VERIFIED",
        )

        result = FarmerApprovalEligibilityService.evaluate(farmer)

        self.assertFalse(result["eligible"])
        self.assertIn("verified", " ".join(result["reasons"]).lower())

    def test_farmer_eligibility_decision_table(self):
        scenarios = [
            (Farmer.STATUS_VERIFIED, True, True, True),
            (Farmer.STATUS_VERIFIED, False, True, False),
            (Farmer.STATUS_SUBMITTED, True, True, False),
            (Farmer.STATUS_VERIFIED, True, False, False),
        ]
        for index, (verification_status, subscribed, farm_verified, expected) in enumerate(scenarios):
            with self.subTest(index=index):
                farmer = Farmer.objects.create(
                    first_name=f"Decision{index}", surname="Farmer", national_id=f"63-222222{index}-X-10",
                    phone_primary=f"07710000{index:02d}", province=self.province, district=self.district,
                    ward=self.ward, verification_status=verification_status,
                )
                Farm.objects.create(
                    farmer=farmer, farm_name=f"Decision Farm {index}", province=self.province, district=self.district,
                    ward=self.ward, total_hectares="10.00", arable_hectares="10.00",
                    verification_status="VERIFIED" if farm_verified else "PENDING",
                )
                if subscribed:
                    FarmerSubscription.objects.create(
                        farmer=farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="500.00",
                        outstanding_amount="0.00", payment_status="PAID", season=f"2026/{index}",
                    )

                result = FarmerApprovalEligibilityService.evaluate(farmer)

                self.assertEqual(result["eligible"], expected)

    def test_farmer_registration_service_rejects_duplicate_national_id(self):
        Farmer.objects.create(
            first_name="Philip",
            surname="Moyo",
            national_id="63-7654321-K-90",
            phone_primary="0777654321",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )

        payload = {
            "first_name": "Takudzwa",
            "surname": "Moyo",
            "national_id": "63-7654321-K-90",
            "phone_primary": "0777654322",
            "province": self.province.pk,
            "district": self.district.pk,
            "ward": self.ward.pk,
        }

        result = FarmerRegistrationService.validate(payload)

        self.assertFalse(result["valid"])
        self.assertIn("national_id", result["errors"])

    def test_farmer_registration_service_validates_province_district_relationship(self):
        other_province = Province.objects.create(name="Bulawayo", code="BU")
        payload = {
            "first_name": "Dumisani",
            "surname": "Ncube",
            "national_id": "63-5555555-X-77",
            "phone_primary": "0775555555",
            "province": self.province.pk,
            "district": District.objects.create(province=other_province, name="Bulawayo Central").pk,
            "ward": self.ward.pk,
        }

        result = FarmerRegistrationService.validate(payload)

        self.assertFalse(result["valid"])
        self.assertIn("district", result["errors"])


class FarmerEligibleEndpointSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="programme-officer@example.com",
            username="programme-officer",
            password="StrongPass123!",
            first_name="Programme",
            last_name="Officer",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.province = Province.objects.create(name="Mashonaland East", code="ME")
        self.district = District.objects.create(province=self.province, name="Marondera")
        self.ward = Ward.objects.create(district=self.district, name="Ward 8")
        self.season = Season.objects.create(
            name="2026/2027",
            start_date="2026-10-01",
            end_date="2027-09-30",
            status=Season.STATUS_ACTIVE,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self._counter = 0

    def _create_farmer(
        self,
        *,
        first_name,
        middle_name="",
        surname="Search",
        payment_status="PAID",
        verification_status=Farmer.STATUS_VERIFIED,
        is_active=True,
    ):
        self._counter += 1
        farmer = Farmer.objects.create(
            first_name=first_name,
            middle_name=middle_name,
            surname=surname,
            national_id=f"63-SEARCH-{self._counter:04d}-X-10",
            phone_primary=f"0774{self._counter:06d}",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=verification_status,
            is_active=is_active,
        )
        Farm.objects.create(
            farmer=farmer,
            farm_name=f"{first_name} Farm",
            province=self.province,
            district=self.district,
            ward=self.ward,
            total_hectares="20.00",
            arable_hectares="15.00",
            verification_status="VERIFIED",
        )
        paid_amount = "500.00" if payment_status == "PAID" else "250.00" if payment_status == "PARTIAL" else "0.00"
        outstanding_amount = "0.00" if payment_status == "PAID" else "250.00" if payment_status == "PARTIAL" else "500.00"
        FarmerSubscription.objects.create(
            farmer=farmer,
            category="UNDER_200HA",
            expected_amount="500.00",
            paid_amount=paid_amount,
            outstanding_amount=outstanding_amount,
            payment_status=payment_status,
            season=self.season.name,
        )
        return farmer

    def _eligible_search(self, search, page_size=25):
        response = self.client.get(
            reverse("farmer-eligible"),
            {
                "season": self.season.pk,
                "season_name": self.season.name,
                "search": search,
                "page_size": page_size,
            },
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_search_matches_name_case_insensitive_and_partial(self):
        target = self._create_farmer(first_name="Joseph", middle_name="Takunda", surname="Chigova")
        self._create_farmer(first_name="Other", surname="Farmer")

        name_rows = self._eligible_search("joseph")["results"]
        self.assertIn(target.pk, {row["id"] for row in name_rows})

        case_rows = self._eligible_search("JOSEPH")["results"]
        self.assertIn(target.pk, {row["id"] for row in case_rows})

        partial_rows = self._eligible_search("chig")["results"]
        self.assertIn(target.pk, {row["id"] for row in partial_rows})

        target_row = next(row for row in partial_rows if row["id"] == target.pk)
        self.assertEqual(target_row["full_name"], "Joseph Takunda Chigova")
        self.assertEqual(target_row["national_id"], target.national_id)
        self.assertEqual(target_row["membership_number"], target.membership_number)
        self.assertEqual(target_row["phone_primary"], target.phone_primary)
        self.assertEqual(target_row["district_name"], self.district.name)

    def test_search_matches_national_id(self):
        target = self._create_farmer(first_name="National", surname="ID")

        suffix = target.national_id[6:14]
        rows = self._eligible_search(suffix)["results"]
        self.assertIn(target.pk, {row["id"] for row in rows})

    def test_search_matches_membership_number(self):
        target = self._create_farmer(first_name="Membership", surname="Lookup")

        fragment = target.membership_number.split("-")[-1][-4:]
        rows = self._eligible_search(fragment)["results"]
        self.assertIn(target.pk, {row["id"] for row in rows})

    def test_search_matches_phone(self):
        target = self._create_farmer(first_name="Phone", surname="Lookup")

        rows = self._eligible_search(target.phone_primary[-6:])["results"]
        self.assertIn(target.pk, {row["id"] for row in rows})

    def test_search_excludes_unpaid_unverified_and_inactive_farmers(self):
        eligible = self._create_farmer(first_name="FilterFocus", surname="Eligible")
        self._create_farmer(first_name="FilterFocus", surname="Unpaid", payment_status="UNPAID")
        partial = self._create_farmer(first_name="FilterFocus", surname="Partial", payment_status="PARTIAL")
        self._create_farmer(first_name="FilterFocus", surname="Draft", verification_status=Farmer.STATUS_DRAFT)
        self._create_farmer(first_name="FilterFocus", surname="Inactive", is_active=False)

        rows = self._eligible_search("FilterFocus", page_size=50)["results"]
        self.assertEqual({row["id"] for row in rows}, {eligible.pk, partial.pk})

    def test_search_finds_match_that_is_beyond_first_unfiltered_page(self):
        target = self._create_farmer(first_name="NeedleFarmer", surname="ZuluNeedle")
        for index in range(30):
            self._create_farmer(first_name=f"Bulk{index:02d}", surname="AlphaEligible")

        first_page = self._eligible_search("", page_size=5)
        self.assertNotIn(target.pk, {row["id"] for row in first_page["results"]})

        searched = self._eligible_search("NeedleFarmer", page_size=5)
        self.assertIn(target.pk, {row["id"] for row in searched["results"]})

    def test_paid_and_partially_paid_spellings_are_eligible_and_balances_stay_unchanged(self):
        paid = self._create_farmer(first_name="Roster", surname="Paid", payment_status="Paid")
        partial = self._create_farmer(first_name="Roster", surname="Partial", payment_status="Partly Paid")
        explicit = self._create_farmer(first_name="Roster", surname="Explicit", payment_status="PARTIALLY_PAID")
        self._create_farmer(first_name="Roster", surname="Unpaid", payment_status="Unpaid")
        self._create_farmer(first_name="Roster", surname="Unverified", payment_status="Partly Paid", verification_status=Farmer.STATUS_DRAFT)
        for farmer, paid_amount, outstanding in (
            (paid, "500.00", "0.00"),
            (partial, "250.00", "250.00"),
            (explicit, "100.00", "400.00"),
        ):
            subscription = farmer.subscriptions.get()
            subscription.paid_amount = paid_amount
            subscription.outstanding_amount = outstanding
            subscription.save(update_fields=["paid_amount", "outstanding_amount"])

        rows = self._eligible_search("Roster", page_size=50)
        self.assertEqual(rows["count"], 3)
        by_id = {row["id"]: row for row in rows["results"]}
        self.assertEqual(set(by_id), {paid.pk, partial.pk, explicit.pk})
        self.assertEqual(by_id[paid.pk]["subscription_status"], "PAID")
        self.assertEqual(by_id[partial.pk]["subscription_status"], "PARTIALLY_PAID")
        self.assertEqual(by_id[explicit.pk]["subscription_status"], "PARTIALLY_PAID")
        self.assertEqual(paid.subscriptions.get().paid_amount, Decimal("500.00"))
        self.assertEqual(paid.subscriptions.get().outstanding_amount, Decimal("0.00"))
        self.assertEqual(partial.subscriptions.get().payment_status, "Partly Paid")
        self.assertEqual(partial.subscriptions.get().paid_amount, Decimal("250.00"))
        self.assertEqual(partial.subscriptions.get().outstanding_amount, Decimal("250.00"))
        self.assertEqual(explicit.subscriptions.get().payment_status, "PARTIALLY_PAID")
        self.assertEqual(explicit.subscriptions.get().outstanding_amount, Decimal("400.00"))


class FarmerPaginationAndVerificationQueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="pagination@example.com",
            username="pagination-user",
            password="StrongPass123!",
            first_name="Queue",
            last_name="Officer",
            role=User.ROLE_VERIFICATION_OFFICER,
        )
        self.province = Province.objects.create(name="Manicaland", code="MA")
        self.district = District.objects.create(province=self.province, name="Mutare")
        self.ward = Ward.objects.create(district=self.district, name="Ward 12")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self._counter = 0

    def _create_farmer(self, *, first_name, surname, verification_status=Farmer.STATUS_DRAFT):
        self._counter += 1
        return Farmer.objects.create(
            first_name=first_name,
            surname=surname,
            national_id=f"63-PAGE-{self._counter:04d}-X-10",
            phone_primary=f"0775{self._counter:06d}",
            province=self.province,
            district=self.district,
            ward=self.ward,
            verification_status=verification_status,
        )

    def test_farmers_list_paginates_first_middle_and_last_pages(self):
        for index in range(53):
            self._create_farmer(first_name=f"Paged{index:02d}", surname="Farmer")

        first_page = self.client.get(reverse("farmer-list"), {"page_size": 20, "page": 1})
        self.assertEqual(first_page.status_code, 200, first_page.data)
        self.assertEqual(first_page.data["count"], 53)
        self.assertEqual(len(first_page.data["results"]), 20)
        self.assertIsNone(first_page.data["previous"])
        self.assertIsNotNone(first_page.data["next"])

        middle_page = self.client.get(reverse("farmer-list"), {"page_size": 20, "page": 2})
        self.assertEqual(middle_page.status_code, 200, middle_page.data)
        self.assertEqual(middle_page.data["count"], 53)
        self.assertEqual(len(middle_page.data["results"]), 20)
        self.assertIsNotNone(middle_page.data["previous"])
        self.assertIsNotNone(middle_page.data["next"])

        last_page = self.client.get(reverse("farmer-list"), {"page_size": 20, "page": 3})
        self.assertEqual(last_page.status_code, 200, last_page.data)
        self.assertEqual(last_page.data["count"], 53)
        self.assertEqual(len(last_page.data["results"]), 13)
        self.assertIsNotNone(last_page.data["previous"])
        self.assertIsNone(last_page.data["next"])

    def test_farmers_search_is_filtered_before_pagination_and_count_is_total_filtered(self):
        for index in range(30):
            self._create_farmer(first_name=f"SearchMatch{index:02d}", surname="Target")
        for index in range(15):
            self._create_farmer(first_name=f"Other{index:02d}", surname="Record")

        response = self.client.get(reverse("farmer-list"), {"search": "searchmatch", "page_size": 10, "page": 2})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 30)
        self.assertEqual(len(response.data["results"]), 10)
        self.assertTrue(all("SearchMatch" in row["first_name"] for row in response.data["results"]))

    def test_verification_queue_filter_includes_draft_status(self):
        draft_farmer = self._create_farmer(first_name="DraftQueue", surname="Farmer", verification_status=Farmer.STATUS_DRAFT)
        for index in range(11):
            self._create_farmer(first_name=f"Submitted{index:02d}", surname="Queue", verification_status=Farmer.STATUS_SUBMITTED)
        for index in range(10):
            self._create_farmer(first_name=f"Review{index:02d}", surname="Queue", verification_status=Farmer.STATUS_UNDER_REVIEW)
        for index in range(5):
            self._create_farmer(first_name=f"Verified{index:02d}", surname="Queue", verification_status=Farmer.STATUS_VERIFIED)

        queue = self.client.get(
            reverse("farmer-list"),
            {
                "verification_status": "DRAFT,SUBMITTED,UNDER_REVIEW",
                "page_size": 10,
                "page": 1,
            },
        )
        self.assertEqual(queue.status_code, 200, queue.data)
        self.assertEqual(queue.data["count"], 22)
        for row in queue.data["results"]:
            self.assertIn(row["verification_status"], {Farmer.STATUS_DRAFT, Farmer.STATUS_SUBMITTED, Farmer.STATUS_UNDER_REVIEW})

        draft_search = self.client.get(
            reverse("farmer-list"),
            {
                "verification_status": "DRAFT,SUBMITTED,UNDER_REVIEW",
                "search": "DraftQueue",
                "page_size": 10,
            },
        )
        self.assertEqual(draft_search.status_code, 200, draft_search.data)
        self.assertEqual(draft_search.data["count"], 1)
        self.assertEqual(draft_search.data["results"][0]["id"], draft_farmer.pk)
        self.assertEqual(draft_search.data["results"][0]["verification_status"], Farmer.STATUS_DRAFT)

    def test_verification_action_transitions_draft_farmer(self):
        farmer = self._create_farmer(first_name="Transition", surname="Draft", verification_status=Farmer.STATUS_DRAFT)

        response = self.client.post(
            reverse("farmer-verify", kwargs={"pk": farmer.pk}),
            {"verification_status": Farmer.STATUS_UNDER_REVIEW},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        farmer.refresh_from_db()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_UNDER_REVIEW)


class FarmCoordinateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="coordinates@example.com", username="coordinates-user", password="StrongPass123!",
            role=User.ROLE_VERIFICATION_OFFICER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.province = Province.objects.create(name="Masvingo", code="MV-COORD")
        self.district = District.objects.create(province=self.province, name="Gutu")
        self.ward = Ward.objects.create(district=self.district, name="Ward 4")

    def _payload(self, **extra):
        payload = {
            "first_name": "Map", "surname": "Farmer", "national_id": "63-COORD-1",
            "phone_primary": "0773000001", "province": self.province.pk, "district": self.district.pk,
            "ward": self.ward.pk, "farm_name": "Mapped Farm", "total_hectares": "8.00",
            "arable_hectares": "6.00", "irrigated_hectares": "1.00",
        }
        payload.update(extra)
        return payload

    def test_registration_saves_optional_decimal_coordinates_and_updates_preserve_them(self):
        created = self.client.post(reverse("farmer-list"), self._payload(latitude="-17.825200", longitude="31.033500"), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        farm = Farm.objects.get(farmer_id=created.data["id"])
        self.assertEqual(farm.latitude, Decimal("-17.825200"))
        self.assertEqual(farm.longitude, Decimal("31.033500"))
        farm_response = self.client.get(reverse("farm-detail", args=[farm.pk]))
        self.assertEqual(farm_response.data["latitude"], "-17.825200")
        self.assertEqual(farm_response.data["longitude"], "31.033500")

        updated = self.client.patch(reverse("farmer-detail", args=[created.data["id"]]), {"phone_secondary": "0773000002"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        farm.refresh_from_db()
        self.assertEqual(farm.latitude, Decimal("-17.825200"))
        self.assertEqual(farm.longitude, Decimal("31.033500"))

        edited = self.client.patch(reverse("farm-detail", args=[farm.pk]), {"latitude": "90", "longitude": "180"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(edited.data["latitude"], "90.000000")
        self.assertEqual(edited.data["longitude"], "180.000000")

    def test_coordinate_ranges_and_pairs_are_validated(self):
        cases = [
            ({"latitude": "90", "longitude": "-180"}, 201),
            ({"latitude": "-90", "longitude": "180"}, 201),
            ({"latitude": "90.000001", "longitude": "1"}, 400),
            ({"latitude": "-90.000001", "longitude": "1"}, 400),
            ({"latitude": "1", "longitude": "180.000001"}, 400),
            ({"latitude": "1", "longitude": "-180.000001"}, 400),
            ({"latitude": "south", "longitude": "31"}, 400),
            ({"latitude": "-17.8"}, 400),
            ({"longitude": "31.1"}, 400),
            ({}, 201),
        ]
        for index, (coordinates, expected) in enumerate(cases, start=1):
            with self.subTest(coordinates=coordinates):
                response = self.client.post(
                    reverse("farmer-list"),
                    self._payload(national_id=f"63-COORD-{index:02d}", phone_primary=f"07730000{index:02d}", **coordinates),
                    format="json",
                )
                self.assertEqual(response.status_code, expected, response.data)
                if expected == 201 and not coordinates:
                    self.assertIsNone(Farm.objects.get(farmer_id=response.data["id"]).latitude)
                    self.assertIsNone(Farm.objects.get(farmer_id=response.data["id"]).longitude)
