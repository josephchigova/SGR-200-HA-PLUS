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

    def test_subscription_tier_uses_registered_arable_hectares_at_200_boundary(self):
        self.farm.arable_hectares = "199.99"
        self.farm.save(update_fields=["arable_hectares"])
        under_threshold = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="199.99 season"),
            format="json",
        )
        self.assertEqual(under_threshold.status_code, 201, under_threshold.data)
        self.assertEqual(under_threshold.data["expected_amount"], "500.00")

        self.farm.arable_hectares = "200.00"
        self.farm.save(update_fields=["arable_hectares"])
        at_threshold = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="200.00 season"),
            format="json",
        )
        self.assertEqual(at_threshold.status_code, 201, at_threshold.data)
        self.assertEqual(at_threshold.data["expected_amount"], "1000.00")
        self.assertEqual(at_threshold.data["category"], "200HA+")

    def test_subscription_tier_for_350_registered_arable_hectares(self):
        self.farm.arable_hectares = "350.00"
        self.farm.save(update_fields=["arable_hectares"])

        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="350 hectare season"),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["expected_amount"], "1000.00")
        self.assertEqual(response.data["category"], "200HA+")

    def test_subscription_tier_sums_arable_area_across_farms(self):
        self.farm.arable_hectares = "200.00"
        self.farm.save(update_fields=["arable_hectares"])
        Farm.objects.create(
            farmer=self.farmer,
            farm_name="Second Tariro Farm",
            total_hectares="1.00",
            arable_hectares="1.00",
        )

        response = self.client.post(
            reverse("farmer-subscription-list"),
            self.payment_data("0.00", season="multi-farm"),
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["expected_amount"], "1000.00")
        self.assertEqual(response.data["category"], "200HA+")

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
