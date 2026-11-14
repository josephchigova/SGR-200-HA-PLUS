from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.clusters.models import Cluster
from apps.farmers.models import Farmer, FarmerChangeRequest, FarmerReviewEvent
from apps.geography.models import District, Province, Ward

User = get_user_model()
PASSWORD = "StrongPass123!"


class LeadFarmerClusterTests(TestCase):
    """The administrator manages lead farmers. Each lead farmer is one cluster."""

    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Mashonaland East", code="ME")
        cls.other_province = Province.objects.create(name="Midlands", code="MD")
        cls.district = District.objects.create(province=cls.province, name="Marondera")
        cls.other_district = District.objects.create(province=cls.other_province, name="Gweru")
        cls.ward = Ward.objects.create(district=cls.district, name="Ward 4")
        cls.ward_two = Ward.objects.create(district=cls.district, name="Ward 7")
        cls.other_ward = Ward.objects.create(district=cls.other_district, name="Ward 1")
        cls.admin = User.objects.create_user(email="admin@example.com", username="admin@example.com", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)
        cls.executive = User.objects.create_user(email="exec@example.com", username="exec@example.com", password=PASSWORD, role=User.ROLE_SGR_EXECUTIVE)
        cls.auditor = User.objects.create_user(email="auditor@example.com", username="auditor@example.com", password=PASSWORD, role=User.ROLE_AUDITOR)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def register_lead(self, first="John", surname="Moyo", national_id="63-1111111A11", email="john@example.com", ward=None, client=None):
        response = (client or self.client_for(self.admin)).post("/api/lead-farmers/", {
            "first_name": first, "surname": surname, "national_id": national_id, "phone_primary": "0771111111",
            "email": email, "province": self.province.id, "district": self.district.id, "ward": (ward or self.ward).id,
            "password": "AnotherStrong456!",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def lead_user(self, lead):
        return User.objects.get(pk=lead["account"]["id"])

    def register_farmer(self, lead_user, national_id, first="Farai", surname="Dube", **changes):
        payload = {
            "first_name": first, "surname": surname, "national_id": national_id, "phone_primary": "0772222222",
            "farm_name": "Home", "province": self.province.id, "district": self.district.id, "ward": self.ward.id,
            "total_hectares": "250", "arable_hectares": "220", "irrigated_hectares": "20", "as_draft": True,
        }
        payload.update(changes)
        return self.client_for(lead_user).post("/api/farmers/", payload, format="json")

    # 1, 2, 4, 5: one step creates the record, the cluster named after the lead, and the login.
    def test_administrator_registers_a_lead_farmer_with_location_and_login(self):
        lead = self.register_lead()
        self.assertEqual(lead["cluster"], "JOHN MOYO")
        self.assertEqual(lead["lead_farmer"], "JOHN MOYO")
        self.assertEqual((lead["province"]["id"], lead["district"]["id"], lead["ward"]["id"]), (self.province.id, self.district.id, self.ward.id))
        self.assertEqual(lead["status"], "ACTIVE")
        account = self.lead_user(lead)
        self.assertEqual(account.role, User.ROLE_LEAD_FARMER)
        self.assertTrue(account.must_change_password)
        self.assertTrue(account.check_password("AnotherStrong456!"))
        cluster = Cluster.objects.get(pk=lead["cluster_id"])
        self.assertEqual(cluster.lead_farmer, account)
        self.assertEqual(account.assigned_cluster, cluster)
        farmer = Farmer.objects.get(pk=lead["farmer_id"])
        self.assertTrue(farmer.is_lead)
        self.assertEqual(farmer.cluster, cluster)
        self.assertEqual(Cluster.objects.count(), 1)

    def test_independent_clusters_cannot_be_created_or_edited(self):
        lead = self.register_lead()
        client = self.client_for(self.admin)
        self.assertEqual(client.post("/api/clusters/", {"name": "Free cluster", "province": self.province.id}, format="json").status_code, 405)
        self.assertEqual(client.patch(f"/api/clusters/{lead['cluster_id']}/", {"name": "Renamed"}, format="json").status_code, 405)
        self.assertEqual(client.get("/api/clusters/").status_code, 200)

    def test_cluster_name_follows_the_lead_farmers_name(self):
        lead = self.register_lead()
        updated = self.client_for(self.admin).patch(f"/api/lead-farmers/{lead['cluster_id']}/", {"surname": "Moyo-Ncube"}, format="json")
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["cluster"], "JOHN MOYO-NCUBE")
        self.assertEqual(self.lead_user(lead).last_name, "MOYO-NCUBE")

    def test_two_lead_farmers_with_the_same_name_get_distinct_clusters(self):
        first = self.register_lead()
        second = self.register_lead(national_id="63-2222222B22", email="john2@example.com")
        self.assertNotEqual(first["cluster"], second["cluster"])
        self.assertTrue(second["cluster"].startswith("JOHN MOYO ("))

    # 3: several lead farmers in one province, each with their own farmers.
    def test_several_lead_farmers_share_a_province_without_sharing_farmers(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com", ward=self.ward_two)
        peter = self.register_lead("Peter", "Ncube", "63-4444444D44", "peter@example.com")
        self.assertEqual(self.register_farmer(self.lead_user(john), "63-5555555E55", "Ann", "Banda").status_code, 201)
        self.assertEqual(self.register_farmer(self.lead_user(mary), "63-6666666F66", "Ben", "Sithole").status_code, 201)
        john_sees = self.client_for(self.lead_user(john)).get("/api/farmers/").json()["results"]
        names = {row["full_name"] for row in john_sees}
        self.assertIn("ANN BANDA", names)
        self.assertNotIn("BEN SITHOLE", names)
        listed = self.client_for(self.admin).get("/api/lead-farmers/").json()
        sizes = {row["lead_farmer"]: row["farmers"] for row in listed["results"]}
        self.assertEqual(sizes, {"JOHN MOYO": 1, "MARY DUBE": 1, "PETER NCUBE": 0})
        self.assertEqual(listed["overview"]["lead_farmers"], 3)
        self.assertEqual(listed["overview"]["farmers"], 2)
        self.assertEqual(listed["overview"]["smallest_cluster"]["farmers"], 0)
        self.assertEqual(peter["farmers"], 0)

    # 6, 7: the server decides ownership from the signed-in lead farmer.
    def test_registered_farmer_belongs_to_the_signed_in_lead_whatever_the_request_says(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com")
        response = self.register_farmer(self.lead_user(john), "63-5555555E55", cluster=mary["cluster_id"])
        self.assertEqual(response.status_code, 201, response.content)
        farmer = Farmer.objects.get(pk=response.json()["id"])
        self.assertEqual(farmer.cluster_id, john["cluster_id"])
        self.assertEqual(farmer.registered_by, self.lead_user(john))
        moved = self.client_for(self.lead_user(john)).patch(f"/api/farmers/{farmer.id}/", {"cluster": mary["cluster_id"]}, format="json")
        self.assertEqual(moved.status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.cluster_id, john["cluster_id"])

    # 8, 9: a second lead farmer cannot register the same person.
    def test_second_lead_farmer_is_told_who_already_registered_the_farmer(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com")
        self.assertEqual(self.register_farmer(self.lead_user(john), "63-5555555E55").status_code, 201)
        for variant in ("63-5555555E55", "63-5555555e55"):
            refused = self.register_farmer(self.lead_user(mary), variant)
            self.assertEqual(refused.status_code, 400)
            self.assertEqual(
                refused.json()["national_id"],
                ["This farmer is already registered under Lead Farmer JOHN MOYO. Please contact the Administrator if reassignment is required."],
            )
        self.assertEqual(Farmer.objects.filter(national_id__iexact="63-5555555E55").count(), 1)

    def test_a_lead_farmer_cannot_be_registered_twice(self):
        self.register_lead()
        response = self.client_for(self.admin).post("/api/lead-farmers/", {
            "first_name": "John", "surname": "Moyo", "national_id": "63-1111111a11", "phone_primary": "0771111111",
            "email": "other@example.com", "province": self.province.id, "district": self.district.id, "ward": self.ward.id,
            "password": "AnotherStrong456!",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already registered as a lead farmer", response.json()["national_id"][0])

    # 10: no access to another lead farmer's farmers through the API.
    def test_lead_farmer_cannot_reach_another_clusters_records(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com")
        response = self.register_farmer(self.lead_user(john), "63-5555555E55")
        farmer_id = response.json()["id"]
        mary_client = self.client_for(self.lead_user(mary))
        self.assertEqual(mary_client.get(f"/api/farmers/{farmer_id}/").status_code, 404)
        self.assertEqual(mary_client.patch(f"/api/farmers/{farmer_id}/", {"phone_primary": "0779999999"}, format="json").status_code, 404)
        self.assertEqual(mary_client.post(f"/api/farmers/{farmer_id}/submit/").status_code, 404)
        self.assertEqual(mary_client.get(f"/api/farmers/{farmer_id}/history/").status_code, 404)
        self.assertEqual(mary_client.get("/api/lead-farmers/").status_code, 403)
        self.assertEqual(mary_client.get(f"/api/lead-farmers/{john['cluster_id']}/").status_code, 403)
        self.assertEqual(mary_client.post("/api/lead-farmers/reassign/", {"farmer": farmer_id, "cluster": mary["cluster_id"], "reason": "x"}, format="json").status_code, 403)
        overview = mary_client.get("/api/farmers/cluster-overview/").json()
        self.assertEqual(overview["counts"]["total"], 0)

    def test_lead_farmers_and_administrators_have_the_right_registration_rights(self):
        john = self.register_lead()
        self.assertEqual(self.client_for(self.admin).post("/api/farmers/", {"first_name": "A", "surname": "B", "national_id": "63-7777777G77"}, format="json").status_code, 403)
        self.assertEqual(self.register_lead(client=self.client_for(self.executive), first="Exec", surname="Made", national_id="63-8888888H88", email="e@example.com")["status"], "ACTIVE")
        lead_client = self.client_for(self.lead_user(john))
        self.assertEqual(lead_client.post("/api/lead-farmers/", {"first_name": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.auditor).get("/api/lead-farmers/").status_code, 200)
        self.assertEqual(self.client_for(self.auditor).post("/api/lead-farmers/", {}, format="json").status_code, 403)

    def test_team_page_cannot_create_or_rewire_lead_farmer_logins(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com")
        client = self.client_for(self.admin)
        created = client.post("/api/auth/users/", {"email": "x@example.com", "first_name": "X", "last_name": "Y", "role": User.ROLE_LEAD_FARMER, "password": "AnotherStrong456!"}, format="json")
        self.assertEqual(created.status_code, 400)
        self.assertIn("Lead farmers page", created.json()["role"][0])
        account = self.lead_user(john)
        client.patch(f"/api/auth/users/{account.id}/", {"assigned_cluster": mary["cluster_id"]}, format="json")
        account.refresh_from_db()
        self.assertEqual(account.assigned_cluster_id, john["cluster_id"])
        self.assertEqual(client.patch(f"/api/auth/users/{account.id}/", {"role": User.ROLE_VIEWER}, format="json").status_code, 400)

    # 11, 12: the administrator sees every cluster and its counts.
    def test_administrator_sees_cluster_detail_with_counts_and_crops(self):
        john = self.register_lead()
        account = self.lead_user(john)
        first = self.register_farmer(account, "63-5555555E55", "Ann", "Banda").json()["id"]
        self.register_farmer(account, "63-6666666F66", "Ben", "Sithole")
        Farmer.objects.filter(pk=first).update(verification_status=Farmer.STATUS_REJECTED)
        detail = self.client_for(self.admin).get(f"/api/lead-farmers/{john['cluster_id']}/").json()
        self.assertEqual((detail["farmers"], detail["rejected"], detail["incomplete"]), (2, 1, 1))
        self.assertEqual(len(detail["overview"]["farmers"]), 2)
        self.assertNotIn(john["farmer_id"], [row["id"] for row in detail["overview"]["farmers"]])
        self.assertTrue(all(row["registration_date"] for row in detail["overview"]["farmers"]))
        self.assertIn("crops", detail["overview"]["farmers"][0])

    # 15: reassignment is the administrator's, needs a reason, and is recorded.
    def test_reassignment_is_audited_and_moves_the_farms(self):
        john = self.register_lead()
        mary = self.register_lead("Mary", "Dube", "63-3333333C33", "mary@example.com")
        farmer_id = self.register_farmer(self.lead_user(john), "63-5555555E55").json()["id"]
        client = self.client_for(self.admin)
        self.assertEqual(client.post("/api/lead-farmers/reassign/", {"farmer": farmer_id, "cluster": mary["cluster_id"]}, format="json").status_code, 400)
        moved = client.post("/api/lead-farmers/reassign/", {"farmer": farmer_id, "cluster": mary["cluster_id"], "reason": "Farmer moved closer to Mary"}, format="json")
        self.assertEqual(moved.status_code, 200, moved.content)
        farmer = Farmer.objects.get(pk=farmer_id)
        self.assertEqual(farmer.cluster_id, mary["cluster_id"])
        self.assertEqual(set(farmer.farms.values_list("cluster_id", flat=True)), {mary["cluster_id"]})
        event = farmer.review_events.get(action=FarmerReviewEvent.REASSIGNED)
        self.assertIn("From JOHN MOYO to MARY DUBE", event.remarks)
        self.assertEqual(event.actor, self.admin)
        self.assertTrue(AuditLog.objects.filter(module="lead-farmers", summary__contains="Reassigned").exists())
        refused = client.post("/api/lead-farmers/reassign/", {"farmer": john["farmer_id"], "cluster": mary["cluster_id"], "reason": "x"}, format="json")
        self.assertEqual(refused.status_code, 400)

    def test_deactivating_a_lead_keeps_the_cluster_and_its_farmers(self):
        john = self.register_lead()
        self.register_farmer(self.lead_user(john), "63-5555555E55")
        result = self.client_for(self.admin).post(f"/api/lead-farmers/{john['cluster_id']}/status/", {"is_active": False}, format="json").json()
        self.assertEqual(result["status"], "INACTIVE")
        self.assertEqual(result["farmers"], 1)
        self.assertFalse(self.lead_user(john).is_active)
        self.assertTrue(Cluster.objects.get(pk=john["cluster_id"]).active)

    def test_a_lead_registered_without_a_login_can_be_given_one(self):
        farmer = Farmer.objects.create(first_name="OLD", surname="LEAD", national_id="63-9999999Z99", province=self.province)
        from apps.farmers.services import open_lead_cluster

        cluster = open_lead_cluster(farmer)
        client = self.client_for(self.admin)
        listed = {row["cluster_id"]: row for row in client.get("/api/lead-farmers/").json()["results"]}
        self.assertEqual(listed[cluster.pk]["status"], "NO_LOGIN")
        created = client.post(f"/api/lead-farmers/{cluster.pk}/login/", {"email": "old@example.com", "password": "AnotherStrong456!"}, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["status"], "ACTIVE")
        self.assertEqual(client.post(f"/api/lead-farmers/{cluster.pk}/login/", {"email": "old2@example.com", "password": "AnotherStrong456!"}, format="json").status_code, 400)

    def test_ward_is_a_typed_number_matched_or_added_in_the_district(self):
        john = self.register_lead()
        account = self.lead_user(john)
        for bad in ("abc", "0", "1000", "-3"):
            refused = self.register_farmer(account, "63-5555555E55", ward=None, ward_number=bad)
            self.assertEqual(refused.status_code, 400, bad)
            self.assertIn("ward_number", refused.json())
        matched = self.register_farmer(account, "63-5555555E55", ward=None, ward_number="7")
        self.assertEqual(matched.status_code, 201, matched.content)
        self.assertEqual(Farmer.objects.get(pk=matched.json()["id"]).ward, self.ward_two)
        added = self.register_farmer(account, "63-6666666F66", "Ben", "Sithole", ward=None, ward_number="287")
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(Farmer.objects.get(pk=added.json()["id"]).ward.name, "Ward 287")
        self.assertEqual(Ward.objects.filter(district=self.district, name="Ward 287").count(), 1)
        missing = self.register_farmer(account, "63-7777777G77", ward=None)
        self.assertEqual(missing.status_code, 400)
        self.assertIn("ward_number", missing.json())

    def test_lead_farmer_form_takes_a_ward_number(self):
        response = self.client_for(self.admin).post("/api/lead-farmers/", {
            "first_name": "Mary", "surname": "Dube", "national_id": "63-3333333C33", "phone_primary": "0773333333",
            "email": "mary@example.com", "province": self.province.id, "district": self.district.id, "ward_number": "152",
            "password": "AnotherStrong456!",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["ward"]["name"], "Ward 152")
        moved = self.client_for(self.admin).patch(f"/api/lead-farmers/{response.json()['cluster_id']}/", {"ward_number": "4"}, format="json")
        self.assertEqual(moved.json()["ward"]["id"], self.ward.id)

    # 14: older records are reported, never assigned at random.
    def test_reconciliation_reports_unowned_records_and_changes_nothing_without_apply(self):
        legacy = Cluster.objects.create(name="Old Cluster", province=self.province)
        Farmer.objects.create(first_name="LEGACY", surname="ONE", national_id="LEG-1", province=self.province, cluster=legacy)
        Farmer.objects.create(first_name="LEGACY", surname="TWO", national_id="LEG-2", province=self.province)
        john = self.register_lead()
        Cluster.objects.filter(pk=john["cluster_id"]).update(name="Wrong name")
        out = StringIO()
        call_command("reconcile_lead_clusters", stdout=out)
        report = out.getvalue()
        self.assertIn("Clusters without a lead farmer: 1", report)
        self.assertIn("Farmers without a lead farmer: 2", report)
        self.assertEqual(Cluster.objects.get(pk=john["cluster_id"]).name, "Wrong name")
        call_command("reconcile_lead_clusters", "--apply", stdout=StringIO())
        self.assertEqual(Cluster.objects.get(pk=john["cluster_id"]).name, "JOHN MOYO")
        self.assertIsNone(Farmer.objects.get(national_id="LEG-2").cluster_id)
        self.assertEqual(Farmer.objects.get(national_id="LEG-1").cluster_id, legacy.pk)


class SuperuserAndAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Harare Metropolitan", code="HRE")
        cls.district = District.objects.create(province=cls.province, name="Chitungwiza")
        cls.ward = Ward.objects.create(district=cls.district, name="Manjonjori")
        cls.root = User.objects.create_superuser(email="root@example.com", username="root", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def payload(self, **changes):
        data = {
            "first_name": "Tendai", "surname": "Mharapara", "national_id": "63-2468246T24", "phone_primary": "0772468246",
            "email": "tendai@example.com", "farm_name": "Mharapara Estate", "province": self.province.id, "district": self.district.id,
            "ward": self.ward.id, "total_hectares": "200", "arable_hectares": "100", "irrigated_hectares": "100",
            "irrigation_type": "SPRINKLER", "latitude": "-17.835622", "longitude": "31.021466", "as_draft": True, "as_lead": True,
        }
        data.update(changes)
        return data

    def test_a_superuser_is_offered_lead_registration_not_ordinary_registration(self):
        permissions = self.client_for(self.root).get("/api/auth/me/").json()["permissions"]
        self.assertFalse(permissions["farmers"]["create"])
        self.assertTrue(permissions["lead_registration"]["create"])
        self.assertTrue(permissions["users"]["delete"])

    def test_a_superuser_registers_a_lead_farmer_with_farm_and_login_in_one_save(self):
        client = self.client_for(self.root)
        created = client.post("/api/farmers/", self.payload(login_password="Lead-Start-2026!"), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        farmer = Farmer.objects.get(pk=created.json()["id"])
        self.assertTrue(farmer.is_lead)
        self.assertEqual(farmer.cluster.name, "TENDAI MHARAPARA")
        self.assertEqual(farmer.farms.get().total_hectares, 200)
        account = User.objects.get(email="tendai@example.com")
        self.assertEqual((account.role, account.farmer_id, account.assigned_cluster_id), (User.ROLE_LEAD_FARMER, farmer.id, farmer.cluster_id))
        self.assertTrue(account.check_password("Lead-Start-2026!"))
        self.assertEqual(farmer.cluster.lead_farmer, account)
        self.assertNotIn("login_password", created.json())

    def test_lead_login_problems_stop_the_whole_registration(self):
        User.objects.create_user(email="tendai@example.com", username="taken", password=PASSWORD)
        client = self.client_for(self.root)
        taken = client.post("/api/farmers/", self.payload(login_password="Lead-Start-2026!"), format="json")
        self.assertEqual(taken.status_code, 400)
        self.assertIn("email", taken.json())
        weak = client.post("/api/farmers/", self.payload(email="other@example.com", login_password="password"), format="json")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("login_password", weak.json())
        self.assertFalse(Farmer.objects.exists())
        self.assertFalse(Cluster.objects.exists())

    def test_accounts_can_be_deleted_without_losing_records(self):
        client = self.client_for(self.root)
        client.post("/api/farmers/", self.payload(login_password="Lead-Start-2026!"), format="json")
        account = User.objects.get(email="tendai@example.com")
        farmer = Farmer.objects.get(national_id="63-2468246T24")
        deleted = client.delete(f"/api/auth/users/{account.id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(User.objects.filter(pk=account.pk).exists())
        farmer.refresh_from_db()
        self.assertIsNone(farmer.cluster.lead_farmer)
        self.assertTrue(Farmer.objects.filter(pk=farmer.pk).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_DELETE, summary__contains="tendai@example.com").exists())
        listed = {row["cluster_id"]: row["status"] for row in client.get("/api/lead-farmers/").json()["results"]}
        self.assertEqual(listed[farmer.cluster_id], "NO_LOGIN")

    def test_deletion_guards(self):
        client = self.client_for(self.root)
        self.assertEqual(client.delete(f"/api/auth/users/{self.root.id}/").status_code, 400)
        only = User.objects.create_user(email="sa@example.com", username="sa", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)
        other = User.objects.create_user(email="sa2@example.com", username="sa2", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)
        self.assertEqual(self.client_for(other).delete(f"/api/auth/users/{only.id}/").status_code, 204)
        User.objects.filter(pk=self.root.pk).update(is_active=False)
        refused = self.client_for(other).delete(f"/api/auth/users/{self.root.id}/")
        self.assertEqual(refused.status_code, 204)
        lone = User.objects.create_user(email="lone@example.com", username="lone", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)
        executive = User.objects.create_user(email="ex@example.com", username="ex", password=PASSWORD, role=User.ROLE_SGR_EXECUTIVE)
        self.assertEqual(self.client_for(executive).delete(f"/api/auth/users/{lone.id}/").status_code, 403)
        self.assertEqual(self.client_for(lone).delete(f"/api/auth/users/{other.id}/").status_code, 204)
        last = self.client_for(User.objects.create_superuser(email="su@example.com", username="su", password=PASSWORD, role=User.ROLE_VIEWER)).delete(f"/api/auth/users/{lone.id}/")
        self.assertEqual(last.status_code, 400)
        self.assertIn("only active Super Administrator", last.json()["detail"])


class AdminRegisteredLeadTests(TestCase):
    """A lead farmer an administrator registers is complete. Their later edits go to administration."""

    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Manicaland", code="MN")
        cls.district = District.objects.create(province=cls.province, name="Chipinge")
        cls.admin = User.objects.create_user(email="admin@example.com", username="admin", password=PASSWORD, role=User.ROLE_SUPER_ADMIN)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def register_lead_with_wizard(self):
        admin = self.client_for(self.admin)
        created = admin.post("/api/farmers/", {
            "first_name": "Takunda", "middle_name": "Joshua", "surname": "Mutenje", "national_id": "64-9873737E34",
            "phone_primary": "077717272773"[:12], "email": "takunda@example.com", "farm_name": "Mutenje Farm",
            "province": self.province.id, "district": self.district.id, "ward_number": "12",
            "total_hectares": "200", "arable_hectares": "100", "irrigated_hectares": "100", "irrigation_type": "SPRINKLER",
            "as_draft": True, "as_lead": True, "login_password": "Lead-Start-2026!",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        farmer = Farmer.objects.get(pk=created.json()["id"])
        finished = admin.post(f"/api/farmers/{farmer.id}/submit/")
        self.assertEqual(finished.status_code, 200, finished.content)
        farmer.refresh_from_db()
        return farmer, User.objects.get(email="takunda@example.com")

    def test_an_administrator_registration_is_complete_when_the_farm_is_saved(self):
        """No KYC files and no final click: saving the farmer and farm completes it."""
        from datetime import date

        from apps.production.models import FarmerProduction
        from apps.programmes.models import Crop, Season

        admin = self.client_for(self.admin)
        created = admin.post("/api/farmers/", {
            "first_name": "Rudo", "surname": "Moyo", "national_id": "63-2353535E34", "phone_primary": "0771111222",
            "email": "rudo@example.com", "farm_name": "Moyo Farm", "province": self.province.id, "district": self.district.id,
            "ward_number": "4", "total_hectares": "100", "arable_hectares": "100", "irrigated_hectares": "0",
            "as_draft": True, "as_lead": True, "login_password": "Lead-Start-2026!",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["verification_status"], Farmer.STATUS_VERIFIED)
        self.assertFalse(created.json()["kyc_upload_required"])
        farmer = Farmer.objects.get(pk=created.json()["id"])
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_ACTIVE)
        self.assertFalse(admin.get("/api/farmers/", {"verification_status": "DRAFT"}).json()["results"])

        # Crops can still be added afterwards, and reach production straight away.
        season = Season.objects.create(name="2026/2027 Summer", start_date=date(2026, 5, 1), end_date=date(2026, 10, 31), status=Season.STATUS_ACTIVE)
        crop = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
        crops = admin.patch(f"/api/farmers/{farmer.id}/", {"crop_allocations": [{"crop": crop.id, "season": season.id, "hectares": "40"}]}, format="json")
        self.assertEqual(crops.status_code, 200, crops.content)
        self.assertTrue(FarmerProduction.objects.filter(farmer=farmer, crop="Maize").exists())

        # Finishing the wizard afterwards only confirms it.
        finished = admin.post(f"/api/farmers/{farmer.id}/submit/")
        self.assertEqual(finished.status_code, 200, finished.content)
        self.assertEqual(finished.json()["verification_status"], Farmer.STATUS_VERIFIED)
        self.assertEqual(farmer.review_events.filter(action=FarmerReviewEvent.APPROVED).count(), 1)

    def test_open_administrator_records_are_repaired(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        lead_user = User.objects.create_user(email="lead2@example.com", username="lead2", password=PASSWORD, role=User.ROLE_LEAD_FARMER)
        def make(national_id, registrar, with_farm=True, status=Farmer.STATUS_DRAFT):
            farmer = Farmer.objects.create(
                first_name="A", surname=national_id[-3:], national_id=national_id, province=self.province, district=self.district,
                verification_status=status, registered_by=registrar,
            )
            if with_farm:
                farmer.farms.create(farm_name="F", total_hectares=10, arable_hectares=10, province=self.province, district=self.district)
            return farmer

        stuck = make("63-1111111A11", self.admin)
        captured_by_lead = make("63-2222222B22", lead_user)
        no_farm = make("63-3333333C33", self.admin, with_farm=False)
        rejected = make("63-4444444D44", self.admin, status=Farmer.STATUS_REJECTED)
        import_module("apps.farmers.migrations.0012_complete_open_admin_registrations").complete(global_apps, None)
        states = {f.pk: f.verification_status for f in Farmer.objects.filter(pk__in=[stuck.pk, captured_by_lead.pk, no_farm.pk, rejected.pk])}
        self.assertEqual(states[stuck.pk], Farmer.STATUS_VERIFIED)
        self.assertEqual(states[captured_by_lead.pk], Farmer.STATUS_DRAFT)
        self.assertEqual(states[no_farm.pk], Farmer.STATUS_DRAFT)
        self.assertEqual(states[rejected.pk], Farmer.STATUS_REJECTED)

    def test_finishing_an_administrator_registration_completes_it(self):
        farmer, _ = self.register_lead_with_wizard()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_VERIFIED)
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_ACTIVE)
        self.assertEqual(farmer.verified_by, self.admin)
        self.assertEqual(farmer.farms.get().verification_status, "VERIFIED")
        self.assertTrue(farmer.review_events.filter(action=FarmerReviewEvent.APPROVED).exists())

    def test_one_step_lead_registration_is_complete_too(self):
        response = self.client_for(self.admin).post("/api/lead-farmers/", {
            "first_name": "Mary", "surname": "Dube", "national_id": "63-3333333C33", "phone_primary": "0773333333",
            "email": "mary@example.com", "province": self.province.id, "district": self.district.id, "ward_number": "3",
            "password": "AnotherStrong456!",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["own_record_status"], Farmer.STATUS_VERIFIED)

    def test_lead_farmer_cannot_edit_the_record_directly(self):
        farmer, lead = self.register_lead_with_wizard()
        client = self.client_for(lead)
        self.assertEqual(client.patch(f"/api/farmers/{farmer.id}/", {"phone_primary": "0779999999"}, format="json").status_code, 400)
        # The registration is already complete. Submitting again confirms it and does not ask for KYC files.
        confirmed = client.post(f"/api/farmers/{farmer.id}/submit/")
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.assertEqual(confirmed.json()["verification_status"], Farmer.STATUS_VERIFIED)
        self.assertFalse(confirmed.json()["kyc_upload_required"])
        farm = farmer.farms.get()
        self.assertEqual(client.patch(f"/api/farms/{farm.id}/", {"total_hectares": "300"}, format="json").status_code, 400)

    def test_change_request_waits_for_approval_then_applies(self):
        farmer, lead = self.register_lead_with_wizard()
        client = self.client_for(lead)
        nothing = client.post(f"/api/farmers/{farmer.id}/change-requests/", {"phone_primary": farmer.phone_primary}, format="json")
        self.assertEqual(nothing.status_code, 400)
        bad = client.post(f"/api/farmers/{farmer.id}/change-requests/", {"arable_hectares": "500"}, format="json")
        self.assertEqual(bad.status_code, 400)
        sent = client.post(f"/api/farmers/{farmer.id}/change-requests/", {
            "phone_primary": "0779999999", "surname": "mutenje-moyo", "total_hectares": "250", "ward_number": 14, "note": "New phone",
        }, format="json")
        self.assertEqual(sent.status_code, 201, sent.content)
        farmer.refresh_from_db()
        self.assertEqual(farmer.phone_primary, "077717272773"[:12])
        rows = {row["field"]: (row["old"], row["new"]) for row in sent.json()["rows"]}
        self.assertEqual(rows["surname"], ("MUTENJE", "MUTENJE-MOYO"))
        self.assertEqual(rows["ward_number"], ("12", "14"))
        again = client.post(f"/api/farmers/{farmer.id}/change-requests/", {"phone_primary": "0778888888"}, format="json")
        self.assertEqual(again.status_code, 201)
        self.assertEqual(FarmerChangeRequest.objects.filter(farmer=farmer, status="PENDING").count(), 1)
        change_id = again.json()["id"]
        self.assertEqual(client.post(f"/api/farmer-change-requests/{change_id}/approve/").status_code, 403)
        admin = self.client_for(self.admin)
        queue = admin.get("/api/farmer-change-requests/?status=PENDING").json()["results"]
        self.assertEqual([row["id"] for row in queue], [change_id])
        notices = [item["key"] for item in admin.get("/api/notifications/").json()["items"]]
        self.assertIn("changes", notices)
        approved = admin.post(f"/api/farmer-change-requests/{change_id}/approve/")
        self.assertEqual(approved.status_code, 200, approved.content)
        farmer.refresh_from_db()
        self.assertEqual(farmer.phone_primary, "0778888888")
        self.assertEqual(farmer.verification_status, Farmer.STATUS_VERIFIED)
        self.assertEqual(admin.post(f"/api/farmer-change-requests/{change_id}/approve/").status_code, 400)

    def test_approved_names_and_land_reach_the_cluster_and_farm(self):
        farmer, lead = self.register_lead_with_wizard()
        change = self.client_for(lead).post(f"/api/farmers/{farmer.id}/change-requests/", {
            "surname": "Moyo", "total_hectares": "260", "arable_hectares": "150", "ward_number": 7,
        }, format="json").json()
        self.client_for(self.admin).post(f"/api/farmer-change-requests/{change['id']}/approve/")
        farmer.refresh_from_db()
        self.assertEqual(farmer.cluster.name, "TAKUNDA JOSHUA MOYO")
        self.assertEqual(User.objects.get(pk=lead.pk).last_name, "MOYO")
        farm = farmer.farms.get()
        self.assertEqual((farm.total_hectares, farm.arable_hectares, farm.ward.name), (260, 150, "Ward 7"))
        self.assertEqual(farmer.ward.name, "Ward 7")

    def test_rejection_needs_a_reason_and_changes_nothing(self):
        farmer, lead = self.register_lead_with_wizard()
        change = self.client_for(lead).post(f"/api/farmers/{farmer.id}/change-requests/", {"phone_primary": "0771111111"}, format="json").json()
        admin = self.client_for(self.admin)
        self.assertEqual(admin.post(f"/api/farmer-change-requests/{change['id']}/reject/").status_code, 400)
        rejected = admin.post(f"/api/farmer-change-requests/{change['id']}/reject/", {"remarks": "Bring the new SIM registration"}, format="json")
        self.assertEqual(rejected.json()["status"], "REJECTED")
        farmer.refresh_from_db()
        self.assertNotEqual(farmer.phone_primary, "0771111111")
        current = self.client_for(lead).get(f"/api/farmers/{farmer.id}/change-requests/current/").json()
        self.assertEqual(current["values"]["phone_primary"], farmer.phone_primary)
        self.assertIn("ward_number", current["labels"])
        history = self.client_for(lead).get(f"/api/farmers/{farmer.id}/change-requests/").json()
        self.assertEqual(history[0]["remarks"], "Bring the new SIM registration")

    def test_another_lead_farmer_cannot_request_changes(self):
        farmer, _ = self.register_lead_with_wizard()
        from apps.farmers.services import open_lead_cluster

        other_record = Farmer.objects.create(first_name="OTHER", surname="LEAD", national_id="63-5656565O56", province=self.province)
        other = User.objects.create_user(email="o@example.com", username="o", password=PASSWORD, role=User.ROLE_LEAD_FARMER,
                                         farmer=other_record, assigned_cluster=open_lead_cluster(other_record))
        self.assertEqual(self.client_for(other).post(f"/api/farmers/{farmer.id}/change-requests/", {"phone_primary": "0770000000"}, format="json").status_code, 404)

    def test_a_lead_farmer_is_complete_without_kyc_documents(self):
        """Missing KYC files must not leave an administrator's lead farmer incomplete."""
        from importlib import import_module

        from django.apps import apps as global_apps

        from apps.farmers.kyc import kyc_upload_required, missing_required_documents

        registrar = User.objects.create_user(email="lead-registrar@example.com", username="lead-registrar", password=PASSWORD, role=User.ROLE_LEAD_FARMER)
        lead = Farmer.objects.create(
            first_name="TAKUNDA", middle_name="JOSHUA", surname="MUTENJE", national_id="63-2353535E34",
            province=self.province, district=self.district, phone_primary="0771111222",
            verification_status=Farmer.STATUS_DRAFT, membership_status=Farmer.MEMBERSHIP_INACTIVE,
            registered_by=registrar, is_lead=True,
        )
        lead.farms.create(farm_name="Mutenje Farm", total_hectares=100, arable_hectares=100, province=self.province, district=self.district)
        Cluster.objects.create(name="TAKUNDA JOSHUA MUTENJE", province=self.province, district=self.district, lead_member=lead)
        # The flag was never set, which is how older lead records stayed on the farmers list.
        unmarked = Farmer.objects.create(
            first_name="UNMARKED", surname="LEAD", national_id="63-1010101U10", province=self.province, district=self.district,
            verification_status=Farmer.STATUS_DRAFT, registered_by=None, is_lead=False,
        )
        Cluster.objects.create(name="UNMARKED LEAD", province=self.province, lead_member=unmarked)
        member = Farmer.objects.create(
            first_name="MEMBER", surname="DRAFT", national_id="63-2020202M20", province=self.province, district=self.district,
            verification_status=Farmer.STATUS_DRAFT, registered_by=registrar, is_lead=False,
        )
        member.farms.create(farm_name="Member Farm", total_hectares=20, arable_hectares=20, province=self.province, district=self.district)
        rejected = Farmer.objects.create(
            first_name="REJECTED", surname="LEAD", national_id="63-3030303R30", province=self.province,
            verification_status=Farmer.STATUS_REJECTED, is_lead=True, registered_by=self.admin,
        )

        self.assertFalse(kyc_upload_required(lead))
        self.assertEqual(missing_required_documents(lead), [])
        self.assertTrue(kyc_upload_required(member))

        import_module("apps.farmers.migrations.0013_complete_lead_farmers_without_kyc").complete(global_apps, None)
        lead.refresh_from_db()
        unmarked.refresh_from_db()
        member.refresh_from_db()
        rejected.refresh_from_db()
        self.assertEqual(lead.verification_status, Farmer.STATUS_VERIFIED)
        self.assertEqual(lead.membership_status, Farmer.MEMBERSHIP_ACTIVE)
        self.assertEqual(lead.farms.get().verification_status, "VERIFIED")
        self.assertTrue(unmarked.is_lead)
        self.assertEqual(unmarked.verification_status, Farmer.STATUS_VERIFIED)
        self.assertEqual(member.verification_status, Farmer.STATUS_DRAFT)
        self.assertEqual(rejected.verification_status, Farmer.STATUS_REJECTED)

        admin = self.client_for(self.admin)
        incomplete = [row["id"] for row in admin.get("/api/farmers/", {"verification_status": "DRAFT"}).json()["results"]]
        approved = [row["id"] for row in admin.get("/api/farmers/", {"verification_status": "VERIFIED"}).json()["results"]]
        self.assertIn(member.id, incomplete)
        self.assertNotIn(lead.id, incomplete)
        self.assertIn(lead.id, approved)
        listed = admin.get(f"/api/farmers/{lead.id}/").json()
        self.assertEqual(listed["verification_status"], Farmer.STATUS_VERIFIED)
        self.assertFalse(listed["kyc_upload_required"])
        self.assertEqual(listed["documents_summary"]["required"], 0)

    def test_saving_a_lead_without_a_registrar_completes_it_without_documents(self):
        farmer = Farmer.objects.create(
            first_name="RUDO", surname="MOYO", national_id="63-4040404R40", province=self.province, district=self.district,
            verification_status=Farmer.STATUS_DRAFT, is_lead=True, registered_by=None,
        )
        saved = self.client_for(self.admin).patch(f"/api/farmers/{farmer.id}/", {"phone_primary": "0771234567"}, format="json")
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["verification_status"], Farmer.STATUS_VERIFIED)
        self.assertFalse(saved.json()["kyc_upload_required"])
        self.assertEqual(saved.json()["documents_summary"]["required"], 0)
        farmer.refresh_from_db()
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_ACTIVE)
