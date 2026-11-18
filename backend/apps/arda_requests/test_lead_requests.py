"""Lead farmer requests: one consolidated request per lead farmer, programme, year and season."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.arda_requests.models import ARDARequestBatch, LeadRequest
from apps.clusters.models import Cluster
from apps.farmers.models import Farm, Farmer, RegistrationCropAllocation
from apps.geography.models import District, Province
from apps.inputs.models import Input, InputAllocation
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice, Programme, ProgrammeCrop, Season
from apps.subscriptions.models import FarmerSubscription

User = get_user_model()


class LeadRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(email="officer@example.com", username="officer", password="Str0ng!Passw0rd", role=User.ROLE_SUPER_ADMIN)
        province = Province.objects.create(name="Mashonaland East", code="ME")
        cls.district = District.objects.create(province=province, name="Marondera")
        cls.province = province
        cls.season = Season.objects.create(name="2026/2027", start_date=date(2026, 10, 1), end_date=date(2027, 9, 30), status=Season.STATUS_ACTIVE)
        cls.maize = Crop.objects.create(name="Maize", category=Crop.CATEGORY_SUMMER)
        cls.sorghum = Crop.objects.create(name="Sorghum", category=Crop.CATEGORY_SUMMER)
        cls.wheat = Crop.objects.create(name="Wheat", category=Crop.CATEGORY_WINTER)
        for crop in (cls.maize, cls.sorghum):
            CropSellingPrice.objects.create(crop=crop, season=cls.season, price_per_tonne=Decimal("300.00"))
        cls.cluster = Cluster.objects.create(name="Moyo Cluster", province=province)
        cls.other_cluster = Cluster.objects.create(name="Other Cluster", province=province)
        cls.john = cls.farmer("John", "63-1000001A11", cls.cluster)
        cls.cluster.lead_member = cls.john
        cls.cluster.save(update_fields=["lead_member"])
        cls.lead = User.objects.create_user(email="lead@example.com", username="lead", password="Str0ng!Passw0rd", role=User.ROLE_LEAD_FARMER, assigned_cluster=cls.cluster)
        cls.rudo = cls.farmer("Rudo", "63-1000002A11", cls.cluster)
        cls.outsider = cls.farmer("Tafara", "63-1000003A11", cls.other_cluster)

        cls.seedco = Programme.objects.create(name="SEEDCO", code="SC", season=cls.season, input_categories=["SEED", "FERTILIZER"])
        for crop in (cls.maize, cls.sorghum, cls.wheat):
            ProgrammeCrop.objects.create(programme=cls.seedco, crop=crop)
        cls.mbizi = cls.product(cls.maize, "SEED", "Mbizi", "25", "2.00")
        cls.shumba = cls.product(cls.maize, "SEED", "Shumba", "20", "3.00")
        cls.compound = cls.product(cls.maize, "FERTILIZER", "Compound D", "400", "0.64")
        cls.sorghum_seed = cls.product(cls.sorghum, "SEED", "Variety B", "10", "4.00")

    @classmethod
    def farmer(cls, name, national_id, cluster):
        farmer = Farmer.objects.create(
            first_name=name, surname="Moyo", national_id=national_id, province=cls.province, district=cls.district, cluster=cluster,
            verification_status=Farmer.STATUS_VERIFIED, membership_status=Farmer.MEMBERSHIP_ACTIVE,
        )
        Farm.objects.create(farmer=farmer, farm_name=f"{name} Farm", province=cls.province, district=cls.district, total_hectares=40, arable_hectares=30)
        FarmerSubscription.objects.create(farmer=farmer, season=cls.season.name, expected_amount=500, paid_amount=500, outstanding_amount=0, payment_status="PAID")
        for crop in (cls.maize, cls.sorghum):
            RegistrationCropAllocation.objects.create(farmer=farmer, crop=crop, season=cls.season, hectares=10)
        return farmer

    @classmethod
    def product(cls, crop, category, name, rate, price):
        item = Input.objects.create(name=name, category=category, unit="kg")
        return CropInputRequirement.objects.create(
            crop=crop, programme=cls.seedco, input_category=category, input_product=item, group_name=category.title(),
            item_name=name, rate_per_hectare=rate, unit="kg", cost_per_unit=price,
        )

    def setUp(self):
        self.officer = APIClient()
        self.officer.force_authenticate(self.admin)
        self.leader = APIClient()
        self.leader.force_authenticate(self.lead)
        # SEEDCO's own input requests: the hectares it agreed to supply, per variety.
        self.maize_request = self.programme_request("Maize", [(self.mbizi, "8"), (self.shumba, "7"), (self.compound, "15")])
        self.sorghum_request = self.programme_request("Sorghum", [(self.sorghum_seed, "20")])

    def programme_request(self, crop, lines):
        response = self.officer.post(reverse("arda-request-batch-list"), {
            "programme": self.seedco.id, "season": self.season.id, "crop": crop,
            "lines": [{"requirement": requirement.id, "requested_hectares": hectares} for requirement, hectares in lines],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return ARDARequestBatch.objects.get(pk=response.data["id"])

    def product_line(self, batch, requirement):
        return batch.lines.get(requirement=requirement).id

    def open(self, client=None, crop_season="SUMMER"):
        return (client or self.leader).post(reverse("lead-request-list"), {"programme": self.seedco.id, "season": self.season.id, "crop_season": crop_season}, format="json")

    def add(self, request_id, farmer, crop, hectares, products, client=None):
        return (client or self.leader).post(reverse("lead-request-line-list"), {
            "request": request_id, "farmer": farmer.id, "crop": crop.id, "hectares": hectares, "products": products,
        }, format="json")

    def build(self):
        opened = self.open()
        self.assertEqual(opened.status_code, 201, opened.data)
        request_id = opened.data["id"]
        for farmer, crop, hectares, products in (
            (self.john, self.maize, "5", [self.product_line(self.maize_request, self.mbizi), self.product_line(self.maize_request, self.compound)]),
            (self.rudo, self.maize, "4", [self.product_line(self.maize_request, self.shumba)]),
            (self.john, self.sorghum, "2", [self.product_line(self.sorghum_request, self.sorghum_seed)]),
        ):
            added = self.add(request_id, farmer, crop, hectares, products)
            self.assertEqual(added.status_code, 201, added.data)
        return request_id

    def test_lead_farmer_builds_one_consolidated_request_with_automatic_totals(self):
        request_id = self.build()
        detail = self.leader.get(reverse("lead-request-detail", kwargs={"pk": request_id})).data
        self.assertEqual((detail["lead_farmer_name"], detail["programme_name"], detail["season_name"], detail["crop_season_label"]), ("John Moyo", "SEEDCO", "2026/2027", "Summer"))
        self.assertEqual((detail["farmers"], detail["total_hectares"]), (2, "11"))
        totals = {(row["crop"], row["product_name"]): row for row in detail["totals"]["rows"]}
        self.assertEqual(totals[("Maize", "Mbizi")]["quantity"], "125")  # 25 kg x 5 ha
        self.assertEqual(totals[("Maize", "Compound D")]["quantity"], "2000")  # 400 kg x 5 ha
        self.assertEqual(totals[("Maize", "Shumba")]["quantity"], "80")  # 20 kg x 4 ha
        self.assertEqual(totals[("Sorghum", "Variety B")]["quantity"], "20")  # 10 kg x 2 ha
        self.assertIsNone(totals[("Maize", "Mbizi")]["cost"])  # lead farmers do not see money
        # One request per lead farmer, programme, year and season; Winter is separate.
        self.assertEqual(self.open().status_code, 400)
        self.assertEqual(self.open(crop_season="WINTER").status_code, 201)

    def test_lines_must_fit_the_cluster_season_and_programme_request(self):
        request_id = self.open().data["id"]
        mbizi, shumba = self.product_line(self.maize_request, self.mbizi), self.product_line(self.maize_request, self.shumba)
        self.assertEqual(self.add(request_id, self.outsider, self.maize, "2", [mbizi]).status_code, 400)  # not in the cluster
        self.assertEqual(self.add(request_id, self.rudo, self.wheat, "2", [mbizi]).status_code, 400)  # winter crop
        self.assertEqual(self.add(request_id, self.rudo, self.maize, "2", [mbizi, shumba]).status_code, 400)  # two varieties
        self.assertEqual(self.add(request_id, self.rudo, self.maize, "12", [mbizi]).status_code, 400)  # more than the farmer's 10 ha
        wrong = self.add(request_id, self.rudo, self.sorghum, "2", [mbizi])  # maize product on sorghum
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(self.add(request_id, self.rudo, self.maize, "2", [mbizi]).status_code, 201)
        self.assertEqual(self.add(request_id, self.rudo, self.maize, "3", [shumba]).status_code, 400)  # same farmer and crop twice

    def test_admin_approves_the_whole_request_and_allocations_draw_on_the_programme_request(self):
        request_id = self.build()
        self.assertEqual(self.leader.post(reverse("lead-request-approve", kwargs={"pk": request_id})).status_code, 403)
        submitted = self.leader.post(reverse("lead-request-submit", kwargs={"pk": request_id}))
        self.assertEqual((submitted.status_code, submitted.data["status"]), (200, "SUBMITTED"))
        # A submitted request is fixed until Admin decides.
        self.assertEqual(self.add(request_id, self.rudo, self.sorghum, "1", [self.product_line(self.sorghum_request, self.sorghum_seed)]).status_code, 400)

        summary = self.officer.get(reverse("lead-request-summary"), {"season": self.season.id, "crop_season": "SUMMER"}).data
        consolidated = {(row["crop"], row["product_name"]): row for row in summary["totals"]["rows"]}
        self.assertEqual((consolidated[("Maize", "Compound D")]["quantity"], consolidated[("Maize", "Compound D")]["cost"]), ("2000", "1280"))
        self.assertEqual([lead["lead_farmer_name"] for lead in summary["requests"]], ["John Moyo"])

        approved = self.officer.post(reverse("lead-request-approve", kwargs={"pk": request_id}), {"notes": "OK"}, format="json")
        self.assertEqual((approved.status_code, approved.data["status"]), (200, "APPROVED"), approved.data)
        self.assertEqual(InputAllocation.objects.count(), 3)
        self.assertTrue(all(line["allocation"] for line in approved.data["lines"]))
        products = {row["product_name"]: row for row in self.officer.get(reverse("arda-request-batch-detail", kwargs={"pk": self.maize_request.id})).data["products"]}
        self.assertEqual((products["Mbizi"]["remaining_hectares"], products["Shumba"]["remaining_hectares"], products["Compound D"]["remaining_hectares"]), ("3.00", "3.00", "10.00"))

    def test_approval_is_all_or_nothing(self):
        request_id = self.build()
        self.leader.post(reverse("lead-request-submit", kwargs={"pk": request_id}))
        FarmerSubscription.objects.filter(farmer=self.rudo).update(paid_amount=0, outstanding_amount=500, payment_status="UNPAID")
        refused = self.officer.post(reverse("lead-request-approve", kwargs={"pk": request_id}), {}, format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Rudo Moyo", str(refused.data))
        self.assertEqual(InputAllocation.objects.count(), 0)
        self.assertEqual(LeadRequest.objects.get(pk=request_id).status, LeadRequest.STATUS_SUBMITTED)

    def test_rejected_request_can_be_corrected_and_resubmitted(self):
        request_id = self.build()
        self.leader.post(reverse("lead-request-submit", kwargs={"pk": request_id}))
        self.assertEqual(self.officer.post(reverse("lead-request-reject", kwargs={"pk": request_id}), {}, format="json").status_code, 400)
        rejected = self.officer.post(reverse("lead-request-reject", kwargs={"pk": request_id}), {"notes": "Rudo's hectares are too high"}, format="json")
        self.assertEqual(rejected.data["status"], "REJECTED")
        line = next(item for item in rejected.data["lines"] if item["farmer_name"] == "Rudo Moyo")
        changed = self.leader.patch(reverse("lead-request-line-detail", kwargs={"pk": line["id"]}), {"hectares": "2"}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(self.leader.post(reverse("lead-request-submit", kwargs={"pk": request_id})).data["status"], "SUBMITTED")

    def test_lead_farmers_see_only_their_own_cluster(self):
        self.build()
        other = User.objects.create_user(email="other@example.com", username="other-lead", password="Str0ng!Passw0rd", role=User.ROLE_LEAD_FARMER, assigned_cluster=self.other_cluster)
        client = APIClient()
        client.force_authenticate(other)
        self.assertEqual(client.get(reverse("lead-request-list")).data["results"], [])
        self.assertEqual(len(self.officer.get(reverse("lead-request-list")).data["results"]), 1)
