from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farmers.models import Farmer
from apps.geography.models import District, Province

from .models import Cluster

User = get_user_model()


class ClusterLeadFarmerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="clusters@example.com",
            username="cluster-officer",
            password="StrongPass123!",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.province = Province.objects.create(name="Midlands", code="MD")
        self.other = Province.objects.create(name="Manicaland", code="MN")
        self.district = District.objects.create(province=self.province, name="Gweru")
        self.leader = Farmer.objects.create(
            first_name="Lead",
            surname="Farmer",
            national_id="63-2000001-A-00",
            phone_primary="0772000001",
            province=self.province,
            district=self.district,
        )
        self.outsider = Farmer.objects.create(
            first_name="Other",
            surname="Province",
            national_id="63-2000002-A-00",
            phone_primary="0772000002",
            province=self.other,
        )

    def test_cluster_can_be_created_with_a_registered_lead_and_no_members(self):
        response = self.client.post(reverse("cluster-list"), {
            "name": "Gweru Central",
            "province": self.province.pk,
            "district": self.district.pk,
            "lead_member": self.leader.pk,
            "active": True,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["lead_farmer_name"], self.leader.full_name)
        self.assertEqual(response.data["member_count"], 0)
        self.assertEqual(Cluster.objects.get(name="Gweru Central").farmers.count(), 0)

    def test_lead_farmer_must_belong_to_the_cluster_province(self):
        response = self.client.post(reverse("cluster-list"), {
            "name": "Wrong Province",
            "province": self.province.pk,
            "lead_member": self.outsider.pk,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lead_member", response.data)

    def test_one_farmer_cannot_lead_two_active_clusters(self):
        first = self.client.post(reverse("cluster-list"), {
            "name": "Cluster A",
            "province": self.province.pk,
            "lead_member": self.leader.pk,
        }, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(reverse("cluster-list"), {
            "name": "Cluster B",
            "province": self.province.pk,
            "lead_member": self.leader.pk,
        }, format="json")
        self.assertEqual(second.status_code, 400)
        self.assertIn("lead_member", second.data)
