from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.farmers.models import Farmer
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.geography.models import District, Province, Ward
from apps.programmes.models import Programme, Season
from apps.farmers.models import Farm
from apps.inputs.models import InputAllocation
from apps.subscriptions.models import FarmerSubscription
from apps.arda_requests.models import ARDARequestBatch

User = get_user_model()


class ARDARequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="arda@example.com",
            username="arda-user",
            password="StrongPass123!",
            first_name="Kudakwashe",
            last_name="Mapfumo",
            role=User.ROLE_PROGRAMME_OFFICER,
        )
        self.province = Province.objects.create(name="Mashonaland East", code="ME")
        self.district = District.objects.create(province=self.province, name="Marondera")
        self.ward = Ward.objects.create(district=self.district, name="Ward 3")
        self.farmer = Farmer.objects.create(
            first_name="Munashe",
            surname="Kuwaza",
            national_id="63-3344556-Z-10",
            phone_primary="0771234567",
            email="munashe@example.com",
            province=self.province,
            district=self.district,
            ward=self.ward,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_arda_request_can_be_created(self):
        url = reverse("arda-request-list")
        response = self.client.post(
            url,
            {
                "farmer": self.farmer.id,
                "request_type": "SEED",
                "quantity": 20,
                "unit": "bags",
                "reason": "Seed support for planting",
                "status": "PENDING",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["request_type"], "SEED")

    def test_ineligible_farmer_cannot_be_added_to_new_request_batch(self):
        season = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="SGR 200HA+ 2026/27", code="SGR-200HA-2026", season=season,
            announced_hectares="20000.00", status=Programme.STATUS_OPEN,
        )
        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "requested_hectares": "100.00", "season": season.pk},
            format="json",
        )
        self.assertEqual(batch_response.status_code, 201)
        self.assertEqual(batch_response.data["request_number"], "SGR1000")

        response = self.client.post(
            reverse("arda-farmer-request-list"),
            {"request_batch": batch_response.data["id"], "farmer": self.farmer.pk, "requested_hectares": "10.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("ineligible", str(response.data).lower())

    def test_eligible_farmer_request_can_be_approved_within_capacity(self):
        season = Season.objects.create(name="Approved 2026/27", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Kuwaza Farm", province=self.province, district=self.district,
            ward=self.ward, total_hectares="12.00", arable_hectares="10.00", verification_status="VERIFIED",
        )
        self.farmer.verification_status = Farmer.STATUS_VERIFIED
        self.farmer.save(update_fields=["verification_status"])
        FarmerSubscription.objects.create(
            farmer=self.farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="500.00",
            outstanding_amount="0.00", payment_status="PAID", season=season.name,
        )
        programme = Programme.objects.create(
            name="Approval Programme", code="APPROVAL-PROG", season=season, announced_hectares="20000.00",
        )
        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "requested_hectares": "100.00", "season": season.pk},
            format="json",
        )
        line_response = self.client.post(
            reverse("arda-farmer-request-list"),
            {
                "request_batch": batch_response.data["id"], "farmer": self.farmer.pk, "farm": farm.pk,
                "requested_hectares": "8.00",
            },
            format="json",
        )
        self.assertEqual(line_response.status_code, 201, line_response.data)
        batch = ARDARequestBatch.objects.get(pk=batch_response.data["id"])
        self.assertEqual(batch.requested_hectares, Decimal("100.00"))
        self.assertEqual(batch.total_requested_hectares, Decimal("8.00"))

        approval = self.client.post(
            reverse("arda-farmer-request-approve", kwargs={"pk": line_response.data["id"]}),
            {"approved_hectares": "8.00"},
            format="json",
        )

        self.assertEqual(approval.status_code, 200, approval.data)
        programme.refresh_from_db()
        self.assertEqual(programme.total_allocated_hectares, 8)

    def test_paid_and_verified_farmer_can_be_added_without_farm_verification_gate(self):
        season = Season.objects.create(name="ARDA Gate Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Kuwaza Pending Farm", province=self.province, district=self.district,
            ward=self.ward, total_hectares="12.00", arable_hectares="10.00", verification_status="PENDING",
        )
        self.farmer.verification_status = Farmer.STATUS_VERIFIED
        self.farmer.save(update_fields=["verification_status"])
        FarmerSubscription.objects.create(
            farmer=self.farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="500.00",
            outstanding_amount="0.00", payment_status="PAID", season=season.name,
        )
        programme = Programme.objects.create(
            name="ARDA Gate Programme", code="ARDA-GATE-PROG", season=season, announced_hectares="1000.00",
        )
        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "requested_hectares": "100.00", "season": season.pk},
            format="json",
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.data)

        root = reverse("farmer-eligible")
        eligible_response = self.client.get(root, {"season": season.name, "page_size": 20})
        self.assertEqual(eligible_response.status_code, 200, eligible_response.data)
        self.assertIn(self.farmer.pk, {row["id"] for row in eligible_response.data["results"]})

        line_response = self.client.post(
            reverse("arda-farmer-request-list"),
            {
                "request_batch": batch_response.data["id"],
                "farmer": self.farmer.pk,
                "farm": farm.pk,
                "requested_hectares": "8.00",
            },
            format="json",
        )

        self.assertEqual(line_response.status_code, 201, line_response.data)
        self.assertEqual(line_response.data["status"], "PENDING")

    def test_partial_or_unpaid_farmer_is_rejected_for_arda_request(self):
        season = Season.objects.create(name="ARDA Status Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="ARDA Status Programme", code="ARDA-STATUS-PROG", season=season, announced_hectares="1000.00",
        )
        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "requested_hectares": "100.00", "season": season.pk},
            format="json",
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.data)

        for index, status in enumerate(["PARTIAL", "UNPAID"]):
            with self.subTest(status=status):
                farmer = Farmer.objects.create(
                    first_name=f"Status{index}", surname="Farmer", national_id=f"63-998877{index}-Z-10",
                    phone_primary=f"077112233{index}", province=self.province, district=self.district, ward=self.ward,
                    verification_status=Farmer.STATUS_VERIFIED,
                )
                farm = Farm.objects.create(
                    farmer=farmer, farm_name=f"Status Farm {index}", province=self.province, district=self.district,
                    ward=self.ward, total_hectares="10.00", arable_hectares="8.00", verification_status="VERIFIED",
                )
                FarmerSubscription.objects.create(
                    farmer=farmer,
                    category="UNDER_200HA",
                    expected_amount="500.00",
                    paid_amount="250.00" if status == "PARTIAL" else "0.00",
                    outstanding_amount="250.00" if status == "PARTIAL" else "500.00",
                    payment_status=status,
                    season=season.name,
                )

                root = reverse("farmer-eligible")
                eligible_response = self.client.get(root, {"season": season.name, "page_size": 20})
                self.assertEqual(eligible_response.status_code, 200, eligible_response.data)
                self.assertNotIn(farmer.pk, {row["id"] for row in eligible_response.data["results"]})

                line_response = self.client.post(
                    reverse("arda-farmer-request-list"),
                    {
                        "request_batch": batch_response.data["id"],
                        "farmer": farmer.pk,
                        "farm": farm.pk,
                        "requested_hectares": "2.00",
                    },
                    format="json",
                )
                self.assertEqual(line_response.status_code, 400)
                self.assertIn("ineligible", str(line_response.data).lower())

    def test_batch_number_is_generated_and_never_reused_after_delete(self):
        season = Season.objects.create(name="Number Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Number Programme", code="NUMBER-PROG", season=season, announced_hectares="1000.00",
        )
        url = reverse("arda-request-batch-list")
        first = self.client.post(
            url,
            {"request_number": "MANUAL-IGNORED", "programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "200.00"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["request_number"], "SGR1000")
        self.assertEqual(first.data["requested_hectares"], "200.00")

        deleted = self.client.delete(reverse("arda-request-batch-detail", kwargs={"pk": first.data["id"]}))
        self.assertEqual(deleted.status_code, 204)
        second = self.client.post(
            url,
            {"programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "200.00"},
            format="json",
        )

        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["request_number"], "SGR1001")
        self.assertNotEqual(first.data["request_number"], second.data["request_number"])

    def test_batch_number_continues_after_existing_sequential_reference(self):
        season = Season.objects.create(name="Existing Number Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Existing Number Programme", code="EXISTING-NUMBER-PROG", season=season,
            announced_hectares="1000.00",
        )
        ARDARequestBatch.objects.create(
            request_number="SGR1042", programme=programme, season=season, requested_hectares="10.00", status=ARDARequestBatch.STATUS_REJECTED,
        )

        response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "requested_hectares": "10.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["request_number"], "SGR1043")

    def test_batch_requested_hectares_must_be_positive_and_within_programme_capacity(self):
        season = Season.objects.create(name="Capacity Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Capacity Programme", code="CAPACITY-PROG", season=season, announced_hectares="100.00",
        )
        url = reverse("arda-request-batch-list")

        for amount in ("0.00", "-1.00", "100.01"):
            with self.subTest(amount=amount):
                response = self.client.post(
                    url,
                    {"programme": programme.pk, "season": season.pk, "requested_hectares": amount},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("requested_hectares", response.data)

    def test_batch_capacity_uses_other_active_batches(self):
        season = Season.objects.create(name="Cumulative Capacity Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Cumulative Capacity", code="CUMULATIVE-CAPACITY", season=season, announced_hectares="100.00",
        )
        created = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "requested_hectares": "75.00"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        rejected = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "requested_hectares": "26.00"},
            format="json",
        )
        self.assertEqual(rejected.status_code, 400)

    def test_batch_update_preserves_generated_request_number(self):
        season = Season.objects.create(name="Update Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Update Programme", code="UPDATE-PROG", season=season, announced_hectares="100.00",
        )
        created = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "20.00"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        updated = self.client.patch(
            reverse("arda-request-batch-detail", kwargs={"pk": created.data["id"]}),
            {"requested_hectares": "25.00", "request_number": "MANUAL-OVERRIDE"},
            format="json",
        )

        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["request_number"], created.data["request_number"])
        self.assertEqual(updated.data["requested_hectares"], "25.00")
        self.assertEqual(ARDARequestBatch.objects.count(), 1)

    def test_only_paid_current_season_farmers_appear_in_eligible_search(self):
        season = Season.objects.create(name="Eligibility Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        candidates = []
        for index, (first_name, paid_amount, payment_season) in enumerate([
            ("Tariro", "500.00", season.name),
            ("Takudzwa", "500.00", season.name),
            ("Tinashe", "250.00", season.name),
            ("Tawanda", "500.00", "Previous Season"),
            ("Tendai", "500.00", season.name),
        ]):
            farmer = Farmer.objects.create(
                first_name=first_name, surname="Search Farmer", national_id=f"63-334455{index}-Z-10",
                phone_primary=f"077123456{index}", province=self.province, district=self.district, ward=self.ward,
                verification_status=Farmer.STATUS_VERIFIED,
            )
            Farm.objects.create(
                farmer=farmer, farm_name=f"{first_name} Farm", province=self.province, district=self.district,
                ward=self.ward, total_hectares="20.00", arable_hectares="10.00", verification_status="VERIFIED",
            )
            FarmerSubscription.objects.create(
                farmer=farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount=paid_amount,
                outstanding_amount=str(Decimal("500.00") - Decimal(paid_amount)),
                payment_status=(
                    "PARTIAL" if first_name == "Tendai"
                    else "PAID" if paid_amount == "500.00"
                    else "PARTIAL"
                ),
                season=payment_season,
            )
            candidates.append(farmer)

        root = reverse("farmer-eligible")
        t_response = self.client.get(root, {"search": "t", "season": season.name, "page_size": 20})
        ta_response = self.client.get(root, {"search": "ta", "season": season.name, "page_size": 20})
        tak_response = self.client.get(root, {"search": "tak", "season": season.name, "page_size": 20})

        self.assertEqual(t_response.status_code, 200, t_response.data)
        self.assertEqual({row["id"] for row in t_response.data["results"]}, {candidates[0].pk, candidates[1].pk})
        self.assertTrue(all(row["subscription_status"] == "PAID" for row in t_response.data["results"]))
        self.assertEqual({row["id"] for row in ta_response.data["results"]}, {candidates[0].pk, candidates[1].pk})
        self.assertEqual([row["id"] for row in tak_response.data["results"]], [candidates[1].pk])
        self.assertFalse(FarmerApprovalEligibilityService.evaluate_for_arda(candidates[4], season)["eligible"])

    def test_paid_but_unverified_farmer_is_not_eligible_for_arda(self):
        season = Season.objects.create(name="Verification Gate Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Unverified Farmer Farm", province=self.province, district=self.district,
            ward=self.ward, total_hectares="12.00", arable_hectares="10.00", verification_status="VERIFIED",
        )
        FarmerSubscription.objects.create(
            farmer=self.farmer, category="UNDER_200HA", expected_amount="500.00", paid_amount="500.00",
            outstanding_amount="0.00", payment_status="PAID", season=season.name,
        )
        programme = Programme.objects.create(
            name="Verification Gate Programme", code="VERIFY-GATE-PROG", season=season, announced_hectares="1000.00",
        )
        batch_response = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "requested_hectares": "100.00", "season": season.pk},
            format="json",
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.data)

        root = reverse("farmer-eligible")
        eligible_response = self.client.get(root, {"season": season.name, "page_size": 20})
        self.assertEqual(eligible_response.status_code, 200, eligible_response.data)
        self.assertNotIn(self.farmer.pk, {row["id"] for row in eligible_response.data["results"]})

        line_response = self.client.post(
            reverse("arda-farmer-request-list"),
            {
                "request_batch": batch_response.data["id"],
                "farmer": self.farmer.pk,
                "farm": farm.pk,
                "requested_hectares": "3.00",
            },
            format="json",
        )

        self.assertEqual(line_response.status_code, 400)
        self.assertIn("verified", str(line_response.data).lower())

    def test_duplicate_active_request_for_same_season_programme_crop_is_rejected(self):
        season = Season.objects.create(name="Duplicate Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Duplicate Programme", code="DUPLICATE-PROG", season=season, announced_hectares="5000.00",
        )

        first = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "200.00"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.data)

        duplicate = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "crop": "maize", "requested_hectares": "100.00"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already exists", str(duplicate.data).lower())
        self.assertIn("edit", str(duplicate.data).lower())

    def test_batch_response_shows_dynamic_allocated_available_and_unique_farmers(self):
        season = Season.objects.create(name="Snapshot Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Snapshot Programme", code="SNAPSHOT-PROG", season=season, announced_hectares="30000.00",
        )
        batch = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "20000.00"},
            format="json",
        )
        self.assertEqual(batch.status_code, 201, batch.data)

        farmer_two = Farmer.objects.create(
            first_name="Memory", surname="Farmer", national_id="63-9981001-Z-10", phone_primary="0778900001",
            province=self.province, district=self.district, ward=self.ward,
        )
        farm_one = Farm.objects.create(
            farmer=self.farmer, farm_name="Snapshot Farm 1", province=self.province, district=self.district,
            ward=self.ward, total_hectares="30.00", arable_hectares="30.00", verification_status="VERIFIED",
        )
        farm_two = Farm.objects.create(
            farmer=farmer_two, farm_name="Snapshot Farm 2", province=self.province, district=self.district,
            ward=self.ward, total_hectares="40.00", arable_hectares="40.00", verification_status="VERIFIED",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, farm=farm_one, programme=programme, crop="Maize", hectares="100.00",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, farm=farm_one, programme=programme, crop="Maize", hectares="20.00",
        )
        InputAllocation.objects.create(
            farmer=farmer_two, farm=farm_two, programme=programme, crop="Maize", hectares="50.00",
        )

        snapshot = self.client.get(reverse("arda-request-batch-list"), {"season": season.pk, "page_size": 20})
        self.assertEqual(snapshot.status_code, 200, snapshot.data)
        row = snapshot.data["results"][0]
        self.assertEqual(row["id"], batch.data["id"])
        self.assertEqual(row["allocated_hectares"], Decimal("170.00"))
        self.assertEqual(row["available_hectares"], Decimal("19830.00"))
        self.assertEqual(row["total_farmers"], 2)

    def test_batch_requested_hectares_cannot_be_reduced_below_allocated(self):
        season = Season.objects.create(name="Edit Floor Season", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(
            name="Edit Floor Programme", code="EDIT-FLOOR-PROG", season=season, announced_hectares="1000.00",
        )
        batch = self.client.post(
            reverse("arda-request-batch-list"),
            {"programme": programme.pk, "season": season.pk, "crop": "Maize", "requested_hectares": "200.00"},
            format="json",
        )
        self.assertEqual(batch.status_code, 201, batch.data)
        farm = Farm.objects.create(
            farmer=self.farmer, farm_name="Edit Floor Farm", province=self.province, district=self.district,
            ward=self.ward, total_hectares="20.00", arable_hectares="20.00", verification_status="VERIFIED",
        )
        InputAllocation.objects.create(
            farmer=self.farmer,
            farm=farm,
            programme=programme,
            crop="Maize",
            hectares="100.00",
        )

        reduced = self.client.patch(
            reverse("arda-request-batch-detail", kwargs={"pk": batch.data["id"]}),
            {"requested_hectares": "50.00"},
            format="json",
        )
        self.assertEqual(reduced.status_code, 400)
        self.assertIn("already allocated", str(reduced.data).lower())

    def test_past_season_batch_edit_is_rejected(self):
        season = Season.objects.create(name="Closed Season", start_date="2025-10-01", end_date="2026-09-30", status=Season.STATUS_CLOSED)
        programme = Programme.objects.create(
            name="Closed Programme", code="CLOSED-PROG", season=season, announced_hectares="1000.00",
        )
        batch = ARDARequestBatch.objects.create(
            request_number="SGR1999",
            programme=programme,
            season=season,
            crop="Maize",
            requested_hectares="200.00",
        )

        response = self.client.patch(
            reverse("arda-request-batch-detail", kwargs={"pk": batch.pk}),
            {"requested_hectares": "250.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("active season", str(response.data).lower())

    def test_empty_batch_can_be_deleted_but_a_batch_with_farmers_cannot(self):
        season = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status=Season.STATUS_ACTIVE)
        programme = Programme.objects.create(name="Delete Programme", code="DEL-PROG", season=season, announced_hectares="1000.00", status=Programme.STATUS_OPEN)
        empty = self.client.post(reverse("arda-request-batch-list"), {"programme": programme.pk, "season": season.pk, "requested_hectares": "20.00"}, format="json")
        self.assertEqual(empty.status_code, 201, empty.data)
        deleted = self.client.delete(reverse("arda-request-batch-detail", args=[empty.data["id"]]))
        self.assertEqual(deleted.status_code, 204)
        kept = ARDARequestBatch.objects.create(request_number="SGR1888", programme=programme, season=season, crop="Maize", requested_hectares="10.00")
        from apps.arda_requests.models import ARDAFarmerRequest
        ARDAFarmerRequest.objects.create(request_batch=kept, farmer=self.farmer, requested_hectares="5.00")
        blocked = self.client.delete(reverse("arda-request-batch-detail", args=[kept.pk]))
        self.assertEqual(blocked.status_code, 400)
        self.assertTrue(ARDARequestBatch.objects.filter(pk=kept.pk).exists())
