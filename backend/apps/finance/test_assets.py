from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Asset, AssetCategory, Expense, JournalEntry

User = get_user_model()


class AssetRegisterTests(APITestCase):
    def setUp(self):
        self.officer = User.objects.create_user(
            email="assets@example.test", username="asset-finance", password="StrongPass123!", role=User.ROLE_FINANCE_OFFICER
        )
        self.auditor = User.objects.create_user(
            email="asset-audit@example.test", username="asset-auditor", password="StrongPass123!", role=User.ROLE_AUDITOR
        )
        self.viewer = User.objects.create_user(
            email="asset-view@example.test", username="asset-viewer", password="StrongPass123!", role=User.ROLE_VIEWER
        )
        self.executive = User.objects.create_user(
            email="asset-exec@example.test", username="asset-exec", password="StrongPass123!", role=User.ROLE_SGR_EXECUTIVE
        )
        self.category, _created = AssetCategory.objects.get_or_create(
            name="Agricultural Equipment", defaults={"description": "Equipment used in agricultural operations."}
        )
        self.client.force_authenticate(self.officer)

    def payload(self, **overrides):
        data = {
            "name": "Grain scale",
            "description": "Platform scale for the depot",
            "category": self.category.pk,
            "purchase_date": "2026-03-01",
            "supplier": "Depot Supplies",
            "cost": "1200.00",
            "current_value": "1100.00",
            "location": "Harare depot",
            "department": "Operations",
            "responsible_person": "Stores clerk",
            "condition": "NEW",
            "status": "ACTIVE",
            "depreciation_method": "STRAIGHT_LINE",
            "useful_life_years": "5.00",
            "residual_value": "0.00",
            "accumulated_depreciation": "0.00",
            "notes": "Recorded from the supplier invoice.",
        }
        data.update(overrides)
        return data

    def test_register_calculates_depreciation_without_posting_a_journal(self):
        journals = JournalEntry.objects.count()
        expenses = Expense.objects.count()
        created = self.client.post(reverse("asset-list"), self.payload(), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(created.data["asset_id"].startswith("AST-"))
        self.assertEqual(created.data["annual_depreciation"], "240.00")
        self.assertEqual(created.data["depreciation_rate"], "20.0000")
        self.assertEqual(created.data["net_book_value"], "1200.00")
        self.assertEqual(created.data["category_name"], "Agricultural Equipment")
        self.assertEqual(JournalEntry.objects.count(), journals)
        self.assertEqual(Expense.objects.count(), expenses)
        asset = Asset.objects.get(pk=created.data["id"])
        self.assertEqual(asset.cost, Decimal("1200.00"))
        self.assertEqual(asset.valuations.filter(kind="ACQUISITION").get().amount, Decimal("1200.00"))
        self.assertEqual(asset.valuations.filter(kind="REVALUATION").get().amount, Decimal("1100.00"))
        self.assertTrue(asset.audit_events.filter(action="REGISTERED").exists())

    def test_straight_line_rounds_half_up_and_reducing_balance_uses_the_rate(self):
        uneven = self.client.post(
            reverse("asset-list"),
            self.payload(name="Pump", cost="1000.00", current_value="1000.00", useful_life_years="3.00", asset_id="AST-PUMP"),
            format="json",
        )
        self.assertEqual(uneven.status_code, 201, uneven.data)
        self.assertEqual(uneven.data["annual_depreciation"], "333.33")
        self.assertEqual(uneven.data["depreciation_rate"], "33.3333")
        reducing = self.client.post(
            reverse("asset-list"),
            self.payload(
                name="Trailer",
                asset_id="AST-TRAILER",
                cost="1000.00",
                current_value="1000.00",
                depreciation_method="REDUCING_BALANCE",
                depreciation_rate="20",
                useful_life_years=None,
            ),
            format="json",
        )
        self.assertEqual(reducing.status_code, 201, reducing.data)
        self.assertEqual(reducing.data["annual_depreciation"], "200.00")
        self.assertEqual(reducing.data["depreciation_rate"], "20.0000")
        self.assertEqual(reducing.data["net_book_value"], "1000.00")

    def test_permissions_search_and_summary(self):
        created = self.client.post(reverse("asset-list"), self.payload(location="Mutare branch"), format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.client.force_authenticate(self.auditor)
        listed = self.client.get(reverse("asset-list"), {"search": "Grain", "location": "Mutare", "condition": "NEW", "status": "ACTIVE", "category": self.category.pk})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["count"], 1)
        blocked = self.client.post(reverse("asset-list"), self.payload(name="Second scale"), format="json")
        self.assertEqual(blocked.status_code, 403)
        summary = self.client.get(reverse("asset-summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["total_assets"], 1)
        self.assertEqual(summary.data["total_acquisition_value"], "1200.00")
        self.assertEqual(summary.data["total_current_value"], "1100.00")
        self.assertEqual(summary.data["under_maintenance"], 0)
        self.assertEqual(summary.data["by_category"][0]["category"], "Agricultural Equipment")
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(reverse("asset-list")).status_code, 403)

    def test_maintenance_transfer_and_disposal_do_not_touch_expenses(self):
        created = self.client.post(reverse("asset-list"), self.payload(), format="json")
        asset_id = created.data["id"]
        expenses = Expense.objects.count()
        journals = JournalEntry.objects.count()
        maintained = self.client.post(
            reverse("asset-maintenance", args=[asset_id]),
            {"activity_date": "2026-04-02", "description": "Calibration", "cost": "15.50", "supplier": "Scale services"},
            format="json",
        )
        self.assertEqual(maintained.status_code, 201, maintained.data)
        self.assertEqual(maintained.data["cost"], "15.50")
        transferred = self.client.post(
            reverse("asset-transfer", args=[asset_id]),
            {"transfer_date": "2026-05-01", "to_location": "Bulawayo branch", "to_department": "Stores", "to_person": "Depot supervisor"},
            format="json",
        )
        self.assertEqual(transferred.status_code, 201, transferred.data)
        detail = self.client.get(reverse("asset-detail", args=[asset_id]))
        self.assertEqual(detail.data["location"], "Bulawayo branch")
        self.assertEqual(detail.data["responsible_person"], "Depot supervisor")
        disposed = self.client.post(
            reverse("asset-dispose", args=[asset_id]),
            {"kind": "DISPOSED", "disposed_on": "2026-06-01", "reason": "Sold after replacement.", "proceeds": "400.00"},
            format="json",
        )
        self.assertEqual(disposed.status_code, 201, disposed.data)
        self.assertEqual(self.client.get(reverse("asset-detail", args=[asset_id])).data["status"], "DISPOSED")
        again = self.client.post(
            reverse("asset-dispose", args=[asset_id]),
            {"kind": "WRITTEN_OFF", "disposed_on": "2026-06-02", "reason": "Already sold.", "proceeds": "0.00"},
            format="json",
        )
        self.assertEqual(again.status_code, 400)
        history = self.client.get(reverse("asset-history", args=[asset_id]))
        self.assertEqual(history.data["disposal"]["proceeds"], "400.00")
        self.assertEqual(len(history.data["maintenance"]), 1)
        self.assertEqual(len(history.data["transfers"]), 1)
        self.assertTrue(any(event["action"] == "DISPOSAL" for event in history.data["audit"]))
        self.assertEqual(Expense.objects.count(), expenses)
        self.assertEqual(JournalEntry.objects.count(), journals)
        self.client.force_authenticate(self.auditor)
        self.assertEqual(self.client.post(reverse("asset-transfer", args=[asset_id]), {"transfer_date": "2026-07-01", "to_location": "Gweru"}, format="json").status_code, 403)

    def test_supporting_document_is_stored(self):
        created = self.client.post(reverse("asset-list"), self.payload(asset_id="AST-DOC"), format="json")
        upload = SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 receipt", content_type="application/pdf")
        attached = self.client.post(
            reverse("asset-documents", args=[created.data["id"]]),
            {"title": "Supplier receipt", "file": upload},
            format="multipart",
        )
        self.assertEqual(attached.status_code, 201, attached.data)
        self.assertIn("finance/assets/", attached.data["file"])
        documents = self.client.get(reverse("asset-documents", args=[created.data["id"]]))
        self.assertEqual(documents.status_code, 200)
        self.assertEqual(documents.data[0]["title"], "Supplier receipt")

    def test_administrators_configure_categories(self):
        self.assertEqual(self.client.get(reverse("asset-category-list")).status_code, 200)
        refused = self.client.post(reverse("asset-category-list"), {"name": "Temporary stores", "description": ""}, format="json")
        self.assertEqual(refused.status_code, 403)
        self.client.force_authenticate(self.executive)
        created = self.client.post(reverse("asset-category-list"), {"name": "Temporary stores", "description": "Short-term storage equipment."}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(AssetCategory.objects.filter(name="Temporary stores").exists())
        removed = self.client.delete(reverse("asset-category-detail", args=[created.data["id"]]))
        self.assertEqual(removed.status_code, 204)
