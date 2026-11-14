from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.clusters.models import Cluster
from apps.farmers import kyc
from apps.farmers.models import Farm, Farmer, FarmerDocument, FarmerReviewEvent
from apps.geography.models import District, Province, Ward
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()
PDF = b"%PDF-1.4 test document"


def account(email, role, **extra):
    return User.objects.create_user(email=email, username=email, password="StrongPass123!", role=role, **extra)


@override_settings(MEDIA_ROOT="/tmp/sgr-test-media")
class RegistrationWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.province = Province.objects.create(name="Mashonaland West", code="MW")
        cls.other_province = Province.objects.create(name="Midlands", code="MD")
        cls.district = District.objects.create(province=cls.province, name="Makonde")
        cls.other_district = District.objects.create(province=cls.other_province, name="Gweru")
        cls.ward = Ward.objects.create(district=cls.district, name="Ward 3")
        cls.other_ward = Ward.objects.create(district=cls.other_district, name="Ward 1")
        cls.cluster = Cluster.objects.create(name="Chinhoyi Cluster", province=cls.province)
        cls.other_cluster = Cluster.objects.create(name="Gweru Cluster", province=cls.other_province)
        cls.lead = account("lead@example.com", User.ROLE_LEAD_FARMER, assigned_cluster=cls.cluster)
        cls.other_lead = account("lead2@example.com", User.ROLE_LEAD_FARMER, assigned_cluster=cls.other_cluster)
        cls.admin = account("admin@example.com", User.ROLE_SUPER_ADMIN)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def payload(self, **changes):
        data = {
            "first_name": "panashe", "surname": "chitima", "national_id": "63-2330173E58", "phone_primary": "0771234567",
            "farm_name": "chitiyo", "province": self.province.id, "district": self.district.id, "ward": self.ward.id,
            "total_hectares": "250", "arable_hectares": "200", "irrigated_hectares": "80", "as_draft": True,
        }
        data.update(changes)
        return data

    def register(self, client=None, **changes):
        response = (client or self.client_for(self.lead)).post("/api/farmers/", self.payload(**changes), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return Farmer.objects.get(pk=response.json()["id"])

    def upload(self, farmer, code, client=None, name="file.pdf", content=PDF):
        return (client or self.client_for(self.lead)).post(
            "/api/farmer-documents/",
            {"farmer": farmer.id, "document_type": code, "file": SimpleUploadedFile(name, content)},
            format="multipart",
        )

    def upload_required(self, farmer):
        for code in kyc.REQUIRED_CODES:
            self.assertEqual(self.upload(farmer, code).status_code, 201, code)

    # Registration ---------------------------------------------------------------------

    def test_lead_farmer_registration_is_a_draft_in_the_lead_farmers_own_cluster(self):
        farmer = self.register(cluster=self.other_cluster.id)
        self.assertEqual(farmer.cluster_id, self.cluster.id)
        self.assertEqual(farmer.verification_status, Farmer.STATUS_DRAFT)
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_INACTIVE)
        self.assertEqual(farmer.registered_by, self.lead)
        self.assertEqual((farmer.first_name, farmer.surname), ("PANASHE", "CHITIMA"))
        self.assertEqual(farmer.farms.get().farm_name, "CHITIYO")

    def test_lead_farmer_cannot_register_outside_the_cluster_region(self):
        response = self.client_for(self.lead).post(
            "/api/farmers/",
            self.payload(province=self.other_province.id, district=self.other_district.id, ward=self.other_ward.id),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("province", response.json())
        self.assertFalse(Farmer.objects.exists())

    def test_national_id_must_match_the_zimbabwean_format(self):
        client = self.client_for(self.lead)
        for bad in ("632330173E58", "63-2330173-E58", "63-233017E58", "6A-2330173E58"):
            response = client.post("/api/farmers/", self.payload(national_id=bad), format="json")
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("national_id", response.json())
        self.register(national_id="63-2330173e58")
        self.assertTrue(Farmer.objects.filter(national_id="63-2330173E58").exists())

    def test_ward_must_belong_to_the_district(self):
        response = self.client_for(self.lead).post("/api/farmers/", self.payload(ward=self.other_ward.id), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ward", response.json())

    def test_registration_context_fixes_the_lead_farmers_region(self):
        context = self.client_for(self.lead).get("/api/farmers/registration-context/").json()
        self.assertTrue(context["locked"])
        self.assertEqual(context["cluster"]["id"], self.cluster.id)
        self.assertEqual(context["province"]["id"], self.province.id)
        self.assertEqual([item["code"] for item in context["documents"] if item["required"]], kyc.REQUIRED_CODES)
        self.assertEqual([item["code"] for item in context["documents"] if item.get("when") == "NEW"], ["DAEO_LETTER"])
        self.assertFalse(self.client_for(self.admin).get("/api/farmers/registration-context/").json()["locked"])

    # Documents ------------------------------------------------------------------------

    def test_submission_needs_every_required_document(self):
        farmer = self.register()
        client = self.client_for(self.lead)
        self.upload(farmer, "NATIONAL_ID")
        refused = client.post(f"/api/farmers/{farmer.id}/submit/")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Proof of land", refused.json()["detail"])
        self.upload_required(farmer)
        self.assertEqual(client.post(f"/api/farmers/{farmer.id}/submit/").status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_SUBMITTED)
        self.assertIsNotNone(farmer.submitted_at)

    def test_uploads_are_checked_and_a_new_upload_replaces_the_old_one(self):
        farmer = self.register()
        self.assertEqual(self.upload(farmer, "NATIONAL_ID", name="id.exe").status_code, 400)
        self.assertEqual(self.upload(farmer, "NATIONAL_ID", name="id.pdf", content=b"not a pdf").status_code, 400)
        self.assertEqual(self.upload(farmer, "SELFIE").status_code, 400)
        self.assertEqual(self.upload(farmer, "NATIONAL_ID").status_code, 201)
        self.assertEqual(self.upload(farmer, "NATIONAL_ID", name="second.pdf").status_code, 201)
        self.assertEqual(farmer.documents.filter(document_type="NATIONAL_ID").count(), 1)
        self.assertEqual(farmer.documents.get().original_name, "second.pdf")

    def test_documents_are_only_served_to_users_who_may_see_the_farmer(self):
        farmer = self.register()
        document_id = self.upload(farmer, "NATIONAL_ID").json()["id"]
        url = f"/api/farmer-documents/{document_id}/download/"
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(self.client_for(self.other_lead).get(url).status_code, 404)
        served = self.client_for(self.lead).get(url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(b"".join(served.streaming_content), PDF)
        self.assertNotIn("file", self.client_for(self.lead).get(f"/api/farmer-documents/{document_id}/").json())

    # Approval -------------------------------------------------------------------------

    def test_lead_farmer_cannot_approve_or_verify_documents(self):
        farmer = self.register()
        self.upload_required(farmer)
        client = self.client_for(self.lead)
        client.post(f"/api/farmers/{farmer.id}/submit/")
        document = farmer.documents.first()
        self.assertEqual(client.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "VERIFIED"}, format="json").status_code, 403)
        self.assertEqual(client.post(f"/api/farmer-documents/{document.id}/review/", {"review_status": "VERIFIED"}, format="json").status_code, 403)
        self.assertEqual(self.upload(farmer, "NATIONAL_ID").status_code, 400)
        self.assertEqual(client.patch(f"/api/farmers/{farmer.id}/", {"phone_primary": "0779999999"}, format="json").status_code, 400)
        farmer.refresh_from_db()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_SUBMITTED)

    def test_administrator_verifies_documents_then_approves(self):
        farmer = self.register()
        self.upload_required(farmer)
        self.client_for(self.lead).post(f"/api/farmers/{farmer.id}/submit/")
        admin = self.client_for(self.admin)
        early = admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "VERIFIED"}, format="json")
        self.assertEqual(early.status_code, 400)
        for document in farmer.documents.all():
            self.assertEqual(admin.post(f"/api/farmer-documents/{document.id}/review/", {"review_status": "VERIFIED"}, format="json").status_code, 200)
        approved = admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "VERIFIED"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        farmer.refresh_from_db()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_VERIFIED)
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_ACTIVE)
        self.assertEqual(Farmer.objects.count(), 1)
        actions = list(farmer.review_events.values_list("action", flat=True))
        self.assertIn(FarmerReviewEvent.SUBMITTED, actions)
        self.assertIn(FarmerReviewEvent.DOCUMENT_VERIFIED, actions)
        self.assertIn(FarmerReviewEvent.APPROVED, actions)
        history = self.client_for(self.lead).get(f"/api/farmers/{farmer.id}/history/").json()
        self.assertEqual(history[0]["action"], FarmerReviewEvent.APPROVED)

    def test_corrections_are_sent_back_and_resubmitted_without_a_duplicate(self):
        farmer = self.register()
        self.upload_required(farmer)
        lead = self.client_for(self.lead)
        lead.post(f"/api/farmers/{farmer.id}/submit/")
        admin = self.client_for(self.admin)
        self.assertEqual(admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "CORRECTIONS_REQUESTED"}, format="json").status_code, 400)
        document = farmer.documents.get(document_type="PROOF_OF_LAND")
        admin.post(f"/api/farmer-documents/{document.id}/review/", {"review_status": "REJECTED", "remarks": "Page 2 is missing"}, format="json")
        sent_back = admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "CORRECTIONS_REQUESTED", "remarks": "Upload the full offer letter"}, format="json")
        self.assertEqual(sent_back.status_code, 200)
        seen = lead.get(f"/api/farmers/{farmer.id}/").json()
        self.assertEqual(seen["verification_status"], "CORRECTIONS_REQUESTED")
        self.assertEqual(seen["review_remarks"], "Upload the full offer letter")
        self.assertEqual(lead.patch(f"/api/farmers/{farmer.id}/", {"phone_primary": "0778888888"}, format="json").status_code, 200)
        self.assertEqual(self.upload(farmer, "PROOF_OF_LAND", name="full.pdf").status_code, 201)
        self.assertEqual(lead.post(f"/api/farmers/{farmer.id}/submit/").status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.verification_status, Farmer.STATUS_SUBMITTED)
        self.assertEqual(Farmer.objects.count(), 1)
        self.assertIn(FarmerReviewEvent.RESUBMITTED, farmer.review_events.values_list("action", flat=True))

    def test_rejection_needs_a_reason(self):
        farmer = self.register()
        admin = self.client_for(self.admin)
        self.assertEqual(admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "REJECTED"}, format="json").status_code, 400)
        self.assertEqual(admin.post(f"/api/farmers/{farmer.id}/verify/", {"verification_status": "REJECTED", "rejection_reason": "Land under 200 ha"}, format="json").status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.membership_status, Farmer.MEMBERSHIP_INACTIVE)

    # Financial privacy ------------------------------------------------------------------

    def test_lead_farmer_sees_compliance_percentages_and_no_amounts(self):
        farmer = self.register()
        Farmer.objects.filter(pk=farmer.pk).update(verification_status=Farmer.STATUS_VERIFIED)
        FarmerSubscription.objects.create(farmer=farmer, season="2026/2027", expected_amount=1000, paid_amount=300, outstanding_amount=700, payment_status="PARTIAL")
        lead = self.client_for(self.lead)
        listed = lead.get("/api/farmer-subscriptions/?season_name=2026/2027").json()["results"][0]
        self.assertEqual(listed["compliance_percent"], 30)
        self.assertEqual(listed["compliance_status"], "In progress")
        for name in ("expected_amount", "paid_amount", "outstanding_amount"):
            self.assertNotIn(name, listed)
        detail = lead.get(f"/api/farmer-subscriptions/{FarmerSubscription.objects.get().id}/").json()
        for name in ("expected_amount", "paid_amount", "outstanding_amount"):
            self.assertNotIn(name, detail)
        self.assertEqual(lead.get("/api/farmer-subscriptions/debtors/?season_name=2026/2027").status_code, 403)
        overview = lead.get("/api/farmers/cluster-overview/?season_name=2026/2027").json()
        self.assertEqual(overview["counts"]["total"], 1)
        self.assertEqual(overview["farmers"][0]["subscription_compliance"], 30)
        self.assertEqual(overview["performance"]["subscription_compliance"], 30)
        self.assertNotIn("300", str(overview))
        summary = lead.get("/api/farmers/dashboard-summary/?season_name=2026/2027").json()
        self.assertNotIn("receivables", summary["charts"])
        self.assertNotIn("subscription_receipts", summary["charts"])
        reports = lead.get("/api/reports/catalogue/").json()["reports"]
        self.assertFalse([report["code"] for report in reports if report["category"] in {"subscriptions", "recovery"} and "amount" in report["description"].lower()])
        admin_row = self.client_for(self.admin).get("/api/farmer-subscriptions/?season_name=2026/2027").json()["results"][0]
        self.assertEqual(admin_row["paid_amount"], "300.00")

    def test_other_cluster_gets_an_empty_overview(self):
        self.register()
        overview = self.client_for(self.other_lead).get("/api/farmers/cluster-overview/").json()
        self.assertEqual(overview["counts"]["total"], 0)
        self.assertEqual(overview["cluster"]["name"], "Gweru Cluster")


class WardRegisterTests(TestCase):
    def test_real_wards_load_once_and_keep_existing_wards(self):
        call_command("load_zimbabwe_geography", verbosity=0)
        buhera = District.objects.get(name="Buhera")
        kept = Ward.objects.create(district=buhera, name="5")
        call_command("load_zimbabwe_wards", verbosity=0)
        total = Ward.objects.count()
        self.assertEqual(total, 1961)
        self.assertEqual(buhera.wards.count(), 33)
        kept.refresh_from_db()
        self.assertEqual(kept.name, "5")
        self.assertTrue(kept.code.startswith("ZW"))
        self.assertNotEqual(District.objects.get(name="Bulawayo").wards.count(), buhera.wards.count())
        call_command("load_zimbabwe_wards", verbosity=0)
        self.assertEqual(Ward.objects.count(), total)


@override_settings(MEDIA_ROOT="/tmp/sgr-test-media")
class InPersonKycTests(TestCase):
    """An administrator checks KYC documents in person, so their registrations upload nothing."""

    def setUp(self):
        from apps.farmers.services import open_lead_cluster

        self.province = Province.objects.create(name="Mashonaland West", code="MW")
        self.district = District.objects.create(province=self.province, name="Makonde")
        self.admin = account("admin@example.com", User.ROLE_SUPER_ADMIN)
        self.lead_record = Farmer.objects.create(
            first_name="ADMIN", surname="CAPTURED", national_id="63-1212121A12", province=self.province, district=self.district,
            registered_by=self.admin,
        )
        Farm.objects.create(farmer=self.lead_record, farm_name="Home", province=self.province, total_hectares=250, arable_hectares=220)
        cluster = open_lead_cluster(self.lead_record)
        self.lead = account("lead@example.com", User.ROLE_LEAD_FARMER, assigned_cluster=cluster, farmer=self.lead_record)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_administrator_capture_submits_and_is_approved_without_documents(self):
        admin = self.client_for(self.admin)
        record = admin.get(f"/api/farmers/{self.lead_record.id}/").json()
        self.assertFalse(record["kyc_upload_required"])
        self.assertEqual(record["documents_summary"]["required"], 0)
        self.assertTrue(self.client_for(self.lead).get("/api/farmers/registration-context/").json()["kyc_upload"])
        self.assertFalse(admin.get("/api/farmers/registration-context/").json()["kyc_upload"])
        submitted = admin.post(f"/api/farmers/{self.lead_record.id}/submit/")
        self.assertEqual(submitted.status_code, 200, submitted.content)
        # Finishing an administrator's own capture completes it. It does not wait in the queue.
        self.assertEqual(submitted.json()["verification_status"], "VERIFIED")
        remarks = list(self.lead_record.review_events.values_list("remarks", flat=True))
        self.assertTrue(any("in person" in remark for remark in remarks))

    def test_lead_farmer_cannot_submit_an_administrator_capture_without_documents(self):
        self.assertEqual(self.client_for(self.lead).post(f"/api/farmers/{self.lead_record.id}/submit/").status_code, 403)

    def test_lead_farmer_captures_still_need_every_document(self):
        lead = self.client_for(self.lead)
        created = lead.post("/api/farmers/", {
            "first_name": "Rudo", "surname": "Moyo", "national_id": "63-3434343R34", "phone_primary": "0771234567",
            "farm_name": "Rudo", "province": self.province.id, "district": self.district.id,
            "ward": Ward.objects.create(district=self.district, name="Ward 2").id,
            "total_hectares": "250", "arable_hectares": "220", "irrigated_hectares": "0", "as_draft": True,
        }, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(created.json()["kyc_upload_required"])
        refused = lead.post(f"/api/farmers/{created.json()['id']}/submit/")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Upload the required documents", refused.json()["detail"])


class LeadRecordFarmTests(TestCase):
    def test_wizard_save_adds_the_first_farm_to_a_lead_record(self):
        from apps.farmers.services import open_lead_cluster

        province = Province.objects.create(name="Mashonaland East", code="ME")
        district = District.objects.create(province=province, name="Marondera")
        ward = Ward.objects.create(district=district, name="Ward 7")
        admin = account("admin@example.com", User.ROLE_SUPER_ADMIN)
        lead = Farmer.objects.create(first_name="JOHN", surname="MOYO", national_id="63-1111111A11", phone_primary="0771111111",
                                     province=province, district=district, ward=ward, registered_by=admin)
        open_lead_cluster(lead)
        client = APIClient()
        client.force_authenticate(user=admin)
        saved = client.patch(f"/api/farmers/{lead.id}/", {
            "farm_name": "moyo estate", "total_hectares": "320", "arable_hectares": "260", "irrigated_hectares": "60", "as_draft": True,
        }, format="json")
        self.assertEqual(saved.status_code, 200, saved.content)
        farm = lead.farms.get()
        self.assertEqual((farm.farm_name, farm.total_hectares, farm.cluster_id), ("MOYO ESTATE", 320, lead.cluster_id))
        self.assertEqual(client.post(f"/api/farmers/{lead.id}/submit/").status_code, 200)
