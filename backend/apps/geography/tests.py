from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.clusters.models import Cluster
from apps.farmers.models import Farmer
from apps.geography.models import District, Province

User = get_user_model()


class GeographyDropdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="geography@example.com",
            username="geography-user",
            password="StrongPass123!",
            role=User.ROLE_VIEWER,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_geography_seed_command_provides_all_manicaland_districts_once(self):
        call_command("load_zimbabwe_geography")
        call_command("load_zimbabwe_geography")

        province = Province.objects.get(name__iexact="Manicaland")
        response = self.client.get(reverse("district-list"), {"province": province.pk})
        names = {district["name"] for district in response.data["results"]}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            names,
            {"Buhera", "Chimanimani", "Chipinge", "Makoni", "Mutare", "Mutasa", "Nyanga"},
        )
        self.assertNotIn("Unknown", names)

    def test_cluster_catalogue_loader_provides_district_scoped_options(self):
        call_command("load_zimbabwe_geography")
        call_command("load_cluster_catalogue")
        district = District.objects.get(name__iexact="Makonde")

        response = self.client.get(reverse("cluster-list"), {"district": district.pk})

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["count"], 0)
        self.assertTrue(all(cluster["district"] == district.pk for cluster in response.data["results"]))
        self.assertEqual(Cluster.objects.filter(district=district, active=True).count(), response.data["count"])

    def test_sync_loads_ten_provinces_without_duplicating_or_detaching_farmers(self):
        official = Province.objects.create(name="Mashonaland West", code="MW")
        official_district = District.objects.create(province=official, name="Chegutu", code="CHEGUT")
        alias = Province.objects.create(name="MASHWEST", code="MASHWEST")
        alias_district = District.objects.create(province=alias, name="CHEGUTU", code="CHEOLD")
        Province.objects.create(name="Harare", code="HRE")
        farmer = Farmer.objects.create(
            first_name="Rudo", surname="Ncube", national_id="63-GEO-100", phone_primary="0771000099",
            province=alias, district=alias_district,
        )

        call_command("load_zimbabwe_geography")
        call_command("load_zimbabwe_geography")

        farmer.refresh_from_db()
        self.assertEqual(farmer.province_id, official.id)
        self.assertEqual(farmer.district_id, official_district.id)
        self.assertEqual(farmer.district.name, "Chegutu")
        self.assertEqual(Province.objects.filter(official=True).count(), 10)
        self.assertEqual(Province.objects.filter(name__iexact="Mashonaland West").count(), 1)
        self.assertFalse(Province.objects.filter(name="Harare").exists())
        self.assertTrue(Province.objects.filter(name="Harare Metropolitan", official=True).exists())
        self.assertTrue(Province.objects.filter(name="Bulawayo Metropolitan", official=True).exists())
        east = Province.objects.get(name="Mashonaland East")
        east_names = set(District.objects.filter(province=east, active=True).values_list("name", flat=True))
        self.assertIn("Seke", east_names)
        self.assertIn("Uzumba-Maramba-Pfungwe", east_names)
        self.assertNotIn("Chegutu", east_names)
        provinces = self.client.get(reverse("province-list"), {"official": "true"})
        self.assertEqual(provinces.status_code, 200)
        self.assertEqual(
            {row["name"] for row in provinces.data["results"]},
            {
                "Manicaland", "Mashonaland Central", "Mashonaland East", "Mashonaland West", "Masvingo",
                "Matabeleland North", "Matabeleland South", "Midlands", "Harare Metropolitan", "Bulawayo Metropolitan",
            },
        )
        harare = Province.objects.get(name="Harare Metropolitan")
        districts = self.client.get(reverse("district-list"), {"province": harare.pk})
        self.assertEqual({row["name"] for row in districts.data["results"]}, {"Harare", "Chitungwiza", "Epworth"})

    def test_province_and_district_filters_and_provincial_access_stay_in_place(self):
        call_command("load_zimbabwe_geography")
        west = Province.objects.get(name="Mashonaland West")
        east = Province.objects.get(name="Mashonaland East")
        chegutu = District.objects.get(province=west, name="Chegutu")
        marondera = District.objects.get(province=east, name="Marondera")
        Farmer.objects.create(first_name="West", surname="Geo", national_id="63-GEO-201", phone_primary="0772000001", province=west, district=chegutu)
        Farmer.objects.create(first_name="East", surname="Geo", national_id="63-GEO-202", phone_primary="0772000002", province=east, district=marondera)
        filtered = self.client.get(reverse("farmer-list"), {"province": west.pk, "district": chegutu.pk, "search": "Geo"})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual([row["surname"] for row in filtered.data["results"]], ["Geo"])
        self.assertEqual(filtered.data["results"][0]["province_name"], "Mashonaland West")

        coordinator = User.objects.create_user(
            email="west-coord@example.com", username="west-coord", password="StrongPass123!",
            role=User.ROLE_PROVINCIAL_COORDINATOR, province=west,
        )
        scoped = APIClient()
        scoped.force_authenticate(user=coordinator)
        visible = scoped.get(reverse("farmer-list"), {"search": "Geo"})
        self.assertEqual([row["province_name"] for row in visible.data["results"]], ["Mashonaland West"])