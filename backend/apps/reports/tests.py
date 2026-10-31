from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


class ReportTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reports@example.com",
            username="reports-user",
            password="StrongPass123!",
            first_name="Nyasha",
            last_name="Chikuruwo",
            role=User.ROLE_AUDITOR,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_report_template_can_be_created(self):
        url = reverse("report-template-list")
        response = self.client.post(
            url,
            {
                "name": "Farmer Verification Summary",
                "code": "FARMER-VERIFICATION-SUMMARY",
                "description": "Summary of verification outcomes",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "FARMER-VERIFICATION-SUMMARY")


class ReportingCentreTests(TestCase):
    def setUp(self):
        from datetime import date
        from decimal import Decimal

        from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
        from apps.farmers.models import Farm, Farmer
        from apps.finance.models import AccountingPeriod, Asset, JournalEntry, JournalLine, LedgerAccount
        from apps.geography.models import District, Province, Ward
        from apps.inputs.models import InputAllocation, InputAllocationLine
        from apps.production.models import FarmerProduction, GMBDelivery
        from apps.programmes.models import Crop, CropInputRequirement, Programme, ProgrammeAllocation, Season
        from apps.recovery.models import InputDebt
        from apps.subscriptions.models import FarmerSubscription, SubscriptionPayment

        self.date = date
        self.decimal = Decimal
        self.auditor = User.objects.create_user(
            email="centre@example.com", username="centre-user", password="StrongPass123!",
            role=User.ROLE_AUDITOR,
        )
        self.viewer = User.objects.create_user(
            email="viewer@example.com", username="viewer-user", password="StrongPass123!",
            role=User.ROLE_VIEWER,
        )
        self.province = Province.objects.create(name="Midlands", code="MD")
        self.other_province = Province.objects.create(name="Manicaland", code="MN")
        self.district = District.objects.create(province=self.province, name="Gweru", code="GW")
        self.other_district = District.objects.create(province=self.other_province, name="Mutare", code="MU")
        self.ward = Ward.objects.create(district=self.district, name="Ward 4")
        self.coordinator = User.objects.create_user(
            email="coord@example.com", username="coord-user", password="StrongPass123!",
            role=User.ROLE_DISTRICT_COORDINATOR, district=self.district,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.auditor)
        self.farmer = Farmer.objects.create(
            first_name="Yusufu", surname="=cmd", national_id="63-2000000-A-00", phone_primary="0772000000",
            province=self.province, district=self.district, ward=self.ward, gender="Male",
            membership_number="SGR-MD-000001", verification_status="VERIFIED",
        )
        self.other = Farmer.objects.create(
            first_name="Rudo", surname="Dube", national_id="63-2000001-B-00", phone_primary="0772000001",
            province=self.other_province, district=self.other_district, gender="Female",
            membership_number="SGR-MN-000002", verification_status="PENDING",
        )
        self.farm = Farm.objects.create(
            farmer=self.farmer, farm_name='North, "A"', province=self.province, district=self.district,
            ward=self.ward, total_hectares="8.00", arable_hectares="6.50", verification_status="VERIFIED",
        )
        Farm.objects.create(
            farmer=self.farmer, farm_name="South", province=self.province, district=self.district,
            ward=self.ward, total_hectares="2.00", arable_hectares="1.50", verification_status="VERIFIED",
        )
        self.season = Season.objects.create(name="2026/2027", start_date="2026-10-01", end_date="2027-09-30", status="ACTIVE")
        crop = Crop.objects.create(name="Maize", category="SUMMER", active=True)
        Crop.objects.create(name="Wheat", category="WINTER", active=True)
        CropInputRequirement.objects.create(
            crop=crop, group_name="Chemicals", item_name="Glyphosate", rate_per_hectare="2.0000",
            unit="L", cost_per_unit="7.70", cost_per_hectare="15.4000", active=True, include_in_input_cost=True,
        )
        programme = Programme.objects.create(
            name="Maize Programme", code="MAIZE-26", season=self.season, crop="Maize",
            announced_hectares="20.00", total_allocated_hectares="5.00", status="OPEN",
        )
        ProgrammeAllocation.objects.create(programme=programme, farmer=self.farmer, input_type="SEED", quantity="4.00", unit="bags")
        batch = ARDARequestBatch.objects.create(
            request_number="SGR1001", programme=programme, season=self.season, crop="Maize",
            requested_hectares="5.00", total_farmers=1, total_requested_hectares="5.00",
        )
        ARDAFarmerRequest.objects.create(
            request_batch=batch, farmer=self.farmer, farm=self.farm, requested_hectares="5.00", approved_hectares="4.00",
        )
        allocation = InputAllocation.objects.create(
            farmer=self.farmer, farm=self.farm, programme=programme, crop="Maize", hectares="5.00",
            quantity="10.00", unit="bags", calculated_input_cost_per_hectare="15.40", total_input_cost="77.00",
            allocation_reference="ALLOC-1",
        )
        InputAllocationLine.objects.create(
            allocation=allocation, group_name="Chemicals", item_name="Glyphosate", unit="L",
            rate_per_hectare="2.0000", cost_per_unit="7.70", cost_per_hectare="15.4000",
            required_quantity="10.0000", calculated_cost="77.00",
        )
        FarmerProduction.objects.create(
            farmer=self.farmer, farm=self.farm, season=self.season, crop="Maize",
            contracted_hectares="5.00", planted_hectares="4.00", planting_date="2026-11-15",
            expected_yield="8.00", estimated_production="32.00", actual_production="20.00", status="PLANTED",
        )
        GMBDelivery.objects.create(
            farmer=self.farmer, farm=self.farm, season=self.season, crop="Maize", delivery_date="2027-04-20",
            gmb_depot="GMB Gweru", delivery_reference="REF-20", ticket_number="GMB-20",
            tonnes="2.00", price="400.00", value="800.00", recovery_tonnes="1.00", amount_recovered="400.00",
        )
        InputDebt.objects.create(
            farmer=self.farmer, farm=self.farm, programme=programme, crop="Maize",
            input_value="2000.00", total_debt="2000.00", outstanding_monetary_balance="2000.00",
            selling_price_per_tonne="400.00", required_recovery_tonnes="5.00", outstanding_tonnes="5.00",
        )
        FarmerSubscription.objects.create(
            farmer=self.farmer, expected_amount="100.00", paid_amount="40.00", outstanding_amount="60.00",
            payment_status="PARTIAL", season="2026/2027", payment_date="2026-11-01",
        )
        SubscriptionPayment.objects.create(
            subscription=self.farmer.subscriptions.get(), amount="40.00", payment_date="2026-11-01",
            method="CASH", reference="SUB-40", idempotency_key="sub-40",
        )
        Asset.objects.create(asset_id="COM1", name="Computer", description="Office computer", category="Equipment", cost="999.00", purchase_date="2026-10-05", status="ACTIVE")
        period = AccountingPeriod.objects.create(name="Oct 2026", start_date="2026-10-01", end_date="2026-10-31")
        revenue = LedgerAccount.objects.create(code="4000", name="Subscription income", account_type="REVENUE", category="REVENUE", normal_balance="CREDIT")
        expense = LedgerAccount.objects.create(code="5000", name="Operations", account_type="EXPENSE", category="EXPENSE", normal_balance="DEBIT")
        entry = JournalEntry.objects.create(reference="JNL-1", entry_date="2026-10-20", description="October activity", period=period, status="POSTED", season=self.season)
        JournalLine.objects.create(entry=entry, account=revenue, credit="25.00")
        JournalLine.objects.create(entry=entry, account=expense, debit="25.00")

    def test_every_report_category_previews_database_records(self):
        catalogue = self.client.get(reverse("report-catalogue"))
        self.assertEqual(catalogue.status_code, 200, catalogue.data)
        codes = [report["code"] for report in catalogue.data["reports"]]
        categories = {report["category"] for report in catalogue.data["reports"]}
        self.assertGreaterEqual(len(categories), 13)
        for code in codes:
            response = self.client.get(reverse("report-preview", kwargs={"code": code}), {"page_size": 5})
            self.assertEqual(response.status_code, 200, (code, response.data))
            self.assertIn("count", response.data)
            self.assertIn("columns", response.data)

    def test_filters_exports_permissions_and_financial_totals(self):
        farmers = self.client.get(reverse("report-preview", kwargs={"code": "farmers-register"}), {"district": self.district.pk, "page_size": 1})
        self.assertEqual(farmers.status_code, 200, farmers.data)
        self.assertEqual(farmers.data["count"], 1)
        self.assertEqual(len(farmers.data["rows"]), 1)
        self.assertEqual(farmers.data["rows"][0]["surname"], "=cmd")
        self.assertEqual(farmers.data["summaries"][0]["value"], "1")

        winter = self.client.get(reverse("report-preview", kwargs={"code": "production-records"}), {"season": "WINTER", "agricultural_year": self.season.pk})
        self.assertEqual(winter.data["count"], 0)
        summer = self.client.get(reverse("report-preview", kwargs={"code": "production-records"}), {"season": "SUMMER", "agricultural_year": self.season.pk})
        self.assertEqual(summer.data["count"], 1)
        self.assertEqual(summer.data["rows"][0]["planted_hectares"], "4")
        self.assertEqual(summer.data["rows"][0]["actual_production"], "20")
        self.assertEqual(summer.data["rows"][0]["yield_per_hectare"], "5")

        delivery = self.client.get(reverse("report-preview", kwargs={"code": "deliveries-all"}), {"farmer": "SGR-MD-000001"})
        row = delivery.data["rows"][0]
        self.assertEqual(row["tonnes"], "2")
        self.assertEqual(row["recovery_tonnes"], "1")
        self.assertEqual(row["expected_tonnes"], "5")
        self.assertEqual(row["price"], "400.00")
        expected_total = next(item["value"] for item in delivery.data["summaries"] if item["label"] == "Total Expected tonnes to recover")
        self.assertEqual(expected_total, "5")

        income = self.client.get(reverse("report-preview", kwargs={"code": "finance-income"}))
        income_total = next(item["value"] for item in income.data["summaries"] if item["label"] == "Total Credit")
        self.assertEqual(income_total, "25.00")
        expenditure = self.client.get(reverse("report-preview", kwargs={"code": "finance-expenditure"}))
        expense_total = next(item["value"] for item in expenditure.data["summaries"] if item["label"] == "Total Debit")
        self.assertEqual(expense_total, "25.00")
        assets = self.client.get(reverse("report-preview", kwargs={"code": "finance-assets"}))
        self.assertEqual(assets.data["rows"][0]["cost"], "999.00")
        self.assertNotIn("quantity", assets.data["rows"][0])

        empty = self.client.get(reverse("report-preview", kwargs={"code": "farmers-register"}), {"membership": "NO-SUCH"})
        self.assertEqual(empty.data["count"], 0)
        self.assertEqual(empty.data["rows"], [])

        csv_response = self.client.get(reverse("report-export", kwargs={"code": "farmers-register"}), {"file_format": "csv"})
        self.assertEqual(csv_response.status_code, 200)
        csv_text = b"".join(csv_response.streaming_content).decode("utf-8-sig")
        self.assertIn("Membership number", csv_text)
        self.assertIn("'=cmd", csv_text)
        self.assertIn('"North, ""A"""', csv_text)
        self.assertEqual(csv_text.count("\n"), 3)
        pdf_response = self.client.get(reverse("report-export", kwargs={"code": "farmers-register"}), {"file_format": "pdf"})
        self.assertEqual(pdf_response.status_code, 200)
        self.assertTrue(pdf_response.content.startswith(b"%PDF"))
        self.assertNotIn(b"/Encrypt", pdf_response.content)
        self.assertIn(b"Complete farmer register", pdf_response.content)
        self.assertIn(b"Page 1 of", pdf_response.content)
        self.assertIn("SGR_Complete_Farmer_Register", pdf_response["Content-Disposition"])

        self.client.force_authenticate(user=self.viewer)
        denied = self.client.get(reverse("report-export", kwargs={"code": "finance-transactions"}), {"file_format": "csv"})
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(user=self.coordinator)
        scoped = self.client.get(reverse("report-preview", kwargs={"code": "farmers-register"}))
        self.assertEqual(scoped.data["count"], 1)
        self.assertEqual(scoped.data["rows"][0]["membership_number"], "SGR-MD-000001")
        blocked = self.client.get(reverse("report-export", kwargs={"code": "finance-assets"}), {"file_format": "pdf"})
        self.assertEqual(blocked.status_code, 403)

    def test_pdf_paginates_wide_reports(self):
        from apps.reports.pdf import build_pdf

        rows = [[f"Farmer {index}", "1.00"] for index in range(80)]
        content = build_pdf(title="Pagination", meta_lines=["Generated: 2026-10-31"], headers=["Farmer", "Hectares"], rows=rows, orientation="portrait")
        self.assertIn(b"/Count 2", content)
        self.assertIn(b"Page 2 of 2", content)
        self.assertNotIn(b"/Encrypt", content)
        start = content.rindex(b"startxref\n") + len(b"startxref\n")
        xref = int(content[start:content.index(b"\n", start)])
        self.assertTrue(content[xref:].startswith(b"xref\n"))

    def test_unpaid_subscription_report_uses_subscription_rules(self):
        from apps.farmers.models import Farmer
        from apps.subscriptions.models import FarmerSubscription

        paid = Farmer.objects.create(
            first_name="Paid", surname="Farmer", national_id="63-3000000-C-00", phone_primary="0773000000",
            province=self.province, district=self.district, membership_number="SGR-MD-000003",
        )
        FarmerSubscription.objects.create(
            farmer=paid, expected_amount="500.00", paid_amount="500.00", outstanding_amount="0.00",
            payment_status="", season="2026/2027",
        )
        blank = FarmerSubscription.objects.create(
            farmer=self.other, expected_amount="500.00", paid_amount="0.00", outstanding_amount="500.00",
            payment_status="", season="2025/2026",
        )
        self.assertEqual(blank.payment_status, "")

        unpaid = self.client.get(reverse("report-preview", kwargs={"code": "subscriptions-unpaid"}), {
            "agricultural_year": self.season.pk,
        })
        self.assertEqual(unpaid.status_code, 200, unpaid.data)
        memberships = {row["membership_number"] for row in unpaid.data["rows"]}
        self.assertIn("SGR-MN-000002", memberships)
        self.assertNotIn("SGR-MD-000003", memberships)
        self.assertNotIn("SGR-MD-000001", memberships)
        self.assertTrue(all(row["payment_status"] == "UNPAID" for row in unpaid.data["rows"]))
        self.assertTrue(all(row["national_id"] and row["phone_primary"] for row in unpaid.data["rows"]))
        self.assertEqual(unpaid.data["rows"][0]["crop_season"], "Shared by Summer and Winter")

        partial = self.client.get(reverse("report-preview", kwargs={"code": "subscriptions-partial"}), {
            "agricultural_year": self.season.pk,
        })
        self.assertEqual({row["membership_number"] for row in partial.data["rows"]}, {"SGR-MD-000001"})

        paid_report = self.client.get(reverse("report-preview", kwargs={"code": "subscriptions-paid"}), {
            "agricultural_year": self.season.pk, "province": self.province.pk,
        })
        self.assertEqual([row["membership_number"] for row in paid_report.data["rows"]], ["SGR-MD-000003"])
        other_province = self.client.get(reverse("report-preview", kwargs={"code": "subscriptions-unpaid"}), {
            "agricultural_year": self.season.pk, "province": self.other_province.pk,
        })
        self.assertNotIn("SGR-MD-000003", {row["membership_number"] for row in other_province.data["rows"]})
        self.assertIn("SGR-MN-000002", {row["membership_number"] for row in other_province.data["rows"]})

    def test_arda_report_matches_request_page_totals(self):
        from apps.arda_requests.models import ARDARequestBatch
        from apps.inputs.models import InputAllocation
        from apps.programmes.models import Programme

        programme = Programme.objects.create(
            name="National Maize", code="MAIZE-BIG", season=self.season, crop="Maize",
            announced_hectares="30000.00", status="OPEN",
        )
        ARDARequestBatch.objects.create(
            request_number="SGR1000", programme=programme, season=self.season, crop="Maize",
            requested_hectares="20000.00", total_farmers=0, total_requested_hectares="0.00",
        )
        InputAllocation.objects.create(
            farmer=self.farmer, farm=self.farm, programme=programme, crop="Maize", hectares="100.00",
            quantity="1.00", unit="bags", allocation_reference="ALLOC-BIG",
        )
        report = self.client.get(reverse("report-preview", kwargs={"code": "arda-requests"}), {
            "programme": programme.pk, "agricultural_year": self.season.pk, "season": "SUMMER",
        })
        self.assertEqual(report.status_code, 200, report.data)
        self.assertEqual(report.data["count"], 1)
        row = report.data["rows"][0]
        self.assertEqual(row["request_number"], "SGR1000")
        self.assertEqual(row["requested_hectares"], "20000")
        self.assertEqual(row["allocated_hectares"], "100")
        self.assertEqual(row["available_hectares"], "19900")
        self.assertEqual(row["farmer_count"], "1")
        self.assertEqual(row["crop_season"], "Summer")
        requested = next(item["value"] for item in report.data["summaries"] if item["label"] == "Total Requested hectares")
        farmers = next(item["value"] for item in report.data["summaries"] if item["label"] == "Total Farmers")
        self.assertEqual(requested, "20000")
        self.assertEqual(farmers, "1")
        export = self.client.get(reverse("report-export", kwargs={"code": "arda-requests"}), {
            "programme": programme.pk, "agricultural_year": self.season.pk, "season": "SUMMER", "file_format": "pdf",
        })
        self.assertIn("SGR_ARDA_Requests_2026-2027_Summer.pdf", export["Content-Disposition"])
        self.assertNotIn(b"/Encrypt", export.content)
        self.assertIn(b"20000", export.content)
        csv_export = self.client.get(reverse("report-export", kwargs={"code": "arda-requests"}), {
            "programme": programme.pk, "agricultural_year": self.season.pk, "season": "SUMMER", "file_format": "csv",
        })
        csv_text = b"".join(csv_export.streaming_content).decode("utf-8-sig")
        self.assertIn("20000", csv_text)
        self.assertEqual(csv_text.count("SGR1000"), 1)

