from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.clusters.models import Cluster
from apps.farmers import kyc
from apps.farmers.models import Farmer
from apps.geography.models import District, Province, Ward
from apps.production.models import FarmerProduction
from apps.programmes.models import Crop, Season

User = get_user_model()
PDF = b"%PDF-1.4 test document"


class LeadClusterRegistrationTests(TestCase):
    def setUp(self):
        self.province = Province.objects.create(name="Mashonaland East", code="ME")
        self.district = District.objects.create(province=self.province, name="Marondera")
        self.executive = User.objects.create_user(
            email="exec@example.com", username="exec@example.com", password="StrongPass123!", role=User.ROLE_SGR_EXECUTIVE,
        )
        self.season = Season.objects.create(name="2026/2027 Summer", start_date=date(2026, 5, 1), end_date=date(2026, 10, 31), status=Season.STATUS_ACTIVE)
        self.crop = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
        # Wards come from the official register. A typed ward must match one of these.
        for number in (2, 4, 9):
            Ward.objects.create(district=self.district, name=f"Ward {number}")

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def lead_payload(self, **changes):
        data = {
            "first_name": "J", "surname": "Chigumba", "national_id": "63-1111111E11", "phone_primary": "0771111111",
            "farm_name": "Home Farm", "province": self.province.id, "district": self.district.id,
            "ward_text": "Ward 4", "total_hectares": "80", "arable_hectares": "60", "irrigated_hectares": "10",
            "farmer_type": "EXISTING", "as_draft": True, "as_lead": True,
        }
        data.update(changes)
        return data

    def test_an_administrator_registers_a_lead_farmer_only(self):
        admin = User.objects.create_user(
            email="root@example.com", username="root@example.com", password="StrongPass123!", role=User.ROLE_SUPER_ADMIN,
        )
        client = self.client_for(admin)
        refused = client.post("/api/farmers/", {**self.lead_payload(), "as_lead": False}, format="json")
        self.assertEqual(refused.status_code, 403)
        created = client.post("/api/farmers/", self.lead_payload(national_id="63-9999999E99"), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(created.data["is_lead"])

    def test_one_province_can_hold_two_lead_farmers_each_with_their_own_cluster(self):
        client = self.client_for(self.executive)
        refused = client.post("/api/farmers/", {**self.lead_payload(), "as_lead": False}, format="json")
        self.assertEqual(refused.status_code, 403)

        first = client.post("/api/farmers/", self.lead_payload(), format="json")
        self.assertEqual(first.status_code, 201, first.content)
        second = client.post("/api/farmers/", self.lead_payload(
            first_name="T", surname="Mharapara", national_id="63-2222222E22", ward_text="Ward 9",
        ), format="json")
        self.assertEqual(second.status_code, 201, second.content)

        j = Farmer.objects.get(pk=first.data["id"])
        t = Farmer.objects.get(pk=second.data["id"])
        self.assertTrue(j.is_lead and t.is_lead)
        self.assertEqual(j.cluster.name, "J CHIGUMBA")
        self.assertEqual(t.cluster.name, "T MHARAPARA")
        self.assertEqual(j.cluster.province_id, self.province.id)
        self.assertEqual(t.cluster.province_id, self.province.id)
        self.assertNotEqual(j.cluster_id, t.cluster_id)
        self.assertEqual(j.ward.name, "Ward 4")
        self.assertEqual(Cluster.objects.filter(province=self.province, lead_member__isnull=False).count(), 2)

    def test_a_lead_farmer_cannot_see_or_register_into_another_cluster(self):
        client = self.client_for(self.executive)
        created = client.post("/api/farmers/", self.lead_payload(), format="json")
        other = client.post("/api/farmers/", self.lead_payload(first_name="T", surname="Mharapara", national_id="63-2222222E22"), format="json")
        lead = User.objects.create_user(
            email="j@example.com", username="j@example.com", password="StrongPass123!", role=User.ROLE_LEAD_FARMER,
            assigned_cluster_id=created.data["cluster"], farmer_id=created.data["id"], province=self.province,
        )
        other_user = User.objects.create_user(
            email="t@example.com", username="t@example.com", password="StrongPass123!", role=User.ROLE_LEAD_FARMER,
            assigned_cluster_id=other.data["cluster"], farmer_id=other.data["id"], province=self.province,
        )
        member = self.client_for(lead).post("/api/farmers/", {
            "first_name": "Rudo", "surname": "Moyo", "national_id": "63-3333333E33", "phone_primary": "0773333333",
            "farm_name": "Rudo Farm", "province": self.province.id, "district": self.district.id, "ward_text": "Ward 4",
            "total_hectares": "20", "arable_hectares": "15", "irrigated_hectares": "0", "as_draft": True,
            "cluster": other.data["cluster"],
        }, format="json")
        self.assertEqual(member.status_code, 201, member.content)
        self.assertEqual(member.data["cluster"], created.data["cluster"])
        self.assertEqual(self.client_for(other_user).get(f"/api/farmers/{member.data['id']}/").status_code, 404)

        duplicate = self.client_for(other_user).post("/api/farmers/", {
            "first_name": "Rudo", "surname": "Moyo", "national_id": "63-3333333E33", "phone_primary": "0774444444",
            "farm_name": "Other Farm", "province": self.province.id, "district": self.district.id, "ward_text": "Ward 9",
            "total_hectares": "10", "arable_hectares": "8", "irrigated_hectares": "0", "as_draft": True,
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("J CHIGUMBA", duplicate.json()["national_id"][0])

    def test_new_farmers_need_the_daeo_letter_and_existing_farmers_do_not(self):
        client = self.client_for(self.executive)
        created = client.post("/api/farmers/", self.lead_payload(farmer_type="NEW"), format="json")
        farmer = Farmer.objects.get(pk=created.data["id"])
        lead = User.objects.create_user(
            email="j@example.com", username="j@example.com", password="StrongPass123!", role=User.ROLE_LEAD_FARMER,
            assigned_cluster_id=farmer.cluster_id, province=self.province,
        )
        owner = self.client_for(lead)
        # The lead's own record was captured by the executive, who checks its documents in person.
        self.assertEqual(kyc.required_codes_for(farmer), [])
        new_member = owner.post("/api/farmers/", {
            "first_name": "Tafara", "surname": "Ncube", "national_id": "63-6666666E66", "phone_primary": "0776666666",
            "farm_name": "Ncube Farm", "province": self.province.id, "district": self.district.id, "ward_text": "Ward 2",
            "total_hectares": "12", "arable_hectares": "10", "irrigated_hectares": "0", "farmer_type": "NEW", "as_draft": True,
        }, format="json")
        self.assertEqual(new_member.status_code, 201, new_member.content)
        member_id = new_member.data["id"]
        for code in kyc.REQUIRED_CODES:
            response = owner.post("/api/farmer-documents/", {"farmer": member_id, "document_type": code, "file": SimpleUploadedFile(f"{code}.pdf", PDF)}, format="multipart")
            self.assertEqual(response.status_code, 201, code)
        missing = owner.post(f"/api/farmers/{member_id}/submit/")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("DAEO letter", missing.json()["detail"])
        owner.post("/api/farmer-documents/", {"farmer": member_id, "document_type": "DAEO_LETTER", "file": SimpleUploadedFile("daeo.pdf", PDF)}, format="multipart")
        self.assertEqual(owner.post(f"/api/farmers/{member_id}/submit/").status_code, 200)

        existing = client.post("/api/farmers/", self.lead_payload(first_name="Rudo", surname="Dube", national_id="63-4444444E44", farmer_type="EXISTING"), format="json")
        # The executive created another lead. A member registration uses the lead account.
        member = owner.post("/api/farmers/", {
            "first_name": "Rudo", "surname": "Dube", "national_id": "63-5555555E55", "phone_primary": "0775555555",
            "farm_name": "Dube Farm", "province": self.province.id, "district": self.district.id, "ward_text": "Ward 2",
            "total_hectares": "12", "arable_hectares": "10", "irrigated_hectares": "0", "farmer_type": "EXISTING", "as_draft": True,
        }, format="json")
        self.assertEqual(member.status_code, 201, member.content)
        for code in kyc.REQUIRED_CODES:
            owner.post("/api/farmer-documents/", {"farmer": member.data["id"], "document_type": code, "file": SimpleUploadedFile(f"{code}.pdf", PDF)}, format="multipart")
        self.assertEqual(owner.post(f"/api/farmers/{member.data['id']}/submit/").status_code, 200)
        self.assertFalse(Farmer.objects.get(pk=member.data["id"]).documents.filter(document_type="DAEO_LETTER").exists())

    def test_crop_allocation_is_saved_and_copied_when_the_farmer_is_approved(self):
        client = self.client_for(self.executive)
        created = client.post("/api/farmers/", self.lead_payload(), format="json")
        farmer_id = created.data["id"]
        too_much = client.patch(f"/api/farmers/{farmer_id}/", {"crop_allocations": [
            {"crop": self.crop.id, "season": self.season.id, "hectares": "70"},
        ]}, format="json")
        self.assertEqual(too_much.status_code, 400, too_much.content)
        saved = client.patch(f"/api/farmers/{farmer_id}/", {"crop_allocations": [
            {"crop": self.crop.id, "season": self.season.id, "hectares": "40"},
        ]}, format="json")
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.data["crop_allocations"][0]["crop_name"], "Maize")
        self.assertEqual(Decimal(saved.data["crop_allocations"][0]["hectares"]), Decimal("40.00"))

        lead = User.objects.create_user(
            email="j@example.com", username="j@example.com", password="StrongPass123!", role=User.ROLE_LEAD_FARMER,
            assigned_cluster_id=created.data["cluster"], province=self.province,
        )
        # The executive captured this record and checked its KYC documents in person, so nothing is uploaded.
        self.assertEqual(kyc.required_codes_for(Farmer.objects.get(pk=farmer_id)), [])
        self.assertEqual(self.client_for(lead).post(f"/api/farmers/{farmer_id}/submit/").status_code, 403)
        self.assertEqual(client.post(f"/api/farmers/{farmer_id}/submit/").status_code, 200)
        admin = User.objects.create_user(email="root@example.com", username="root@example.com", password="StrongPass123!", role=User.ROLE_SUPER_ADMIN)
        reviewer = self.client_for(admin)
        for document in reviewer.get(f"/api/farmer-documents/?farmer={farmer_id}").data["results"]:
            reviewer.post(f"/api/farmer-documents/{document['id']}/review/", {"review_status": "VERIFIED"}, format="json")
        approved = reviewer.post(f"/api/farmers/{farmer_id}/verify/", {"verification_status": "VERIFIED"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.content)
        production = FarmerProduction.objects.get(farmer_id=farmer_id)
        self.assertEqual(production.crop, "Maize")
        self.assertEqual(production.contracted_hectares, Decimal("40.00"))
