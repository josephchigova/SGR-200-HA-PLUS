from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farmers.models import Farm, Farmer
from apps.geography.models import District, Province, Ward
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()


class SubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="subscriptions@example.com",
            username="subscriptions-user",
            password="StrongPass123!",
            first_name="Ropafadzo",
            last_name="Moyo",
            role=User.ROLE_FINANCE_OFFICER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        province = Province.objects.create(name="Midlands", code="MD")
        district = District.objects.create(province=province, name="Gweru")
        ward = Ward.objects.create(district=district, name="Ward 1")
        self.farmer = Farmer.objects.create(
            first_name="Tariro",
            surname="Moyo",
            national_id="63-1234567-X-11",
            phone_primary="0771234567",
            province=province,
            district=district,
            ward=ward,
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer,
            farm_name="Tariro Farm",
            province=province,
            district=district,
            ward=ward,
            total_hectares="20.00",
            arable_hectares="10.00",
        )

    def payment_data(self, paid_amount, season="2026/2027", payment_date="2026-08-04"):
        return {
            "farmer": self.farmer.pk,
            "paid_amount": str(paid_amount),
            "season": season,
            "payment_date": payment_date,
        }

    def test_subscription_can_be_created(self):
        url = reverse("subscription-list")
        response = self.client.post(
            url,
            {
                "name": "Gold Membership",
                "code": "GOLD-2026",
                "description": "Premium annual membership",
                "fee": 150.00,
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "GOLD-2026")

    def test_farmer_subscription_calculates_unpaid_balance(self):
        response = self.client.post(
            reverse("farmer-subscription-list"),
            {**self.payment_data("0.00", payment_date=None), "expected_amount": "1.00", "category": "manual"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["expected_amount"], "500.00")
        self.assertEqual(response.data["outstanding_amount"], "500.00")
        self.assertEqual(response.data["payment_status"], "UNPAID")
        self.assertEqual(response.data["category"], "UNDER_200HA")
        self.assertIsNone(response.data["payment_date"])

    def test_farmer_subscription_calculates_partial_balance(self):
        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("40.00"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["outstanding_amount"], "460.00")
        self.assertEqual(response.data["payment_status"], "PARTIAL")

    def test_farmer_subscription_calculates_fully_paid_balance(self):
        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("500.00"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["outstanding_amount"], "0.00")
        self.assertEqual(response.data["payment_status"], "PAID")

    def test_farmer_subscription_rejects_overpayment(self):
        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("500.01"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_payment_requires_a_date(self):
        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("10.00", payment_date=None),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("payment_date", response.data)

    def allocate(self, season_name, **crops):
        """Give the farmer crop hectares for one agricultural year, as registration does."""
        from datetime import date

        from apps.farmers.models import RegistrationCropAllocation
        from apps.programmes.models import Crop, Season

        season, _ = Season.objects.get_or_create(name=season_name, defaults={"start_date": date(2026, 10, 1), "end_date": date(2027, 9, 30)})
        for name, hectares in crops.items():
            crop, _ = Crop.objects.get_or_create(name=name.title(), defaults={"category": Crop.CATEGORY_SUMMER})
            RegistrationCropAllocation.objects.create(farmer=self.farmer, crop=crop, season=season, hectares=hectares)

    def test_subscription_tier_follows_allocated_crop_hectares_at_200_boundary(self):
        self.allocate("199.99 season", maize="100.00", sorghum="99.99")
        under_threshold = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="199.99 season"),
            format="json",
        )
        self.assertEqual(under_threshold.status_code, 201, under_threshold.data)
        self.assertEqual(under_threshold.data["expected_amount"], "500.00")

        self.allocate("200.00 season", maize="100.00", sorghum="100.00")
        at_threshold = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="200.00 season"),
            format="json",
        )
        self.assertEqual(at_threshold.status_code, 201, at_threshold.data)
        self.assertEqual(at_threshold.data["expected_amount"], "1000.00")
        self.assertEqual(at_threshold.data["category"], "200HA+")

    def test_crops_not_farm_size_decide_the_tier(self):
        """50 ha of maize and 180 ha of sorghum is 230 ha: 200HA+, even on a 10 ha arable farm."""
        self.allocate("2026/2027", maize="50.00", sorghum="180.00")
        response = self.client.post(reverse("farmer-subscription-list"), self.payment_data("0.00"), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["expected_amount"], "1000.00")
        self.assertEqual(response.data["category"], "200HA+")
        listed = self.client.get(reverse("farmer-subscription-list"), {"season_name": "2026/2027"}).data["results"][0]
        self.assertEqual(listed["allocated_hectares"], "230.00")
        self.assertEqual(listed["category"], "200HA+")

        # A large farm with a small crop allocation pays the standard rate.
        self.farm.arable_hectares = "350.00"
        self.farm.save(update_fields=["arable_hectares"])
        self.allocate("2027/2028", maize="40.00")
        small = self.client.post(reverse("farmer-subscription-list"), self.payment_data("0.00", season="2027/2028"), format="json")
        self.assertEqual(small.data["expected_amount"], "500.00")
        self.assertEqual(small.data["category"], "UNDER_200HA")

    def test_each_season_subscription_follows_what_the_farmer_intends_to_plant(self):
        from datetime import date

        from apps.farmers.models import RegistrationCropAllocation
        from apps.programmes.models import Crop, Season

        season = Season.objects.create(name="Planting seasons", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30))
        maize = Crop.objects.create(name="Seasonal maize", category=Crop.CATEGORY_SUMMER)
        wheat = Crop.objects.create(name="Seasonal wheat", category=Crop.CATEGORY_WINTER)
        RegistrationCropAllocation.objects.create(farmer=self.farmer, crop=maize, season=season, hectares="220.00")
        winter_row = RegistrationCropAllocation.objects.create(farmer=self.farmer, crop=wheat, season=season, hectares="30.00")

        summer = self.client.get(reverse("farmer-subscription-list"), {"season_name": season.name, "crop_season": "SUMMER"}).data["results"][0]
        winter = self.client.get(reverse("farmer-subscription-list"), {"season_name": season.name, "crop_season": "WINTER"}).data["results"][0]
        self.assertEqual(summer["allocated_hectares"], "220.00")
        self.assertEqual(summer["expected_amount"], "1000.00")
        self.assertEqual(winter["allocated_hectares"], "30.00")
        self.assertEqual(winter["expected_amount"], "500.00")

        winter_row.hectares = "210.00"
        winter_row.save(update_fields=["hectares"])
        changed = self.client.get(reverse("farmer-subscription-list"), {"season_name": season.name, "crop_season": "WINTER"}).data["results"][0]
        unchanged = self.client.get(reverse("farmer-subscription-list"), {"season_name": season.name, "crop_season": "SUMMER"}).data["results"][0]
        self.assertEqual(changed["allocated_hectares"], "210.00")
        self.assertEqual(changed["expected_amount"], "1000.00")
        self.assertEqual(unchanged["expected_amount"], "1000.00")

    def test_production_records_are_used_when_there_is_no_allocation(self):
        from datetime import date

        from apps.production.models import FarmerProduction
        from apps.programmes.models import Season

        season = Season.objects.create(name="Production year", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30))
        FarmerProduction.objects.create(farmer=self.farmer, farm=self.farm, season=season, crop="Maize", contracted_hectares="120.00")
        FarmerProduction.objects.create(farmer=self.farmer, farm=self.farm, season=season, crop="Wheat", contracted_hectares="90.00")
        response = self.client.post(reverse("farmer-subscription-list"), self.payment_data("0.00", season="Production year"), format="json")
        self.assertEqual(response.data["expected_amount"], "1000.00")

    def test_reposting_payment_updates_farmer_season_aggregate(self):
        url = reverse("farmer-subscription-list")
        first = self.client.post(url, self.payment_data("40.00"), format="json")
        second = self.client.post(
            url,
            self.payment_data("75.00", payment_date="2026-08-11"),
            format="json",
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(FarmerSubscription.objects.filter(farmer=self.farmer, season="2026/2027").count(), 1)
        self.assertEqual(second.data["paid_amount"], "75.00")
        self.assertEqual(second.data["payment_date"], "2026-08-11")
        self.assertEqual(second.data["outstanding_amount"], "425.00")

    def test_viewer_cannot_change_subscription_payments(self):
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])
        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00"),
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_can_read_subscription_records(self):
        self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("40.00"),
            format="json",
        )
        self.user.role = User.ROLE_VIEWER
        self.user.save(update_fields=["role"])

        response = self.client.get(reverse("farmer-subscription-list"))
        self.assertEqual(response.status_code, 200)

    def test_season_status_includes_farmers_without_payment_records(self):
        response = self.client.get(reverse("farmer-subscription-list"), {"season": "2026/2027"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], None)
        self.assertEqual(response.data["results"][0]["payment_status"], "UNPAID")
        self.assertEqual(response.data["results"][0]["expected_amount"], "500.00")

    def test_global_season_summary_is_independent_of_search_and_page(self):
        paid_farmer = self.farmer
        partial_farmer = Farmer.objects.create(
            first_name="Rudo", surname="Paid", national_id="63-1234568-X-11", phone_primary="0771234568",
            province=self.farmer.province, district=self.farmer.district, ward=self.farmer.ward,
        )
        unpaid_farmer = Farmer.objects.create(
            first_name="Tendai", surname="Unpaid", national_id="63-1234569-X-11", phone_primary="0771234569",
            province=self.farmer.province, district=self.farmer.district, ward=self.farmer.ward,
        )
        for farmer in (partial_farmer, unpaid_farmer):
            Farm.objects.create(
                farmer=farmer, farm_name=f"{farmer.first_name} Farm", total_hectares="20.00", arable_hectares="10.00",
            )
        FarmerSubscription.objects.create(
            farmer=paid_farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="500.00",
            outstanding_amount="0.00", payment_status="PAID", season="2026/2027",
        )
        FarmerSubscription.objects.create(
            farmer=partial_farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="100.00",
            outstanding_amount="400.00", payment_status="PARTIAL", season="2026/2027",
        )

        list_url = reverse("farmer-subscription-list")
        page_one = self.client.get(list_url, {"season": "2026/2027", "page": 1, "page_size": 1})
        page_two = self.client.get(list_url, {"season": "2026/2027", "page": 2, "page_size": 1})
        summary_url = reverse("farmer-subscription-summary")
        first_summary = self.client.get(
            summary_url,
            {"season": "2026/2027", "page": 1, "page_size": 1, "search": "Paid"},
        )
        second_summary = self.client.get(
            summary_url,
            {"season": "2026/2027", "page": 2, "page_size": 1, "search": "Unpaid"},
        )

        self.assertEqual(page_one.status_code, 200, page_one.data)
        self.assertEqual(page_two.status_code, 200, page_two.data)
        self.assertEqual(page_one.data["count"], 3)
        self.assertEqual(page_two.data["count"], 3)
        expected_summary = {"total_farmers": 3, "paid": 1, "partial": 1, "unpaid": 1}
        self.assertEqual(first_summary.status_code, 200, first_summary.data)
        self.assertEqual(second_summary.status_code, 200, second_summary.data)
        self.assertEqual(first_summary.data, expected_summary)
        self.assertEqual(second_summary.data, expected_summary)

    def test_receipts_accumulate_and_do_not_record_the_unpaid_balance_as_cash(self):
        url = reverse("farmer-subscription-receive")
        first = self.client.post(url, {
            "farmer": self.farmer.pk, "season": "2026/2027", "amount": "200.00",
            "payment_date": "2026-11-02", "method": "CASH", "idempotency_key": "pay-1",
        }, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["expected_amount"], "500.00")
        self.assertEqual(first.data["paid_amount"], "200.00")
        self.assertEqual(first.data["outstanding_amount"], "300.00")
        self.assertEqual(first.data["payment_status"], "PARTIAL")
        repeat = self.client.post(url, {
            "farmer": self.farmer.pk, "season": "2026/2027", "amount": "200.00",
            "payment_date": "2026-11-02", "method": "CASH", "idempotency_key": "pay-1",
        }, format="json")
        self.assertEqual(repeat.status_code, 200, repeat.data)
        self.assertEqual(repeat.data["paid_amount"], "200.00")
        second = self.client.post(url, {
            "farmer": self.farmer.pk, "season": "2026/2027", "amount": "300.00",
            "payment_date": "2026-11-03", "method": "BANK", "idempotency_key": "pay-2",
        }, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["payment_status"], "PAID")
        self.assertEqual(second.data["outstanding_amount"], "0.00")
        overpaid = self.client.post(url, {
            "farmer": self.farmer.pk, "season": "2026/2027", "amount": "1.00",
            "payment_date": "2026-11-04", "method": "CASH", "idempotency_key": "pay-3",
        }, format="json")
        self.assertEqual(overpaid.status_code, 400)

        debtors = self.client.get(reverse("farmer-subscription-debtors"), {"season": "2026/2027"})
        self.assertEqual(debtors.status_code, 200, debtors.data)
        self.assertEqual(debtors.data["count"], 0)
        from apps.finance.models import JournalLine, LedgerAccount, RecognizedReceipt
        receipts = RecognizedReceipt.objects.filter(farmer=self.farmer)
        self.assertEqual(list(receipts.order_by("amount").values_list("amount", flat=True)), [Decimal("200.00"), Decimal("300.00")])
        revenue = LedgerAccount.objects.get(code="4000")
        credited = JournalLine.objects.filter(account=revenue, entry__status="POSTED").aggregate(total=Sum("credit"))["total"]
        self.assertEqual(credited, Decimal("500.00"))


class ClusterComplianceTests(TestCase):
    def test_compliance_is_amount_paid_over_amount_due(self):
        from apps.subscriptions.services import cluster_compliance

        # One 200 ha+ farmer paid in full (1,000) and one standard farmer paid nothing (500 due):
        # 1,000 of 1,500 is 66%, where an average of the two farmers' percentages would say 50%.
        self.assertEqual(cluster_compliance({1: 1000, 2: 500}, {1: 1000}), 66)
        # An overpayment by one farmer does not cover another farmer's arrears.
        self.assertEqual(cluster_compliance({1: 500, 2: 500}, {1: 900, 2: 0}), 50)
        self.assertEqual(cluster_compliance({}, {}), 0)
