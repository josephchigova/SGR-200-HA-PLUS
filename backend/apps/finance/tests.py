from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.farmers.models import Farmer
from apps.subscriptions.models import FarmerSubscription

from .ledger import (
    account_by_code,
    cash_flow,
    ensure_default_chart,
    profit_and_loss,
    trial_balance,
)
from .models import AccountingPeriod, Asset, CashBookAccount, Expense, LedgerAccount, PayrollEntry, Receipt
from .workbook_statement import workbook_opening_position
from apps.source_data.models import DataBankEntry

User = get_user_model()


class LedgerApiTests(APITestCase):
    def setUp(self):
        ensure_default_chart()
        self.officer = User.objects.create_user(email="finance@example.test", username="finance-user", password="StrongPass123!", role=User.ROLE_FINANCE_OFFICER)
        self.viewer = User.objects.create_user(email="viewer@example.test", username="viewer-user", password="StrongPass123!", role=User.ROLE_VIEWER)
        self.executive = User.objects.create_user(email="exec@example.test", username="exec-user", password="StrongPass123!", role=User.ROLE_SGR_EXECUTIVE)
        self.client.force_authenticate(self.officer)
        self.client.post(reverse("accounting-period-list"), {"name": "FY2026", "start_date": "2026-01-01", "end_date": "2026-12-31"}, format="json")
        cash = LedgerAccount.objects.get(code="1000")
        bank = LedgerAccount.objects.get(code="1010")
        self.cash = CashBookAccount.objects.create(name="Till", kind="CASH", ledger_account=cash)
        self.bank = CashBookAccount.objects.create(name="Operating bank", kind="BANK", ledger_account=bank)

    def post_journal(self, lines, entry_date="2026-10-20", description="Test", post=True):
        return self.client.post(
            reverse("journal-list"),
            {"entry_date": entry_date, "description": description, "lines": lines, "post": post},
            format="json",
        )

    def test_unbalanced_journal_is_rejected_and_draft_is_excluded(self):
        revenue = LedgerAccount.objects.get(code="4000").pk
        cash = LedgerAccount.objects.get(code="1000").pk
        rejected = self.post_journal(
            [{"account": cash, "debit": "100.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "90.00"}]
        )
        self.assertEqual(rejected.status_code, 400)
        draft = self.post_journal(
            [{"account": cash, "debit": "50.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "50.00"}],
            post=False,
        )
        self.assertEqual(draft.status_code, 201)
        self.assertEqual(draft.data["status"], "DRAFT")
        statement = profit_and_loss(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(statement["total_revenue"], "0.00")
        self.assertEqual(trial_balance(date(2026, 10, 31))["total_debit"], "0.00")

    def test_posted_journal_balances_statements_and_cannot_be_deleted(self):
        revenue = LedgerAccount.objects.get(code="4000").pk
        cash = LedgerAccount.objects.get(code="1000").pk
        created = self.post_journal(
            [{"account": cash, "debit": "100.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "100.00"}]
        )
        self.assertEqual(created.status_code, 201, created.data)
        deleted = self.client.delete(reverse("journal-detail", args=[created.data["id"]]))
        self.assertEqual(deleted.status_code, 400)
        statement = self.client.get(reverse("finance-report", args=["profit-loss"]), {"start": "2026-10-01", "end": "2026-10-31"})
        self.assertEqual(statement.data["total_revenue"], "100.00")
        self.assertEqual(statement.data["net_profit"], "100.00")
        later = self.client.get(reverse("finance-report", args=["profit-loss"]), {"start": "2026-11-01", "end": "2026-11-30"})
        self.assertEqual(later.data["total_revenue"], "0.00")
        sheet = self.client.get(reverse("finance-report", args=["balance-sheet"]), {"as_of": "2026-10-31"})
        self.assertTrue(sheet.data["balanced"])
        self.assertEqual(sheet.data["total_assets"], "100.00")
        self.assertEqual(sheet.data["equation_difference"], "0.00")

    def test_reversal_removes_the_later_balance_and_viewer_cannot_post(self):
        revenue = LedgerAccount.objects.get(code="4000").pk
        cash = LedgerAccount.objects.get(code="1000").pk
        created = self.post_journal(
            [{"account": cash, "debit": "80.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "80.00"}],
            entry_date="2026-10-05",
        )
        self.client.force_authenticate(self.viewer)
        denied = self.client.post(reverse("journal-reverse", args=[created.data["id"]]), {"entry_date": "2026-10-06", "description": "Undo"}, format="json")
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.officer)
        reversed_entry = self.client.post(reverse("journal-reverse", args=[created.data["id"]]), {"entry_date": "2026-10-06", "description": "Undo"}, format="json")
        self.assertEqual(reversed_entry.status_code, 201, reversed_entry.data)
        before = profit_and_loss(date(2026, 10, 5), date(2026, 10, 5))
        after = profit_and_loss(date(2026, 10, 1), date(2026, 10, 6))
        self.assertEqual(before["total_revenue"], "80.00")
        self.assertEqual(after["total_revenue"], "0.00")
        self.assertEqual(trial_balance(date(2026, 10, 6))["balanced"], True)

    def test_closed_period_blocks_posting_unless_authorized_adjustment(self):
        period = AccountingPeriod.objects.get(name="FY2026")
        closed = self.client.post(reverse("accounting-period-close", args=[period.pk]))
        self.assertEqual(closed.status_code, 200)
        revenue = LedgerAccount.objects.get(code="4100").pk
        cash = LedgerAccount.objects.get(code="1000").pk
        lines = [{"account": cash, "debit": "10.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "10.00"}]
        blocked = self.post_journal(lines, description="After close")
        self.assertEqual(blocked.status_code, 400)
        adjustment = self.client.post(
            reverse("journal-list"),
            {"entry_date": "2026-10-20", "description": "Adjustment", "lines": lines, "post": True, "is_adjustment": True},
            format="json",
        )
        self.assertEqual(adjustment.status_code, 400)
        self.client.force_authenticate(self.executive)
        allowed = self.client.post(
            reverse("journal-list"),
            {"entry_date": "2026-10-20", "description": "Adjustment", "lines": lines, "post": True, "is_adjustment": True},
            format="json",
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)

    def test_transfer_depreciation_and_cash_flow_reconcile(self):
        revenue = LedgerAccount.objects.get(code="4000").pk
        self.post_journal(
            [{"account": LedgerAccount.objects.get(code="1000").pk, "debit": "200.00", "credit": "0.00"}, {"account": revenue, "debit": "0.00", "credit": "200.00"}]
        )
        transfer = self.client.post(
            reverse("cash-movement-list"),
            {
                "cash_account": self.cash.pk,
                "kind": "TRANSFER",
                "movement_date": "2026-10-21",
                "amount": "50.00",
                "reference": "TR-1",
                "description": "Till to bank",
                "transfer_to": self.bank.pk,
            },
            format="json",
        )
        posted = self.client.post(reverse("cash-movement-post-entry", args=[transfer.data["id"]]))
        self.assertEqual(posted.status_code, 200, posted.data)
        asset = Asset.objects.create(asset_id="AST-1", description="Scale", purchase_date=date(2026, 1, 1), cost=Decimal("1200.00"), residual_value=Decimal("0.00"), useful_life_years=Decimal("5.00"))
        self.client.post(
            reverse("journal-list"),
            {
                "entry_date": "2026-01-15",
                "description": "Buy scale",
                "post": True,
                "lines": [
                    {"account": LedgerAccount.objects.get(code="1500").pk, "debit": "1200.00", "credit": "0.00"},
                    {"account": LedgerAccount.objects.get(code="1010").pk, "debit": "0.00", "credit": "1200.00"},
                ],
            },
            format="json",
        )
        depreciation = self.client.post(reverse("asset-depreciate", args=[asset.pk]), {"period_start": "2026-02-01", "period_end": "2026-02-28"}, format="json")
        self.assertEqual(depreciation.status_code, 201, depreciation.data)
        self.assertEqual(depreciation.data["amount"], "20.00")
        flow = cash_flow(date(2026, 1, 1), date(2026, 10, 31))
        self.assertEqual(flow["reconciled"], True)
        self.assertEqual(flow["investing"], "-1200.00")
        self.assertEqual(Decimal(flow["opening_cash"]) + Decimal(flow["net_change"]), Decimal(flow["closing_cash"]))
        statement = profit_and_loss(date(2026, 1, 1), date(2026, 10, 31))
        self.assertEqual(statement["total_revenue"], "200.00")
        self.assertEqual(statement["total_expenses"], "20.00")
        again = self.client.post(reverse("asset-depreciate", args=[asset.pk]), {"period_start": "2026-02-01", "period_end": "2026-02-28"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_receivable_payment_aging_and_duplicate_reference(self):
        receivable = self.client.post(
            reverse("receivable-list"),
            {
                "party": "Buyer",
                "reference": "INV-1",
                "kind": "TRADE",
                "credit_treatment": "REVENUE",
                "issue_date": "2026-09-01",
                "due_date": "2026-09-15",
                "original_amount": "100.00",
                "receivable_account": LedgerAccount.objects.get(code="1100").pk,
                "credit_account": LedgerAccount.objects.get(code="4200").pk,
            },
            format="json",
        )
        issued = self.client.post(reverse("receivable-issue", args=[receivable.data["id"]]))
        self.assertEqual(issued.status_code, 200, issued.data)
        first = self.client.post(
            reverse("receivable-collect", args=[receivable.data["id"]]),
            {"received_on": "2026-10-01", "amount": "40.00", "reference": "RCPT-1", "cash_account": self.cash.pk},
            format="json",
        )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["outstanding"], "60.00")
        duplicate = self.client.post(
            reverse("receivable-collect", args=[receivable.data["id"]]),
            {"received_on": "2026-10-02", "amount": "10.00", "reference": "RCPT-1", "cash_account": self.cash.pk},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 400)
        aging = self.client.get(reverse("finance-report", args=["receivables-aging"]), {"as_of": "2026-10-20"})
        self.assertEqual(aging.data["buckets"]["31_60"], "60.00")

    def test_subscription_posting_is_explicit_and_not_repeated(self):
        farmer = Farmer.objects.create(first_name="Amai", surname="Moyo", national_id="63-2222222-A-01")
        subscription = FarmerSubscription.objects.create(farmer=farmer, expected_amount=Decimal("500.00"), paid_amount=Decimal("500.00"), outstanding_amount=Decimal("0.00"), season="2026/2027")
        payload = {
            "source": "SUBSCRIPTION",
            "source_id": subscription.pk,
            "external_reference": "SUB-1",
            "amount": "500.00",
            "entry_date": "2026-10-20",
            "description": "Subscription receipt",
            "debit_account": LedgerAccount.objects.get(code="1000").pk,
            "credit_account": LedgerAccount.objects.get(code="4000").pk,
        }
        first = self.client.post(reverse("operational-posting"), payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        second = self.client.post(reverse("operational-posting"), payload, format="json")
        self.assertEqual(second.status_code, 400)
        subscription.refresh_from_db()
        self.assertEqual(subscription.paid_amount, Decimal("500.00"))
        self.assertEqual(account_by_code("4000").code, "4000")

    def test_payroll_schedule_does_not_invent_statutory_deductions(self):
        schedule = PayrollEntry.objects.create(employee_id="EMP-1", employee_position="Officer", basic_salary_monthly=Decimal("1000.00"), housing_allowance_monthly=Decimal("100.00"))
        created = self.client.post(
            reverse("payroll-payment-list"),
            {"schedule": schedule.pk, "period_start": "2026-10-01", "period_end": "2026-10-31", "deductions": "0.00"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["net_salary"], "1100.00")
        self.client.force_authenticate(self.viewer)
        hidden = self.client.get(reverse("payroll-payment-list"))
        self.assertEqual(hidden.status_code, 403)

    def test_workbook_opening_position_uses_source_records_not_hardcoded_totals(self):
        DataBankEntry.objects.create(month="September", opening_balance="10.00", receipts="5.00", expenses="3.00", closing_balance="12.00", source_row=1)
        Receipt.objects.create(receipt_date=date(2026, 8, 1), farmer_name="A", amount_due="100.00", amount_paid="40.00", balance="60.00")
        Receipt.objects.create(receipt_date=date(2026, 10, 2), farmer_name="B", amount_due="999.00", amount_paid="1.00", balance="998.00")
        Expense.objects.create(expense_date=date(2026, 8, 1), particulars="Salary", net_expense="25.00", amount_debit="25.00")
        Expense.objects.create(expense_date=date(2026, 8, 2), particulars="Office laptop", net_expense="30.00", amount_debit="30.00")
        position = workbook_opening_position()
        self.assertEqual(position["assets"][0]["amount"], "12.00")
        self.assertEqual(position["assets"][1]["amount"], "60.00")
        self.assertEqual(position["assets"][2]["amount"], "30.00")
        self.assertEqual(position["equity"][0]["amount"], "-15.00")
        self.assertFalse(position["capital_verified"])
        self.assertTrue(position["balanced"])
        self.assertIn("derived", position["equity"][1]["name"].lower())
