from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.clusters.models import Cluster
from apps.farmers.models import Farmer
from apps.geography.models import District, Province
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()
PASSWORD = "StrongPass123!"


def make_user(email, role, **extra):
    return User.objects.create_user(email=email, username=email, password=PASSWORD, role=role, **extra)


class AccessControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Mashonaland West", code="MW")
        cls.district = District.objects.create(province=cls.province, name="Chinhoyi")
        cls.mine = Cluster.objects.create(name="Chinhoyi Cluster", province=cls.province)
        cls.other = Cluster.objects.create(name="Gweru Cluster", province=cls.province)
        cls.my_farmer = Farmer.objects.create(first_name="Rudo", surname="Chikafu", national_id="11-111111-A-11", province=cls.province, district=cls.district, cluster=cls.mine)
        cls.other_farmer = Farmer.objects.create(first_name="Tatenda", surname="Moyo", national_id="22-222222-B-22", province=cls.province, district=cls.district, cluster=cls.other)
        cls.unassigned_farmer = Farmer.objects.create(first_name="No", surname="Cluster", national_id="33-333333-C-33", province=cls.province, district=cls.district)
        for farmer in (cls.my_farmer, cls.other_farmer):
            FarmerSubscription.objects.create(farmer=farmer, season="2026/2027", expected_amount=1000, paid_amount=0, payment_status="UNPAID")
        cls.admin = make_user("admin@example.com", User.ROLE_SUPER_ADMIN)
        cls.executive = make_user("exec@example.com", User.ROLE_SGR_EXECUTIVE)
        cls.auditor = make_user("auditor@example.com", User.ROLE_AUDITOR)
        cls.finance = make_user("finance@example.com", User.ROLE_FINANCE_OFFICER)
        cls.lead = make_user("lead@example.com", User.ROLE_LEAD_FARMER, assigned_cluster=cls.mine)
        cls.lead_without_cluster = make_user("lead2@example.com", User.ROLE_LEAD_FARMER)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def rows(self, response):
        data = response.json()
        return data["results"] if isinstance(data, dict) and "results" in data else data

    # Lead farmer record visibility -------------------------------------------------

    def test_lead_farmer_only_sees_farmers_in_the_assigned_cluster(self):
        response = self.client_for(self.lead).get("/api/farmers/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in self.rows(response)], [self.my_farmer.id])

    def test_lead_farmer_cannot_open_another_clusters_farmer(self):
        client = self.client_for(self.lead)
        self.assertEqual(client.get(f"/api/farmers/{self.other_farmer.id}/").status_code, 404)
        self.assertEqual(client.patch(f"/api/farmers/{self.other_farmer.id}/", {"surname": "Changed"}, format="json").status_code, 404)

    def test_lead_farmer_without_a_cluster_sees_no_farmers(self):
        response = self.client_for(self.lead_without_cluster).get("/api/farmers/")
        self.assertEqual(self.rows(response), [])

    def test_lead_farmer_subscriptions_and_search_are_scoped(self):
        client = self.client_for(self.lead)
        listed = self.rows(client.get("/api/farmer-subscriptions/?season_name=2026/2027"))
        self.assertTrue(listed)
        self.assertNotIn(self.other_farmer.id, [row.get("farmer") for row in listed])
        other_subscription = FarmerSubscription.objects.get(farmer=self.other_farmer)
        self.assertEqual(client.get(f"/api/farmer-subscriptions/{other_subscription.id}/").status_code, 404)
        found = client.get("/api/search/?q=Moyo").json()["results"]
        self.assertEqual(found, [])

    def test_lead_farmer_cannot_verify_delete_or_take_payment(self):
        client = self.client_for(self.lead)
        self.assertEqual(client.post(f"/api/farmers/{self.my_farmer.id}/verify/", {"verification_status": "VERIFIED"}, format="json").status_code, 403)
        self.assertEqual(client.delete(f"/api/farmers/{self.my_farmer.id}/").status_code, 403)
        self.assertEqual(client.post("/api/farmer-subscriptions/receive/", {"farmer": self.my_farmer.id, "amount": "10"}, format="json").status_code, 403)

    def test_lead_farmer_is_refused_finance_admin_and_organisation_data(self):
        client = self.client_for(self.lead)
        for url in [
            "/api/expenses/", "/api/receipts/", "/api/journals/", "/api/payroll/", "/api/assets/",
            "/api/finance-reports/dashboard/?start=2026-01-01&end=2026-12-31", "/api/expense-schedule/?start=2026-01-01&end=2026-12-31",
            "/api/source-finance-cash-flow/", "/api/auth/users/", "/api/auth/roles/", "/api/audit-logs/",
            "/api/arda-request-batches/", "/api/report-templates/",
        ]:
            with self.subTest(url=url):
                self.assertIn(client.get(url).status_code, (403, 404), url)

    def test_lead_farmer_reports_exclude_finance_and_other_clusters(self):
        client = self.client_for(self.lead)
        catalogue = client.get("/api/reports/catalogue/").json()
        categories = {report["category"] for report in catalogue["reports"]}
        self.assertNotIn("finance", categories)
        self.assertNotIn("users", categories)
        preview = client.get("/api/reports/farmers-register/preview/").json()
        surnames = {row["surname"] for row in preview["rows"]}
        self.assertEqual(surnames, {"Chikafu"})
        finance_code = next(report["code"] for report in self.client_for(self.admin).get("/api/reports/catalogue/").json()["reports"] if report["category"] == "finance")
        self.assertEqual(client.get(f"/api/reports/{finance_code}/preview/").status_code, 403)
        self.assertEqual(client.get(f"/api/reports/{finance_code}/export/?file_format=csv").status_code, 403)

    def test_lead_farmer_dashboard_counts_only_the_cluster(self):
        summary = self.client_for(self.lead).get("/api/farmers/dashboard-summary/?season_name=2026/2027").json()
        self.assertEqual(summary["registered_farmers"], 1)
        self.assertEqual(summary["scope"]["kind"], "cluster")
        self.assertNotIn("expenses_by_category", summary["charts"])
        admin_summary = self.client_for(self.admin).get("/api/farmers/dashboard-summary/?season_name=2026/2027").json()
        self.assertEqual(admin_summary["registered_farmers"], 3)
        self.assertIn("expenses_by_category", admin_summary["charts"])

    def test_lead_farmer_can_register_a_farmer_only_in_the_assigned_cluster(self):
        client = self.client_for(self.lead)
        payload = {"first_name": "New", "surname": "Farmer", "national_id": "44-444444-D-44", "province": self.province.id, "district": self.district.id}
        refused = client.post("/api/farmers/", {**payload, "cluster": self.other.id}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(Farmer.objects.filter(national_id="44-444444-D-44").exists())

    # Role restrictions -------------------------------------------------------------

    def test_auditor_is_read_only_everywhere(self):
        client = self.client_for(self.auditor)
        self.assertEqual(client.get("/api/farmers/").status_code, 200)
        self.assertEqual(client.get("/api/audit-logs/").status_code, 200)
        self.assertEqual(client.post("/api/farmers/", {"first_name": "A", "surname": "B"}, format="json").status_code, 403)
        self.assertEqual(client.post("/api/expense-schedule/", {"description": "x", "amount": "1"}, format="json").status_code, 403)
        self.assertEqual(client.post("/api/auth/users/", {"email": "x@example.com"}, format="json").status_code, 403)

    def test_only_the_super_administrator_manages_accounts(self):
        payload = {"email": "new@example.com", "first_name": "New", "last_name": "User", "role": User.ROLE_FINANCE_OFFICER, "password": "AnotherStrong123!"}
        for user in (self.executive, self.finance, self.lead):
            self.assertEqual(self.client_for(user).post("/api/auth/users/", payload, format="json").status_code, 403)
        created = self.client_for(self.admin).post("/api/auth/users/", payload, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertNotIn("password", created.json())
        self.assertTrue(User.objects.get(email="new@example.com").must_change_password)

    def test_scoped_roles_need_their_assignment_and_admins_cannot_lock_themselves_out(self):
        client = self.client_for(self.admin)
        missing = client.post("/api/auth/users/", {"email": "l@example.com", "role": User.ROLE_LEAD_FARMER, "password": "AnotherStrong123!"}, format="json")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("assigned_cluster", missing.json())
        self.assertEqual(client.patch(f"/api/auth/users/{self.admin.id}/", {"is_active": False}, format="json").status_code, 400)
        self.assertEqual(client.delete(f"/api/auth/users/{self.finance.id}/").status_code, 405)

    def test_profile_carries_the_permission_matrix(self):
        lead = self.client_for(self.lead).get("/api/auth/me/").json()
        self.assertTrue(lead["permissions"]["farmers"]["create"])
        self.assertFalse(lead["permissions"]["farmers"]["delete"])
        self.assertFalse(lead["permissions"]["finance"]["view"])
        self.assertFalse(lead["permissions"]["users"]["view"])
        self.assertEqual(lead["cluster_name"], "Chinhoyi Cluster")
        admin = self.client_for(self.admin).get("/api/auth/me/").json()
        self.assertTrue(all(admin["permissions"][module]["view"] for module in admin["permissions"]))
        self.assertEqual(self.client_for(self.lead).patch("/api/auth/me/", {"role": "super_admin", "first_name": "Lead"}, format="json").status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.role, User.ROLE_LEAD_FARMER)

    # Accounts, passwords and audit ---------------------------------------------------

    def test_self_registration_waits_for_administrator_approval(self):
        client = APIClient()
        response = client.post("/api/auth/register/", {"email": "wait@example.com", "username": "wait", "first_name": "W", "last_name": "A", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(User.objects.get(email="wait@example.com").is_active)
        self.assertEqual(client.post("/api/auth/login/", {"email": "wait@example.com", "password": PASSWORD}, format="json").status_code, 401)
        notes = self.client_for(self.admin).get("/api/notifications/").json()
        self.assertIn("accounts", [item["key"] for item in notes["items"]])

    def test_changes_and_sign_ins_are_written_to_the_audit_log(self):
        APIClient().post("/api/auth/login/", {"email": "admin@example.com", "password": PASSWORD}, format="json")
        APIClient().post("/api/auth/login/", {"email": "admin@example.com", "password": "wrong"}, format="json")
        client = self.client_for(self.admin)
        client.patch(f"/api/farmers/{self.my_farmer.id}/", {"phone_primary": "0771234567"}, format="json")
        actions = list(AuditLog.objects.values_list("action", flat=True))
        self.assertIn(AuditLog.ACTION_LOGIN, actions)
        self.assertIn(AuditLog.ACTION_LOGIN_FAILED, actions)
        entry = AuditLog.objects.filter(action=AuditLog.ACTION_UPDATE, module="farmers").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user_email, "admin@example.com")
        self.assertEqual(entry.changed_fields, ["phone_primary"])
        self.assertEqual(client.delete(f"/api/audit-logs/{entry.id}/").status_code, 404)

    def test_change_password_and_administrator_reset(self):
        client = self.client_for(self.finance)
        self.assertEqual(client.post("/api/auth/change-password/", {"current_password": "nope", "new_password": "BrandNewPass456!"}, format="json").status_code, 400)
        self.assertEqual(client.post("/api/auth/change-password/", {"current_password": PASSWORD, "new_password": "BrandNewPass456!"}, format="json").status_code, 200)
        self.finance.refresh_from_db()
        self.assertTrue(self.finance.check_password("BrandNewPass456!"))
        reset = self.client_for(self.admin).post(f"/api/auth/users/{self.finance.id}/reset-password/")
        self.assertEqual(reset.status_code, 200)
        self.finance.refresh_from_db()
        self.assertTrue(self.finance.check_password(reset.json()["temporary_password"]))
        self.assertTrue(self.finance.must_change_password)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_forgotten_password_link_resets_the_password_once(self):
        client = APIClient()
        self.assertEqual(client.post("/api/auth/password-reset/", {"email": "nobody@example.com"}, format="json").status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        client.post("/api/auth/password-reset/", {"email": "finance@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        link = next(line for line in mail.outbox[0].body.splitlines() if "reset-password?" in line)
        query = dict(part.split("=", 1) for part in link.split("?", 1)[1].split("&"))
        bad = client.post("/api/auth/password-reset/confirm/", {"uid": query["uid"], "token": "wrong", "new_password": "ResetPass789!"}, format="json")
        self.assertEqual(bad.status_code, 400)
        good = client.post("/api/auth/password-reset/confirm/", {**query, "new_password": "ResetPass789!"}, format="json")
        self.assertEqual(good.status_code, 200)
        again = client.post("/api/auth/password-reset/confirm/", {**query, "new_password": "OtherPass789!"}, format="json")
        self.assertEqual(again.status_code, 400)
