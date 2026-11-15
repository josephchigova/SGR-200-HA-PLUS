from datetime import date, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Notification, ScheduledJobRun
from apps.clusters.models import Cluster
from apps.farmers.models import Farmer
from apps.geography.models import District, Province
from apps.programmes.models import Season
from apps.subscriptions.models import FarmerSubscription
from apps.subscriptions.reminders import check_subscription_deadlines, run_if_due

User = get_user_model()
DUE = date(2026, 12, 1)


@override_settings(SUBSCRIPTION_REMINDER_DAYS=7, SUBSCRIPTION_STILL_UNPAID_DAYS=30)
class SubscriptionReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        province = Province.objects.create(name="Midlands", code="MD")
        district = District.objects.create(province=province, name="Gweru")
        cls.season = Season.objects.create(name="2026/2027", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30), subscription_due_date=DUE)
        lead_member = Farmer.objects.create(first_name="Rudo", surname="Lead", national_id="63-1000000A10", province=province, district=district, is_lead=True, verification_status=Farmer.STATUS_VERIFIED)
        cls.cluster = Cluster.objects.create(name="RUDO LEAD", province=province, district=district, lead_member=lead_member)
        lead_member.cluster = cls.cluster
        lead_member.save(update_fields=["cluster"])
        cls.unpaid = Farmer.objects.create(first_name="Tendai", surname="Moyo", national_id="63-2000000B20", province=province, district=district, cluster=cls.cluster, verification_status=Farmer.STATUS_VERIFIED)
        cls.partial = Farmer.objects.create(first_name="Chipo", surname="Dube", national_id="63-3000000C30", province=province, district=district, cluster=cls.cluster, verification_status=Farmer.STATUS_VERIFIED)
        cls.paid = Farmer.objects.create(first_name="Farai", surname="Ncube", national_id="63-4000000D40", province=province, district=district, cluster=cls.cluster, verification_status=Farmer.STATUS_VERIFIED)
        cls.draft = Farmer.objects.create(first_name="Nyasha", surname="Sibanda", national_id="63-5000000E50", province=province, district=district, cluster=cls.cluster, verification_status=Farmer.STATUS_DRAFT)
        FarmerSubscription.objects.create(farmer=cls.partial, season="2026/2027", paid_amount=200, payment_status="PARTIAL")
        FarmerSubscription.objects.create(farmer=cls.paid, season="2026/2027", paid_amount=500, payment_status="PAID")
        # The lead farmer is a member too; their own subscription is paid here.
        FarmerSubscription.objects.create(farmer=lead_member, season="2026/2027", paid_amount=500, payment_status="PAID")
        cls.finance = User.objects.create_user(email="finance@example.com", username="finance", password="Str0ng!Passw0rd", role=User.ROLE_FINANCE_OFFICER)
        cls.lead = User.objects.create_user(email="lead@example.com", username="lead", password="Str0ng!Passw0rd", role=User.ROLE_LEAD_FARMER, assigned_cluster=cls.cluster, farmer=lead_member)
        cls.cluster.lead_farmer = cls.lead
        cls.cluster.save(update_fields=["lead_farmer"])

    def notices(self, user, kind=None):
        rows = Notification.objects.filter(recipient=user)
        return rows.filter(kind=kind) if kind else rows

    def test_upcoming_due_and_overdue_are_detected_for_unpaid_farmers_only(self):
        self.assertEqual(check_subscription_deadlines(today=DUE - timedelta(days=10))["notifications_created"], 0)
        check_subscription_deadlines(today=DUE - timedelta(days=3))
        upcoming = self.notices(self.finance, Notification.KIND_SUBSCRIPTION_UPCOMING)
        self.assertEqual(sorted(notice.farmer_id for notice in upcoming), sorted([self.unpaid.pk, self.partial.pk]))
        check_subscription_deadlines(today=DUE)
        self.assertEqual(self.notices(self.finance, Notification.KIND_SUBSCRIPTION_DUE).count(), 2)
        check_subscription_deadlines(today=DUE + timedelta(days=1))
        overdue = self.notices(self.finance, Notification.KIND_SUBSCRIPTION_OVERDUE).get(farmer=self.unpaid)
        self.assertEqual((overdue.days_overdue, overdue.payment_status, str(overdue.amount_due)), (1, "UNPAID", "500.00"))
        self.assertIn("1 day overdue", overdue.body)
        partial = self.notices(self.finance, Notification.KIND_SUBSCRIPTION_OVERDUE).get(farmer=self.partial)
        self.assertEqual((partial.payment_status, str(partial.amount_due)), ("PARTIAL", "300.00"))

    def test_running_again_creates_no_duplicates(self):
        first = check_subscription_deadlines(today=DUE + timedelta(days=2))
        again = check_subscription_deadlines(today=DUE + timedelta(days=2))
        later = check_subscription_deadlines(today=DUE + timedelta(days=9))
        self.assertGreater(first["notifications_created"], 0)
        self.assertEqual((again["notifications_created"], later["notifications_created"]), (0, 0))
        self.assertEqual(self.notices(self.finance, Notification.KIND_SUBSCRIPTION_OVERDUE).count(), 2)

    def test_still_unpaid_reminders_repeat_once_per_period(self):
        check_subscription_deadlines(today=DUE + timedelta(days=30))
        check_subscription_deadlines(today=DUE + timedelta(days=45))
        check_subscription_deadlines(today=DUE + timedelta(days=60))
        still = self.notices(self.finance, Notification.KIND_SUBSCRIPTION_STILL_UNPAID).filter(farmer=self.unpaid)
        self.assertEqual(sorted(still.values_list("days_overdue", flat=True)), [30, 60])

    def test_lead_farmer_gets_status_but_never_amounts(self):
        check_subscription_deadlines(today=DUE + timedelta(days=1))
        lead_notices = self.notices(self.lead)
        self.assertEqual(lead_notices.count(), 2)
        self.assertTrue(all(notice.amount_due is None for notice in lead_notices))
        self.assertNotIn("USD", " ".join(lead_notices.values_list("body", flat=True)))
        client = APIClient()
        client.force_authenticate(self.lead)
        overdue = client.get("/api/farmer-subscriptions/overdue/", {"season_name": "2026/2027"}).json()
        self.assertTrue(all("amount_due" not in row for row in overdue["results"]))

    def test_bell_shows_notices_tracks_delivery_and_reading(self):
        check_subscription_deadlines(today=DUE + timedelta(days=1))
        client = APIClient()
        client.force_authenticate(self.finance)
        bell = client.get("/api/notifications/").json()
        self.assertEqual(bell["unread_notices"], 2)
        self.assertTrue(all(notice["delivered_at"] for notice in self.notices(self.finance).values("delivered_at")))
        first = bell["notices"][0]["id"]
        self.assertEqual(client.post("/api/notifications/inbox/", {"ids": [first]}, format="json").json()["marked_read"], 1)
        self.assertEqual(client.get("/api/notifications/inbox/", {"unread": "1"}).json()["count"], 1)
        self.assertEqual(client.post("/api/notifications/inbox/", {}, format="json").json()["marked_read"], 1)
        self.assertIsNotNone(Notification.objects.get(pk=first).read_at)

    def test_scheduled_command_and_backstop(self):
        out = StringIO()
        call_command("send_subscription_reminders", "--date", (DUE + timedelta(days=1)).isoformat(), stdout=out)
        self.assertIn("notifications created", out.getvalue())
        self.assertIsNotNone(ScheduledJobRun.objects.get(name="subscription-reminders").last_finished_at)
        # The job just ran, so the backstop does not run it again.
        self.assertIsNone(run_if_due())

    def test_finance_sets_the_due_date_and_lead_farmers_cannot(self):
        finance = APIClient()
        finance.force_authenticate(self.finance)
        saved = finance.post("/api/farmer-subscriptions/deadline/", {"season": "2026/2027", "due_date": "2027-01-15"}, format="json")
        self.assertEqual(saved.json()["due_date"], "2027-01-15")
        lead = APIClient()
        lead.force_authenticate(self.lead)
        self.assertEqual(lead.post("/api/farmer-subscriptions/deadline/", {"season": "2026/2027", "due_date": "2027-02-01"}, format="json").status_code, 403)
