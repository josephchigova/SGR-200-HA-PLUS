from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.farmers.models import Farmer
from apps.farmers.services import open_lead_cluster
from apps.geography.models import District, Province

from .models import Cluster

User = get_user_model()


class ClusterLeadFarmerTests(TestCase):
    """A cluster exists only as a lead farmer's group. It is never created on its own."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="clusters@example.com", username="cluster-officer", password="StrongPass123!", role=User.ROLE_SUPER_ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.province = Province.objects.create(name="Midlands", code="MD")
        self.district = District.objects.create(province=self.province, name="Gweru")
        self.leader = Farmer.objects.create(
            first_name="LEAD", surname="FARMER", national_id="63-2000001A00", phone_primary="0772000001",
            province=self.province, district=self.district,
        )

    def test_the_cluster_api_cannot_create_a_cluster(self):
        response = self.client.post("/api/clusters/", {"name": "Midlands North", "province": self.province.pk, "lead_member": self.leader.pk}, format="json")
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Cluster.objects.exists())

    def test_a_lead_farmer_opens_exactly_one_cluster_named_after_them(self):
        first = open_lead_cluster(self.leader)
        again = open_lead_cluster(self.leader)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(first.name, "LEAD FARMER")
        self.assertEqual(first.lead_member, self.leader)
        self.assertEqual(first.province, self.province)
        listed = self.client.get("/api/clusters/").json()
        rows = listed["results"] if isinstance(listed, dict) else listed
        self.assertEqual([row["lead_farmer_name"] for row in rows], ["LEAD FARMER"])
