"""Opening balance sheet taken from the SGR workbook formulas.

The workbook sheet BALANCE SHEET measures the position immediately before
1 October 2026, the first day of agricultural year 2026/2027.

Cash at Bank is the September closing balance on DATA_BANK.
Accounts receivable is subscription amount due minus amount paid on
DATA_RECEIPTS dated before 1 October 2026.
Office equipment is the net expense of rows dated before that day whose
particulars contain laptop, chair, or phone. The workbook keyword "chair"
also matches "Chairman".
Retained earnings are subscription receipts minus net expenses from
1 June 2026 through 31 August 2026, which is PROFIT & LOSS column I.
Contributed capital is the workbook's derived plug, Assets - Liabilities -
Retained earnings. It is not a verified capital balance and is not posted.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from apps.finance.models import Expense, Receipt
from apps.source_data.models import DataBankEntry

from .ledger import money, text_amount

OPENING_CUTOFF = date(2026, 10, 1)
RETAINED_START = date(2026, 6, 1)
RETAINED_END = date(2026, 9, 1)
ZERO = Decimal("0.00")
EQUIPMENT_KEYWORDS = ("laptop", "chair", "phone")


def _sum(queryset, field):
    return money(queryset.aggregate(total=Sum(field))["total"] or ZERO)


def workbook_opening_position():
    bank = DataBankEntry.objects.filter(month__istartswith="sept").order_by("-id").first()
    cash = money(bank.closing_balance) if bank else None
    receipts = Receipt.objects.filter(receipt_date__lt=OPENING_CUTOFF)
    due = _sum(receipts, "amount_due")
    paid = _sum(receipts, "amount_paid")
    receivable = money(due - paid)
    equipment = Expense.objects.filter(expense_date__lt=OPENING_CUTOFF).filter(
        Q(particulars__icontains="laptop") | Q(particulars__icontains="chair") | Q(particulars__icontains="phone")
    )
    ppe = _sum(equipment, "net_expense")
    income = _sum(Receipt.objects.filter(receipt_date__gte=RETAINED_START, receipt_date__lt=RETAINED_END), "amount_paid")
    costs = _sum(Expense.objects.filter(expense_date__gte=RETAINED_START, expense_date__lt=RETAINED_END), "net_expense")
    retained = money(income - costs)
    liabilities = ZERO
    assets_available = cash is not None
    total_assets = money((cash or ZERO) + receivable + ppe) if assets_available else None
    derived_capital = money(total_assets - liabilities - retained) if total_assets is not None else None
    total_equity = money(retained + derived_capital) if derived_capital is not None else None
    difference = money(total_assets - liabilities - total_equity) if total_assets is not None and total_equity is not None else None
    without_capital = money(total_assets - liabilities - retained) if total_assets is not None else None
    return {
        "as_of": "2026-09-30",
        "title": "Opening balance sheet at 30 September 2026",
        "assets": [
            {"name": "Cash at Bank", "amount": text_amount(cash) if cash is not None else None, "status": "calculated" if cash is not None else "missing", "source": "September closing balance in the reconciled bank book."},
            {"name": "Accounts Receivable – Outstanding Farmer/Subscription Amounts", "amount": text_amount(receivable), "status": "calculated", "source": "Subscription amount due minus amount paid before 1 October 2026."},
            {"name": "Property, Plant & Equipment – Office Equipment", "amount": text_amount(ppe), "status": "calculated", "source": "Net expense before 1 October 2026 for particulars containing laptop, chair, or phone."},
        ],
        "liabilities": [
            {"name": "Accounts Payable / Other Liabilities", "amount": text_amount(liabilities), "status": "unverified_zero", "source": "The workbook has no payable ledger, so this line is zero until a liability is confirmed."},
        ],
        "equity": [
            {"name": "Retained Earnings – Cumulative Profit/(Loss) to 31 Aug 2026", "amount": text_amount(retained), "status": "calculated", "source": "Subscription receipts minus net expenses for June, July, and August 2026."},
            {"name": "Opening / Contributed Capital (derived)", "amount": text_amount(derived_capital) if derived_capital is not None else None, "status": "derived_unverified", "source": "Workbook balancing figure. It is not a verified capital balance and has not been posted."},
        ],
        "total_assets": text_amount(total_assets) if total_assets is not None else None,
        "total_liabilities": text_amount(liabilities),
        "total_equity": text_amount(total_equity) if total_equity is not None else None,
        "equation_difference": text_amount(difference) if difference is not None else None,
        "balanced": difference == ZERO,
        "difference_without_derived_capital": text_amount(without_capital) if without_capital is not None else None,
        "capital_verified": False,
        "notes": [
            "This is the opening position for agricultural year 2026/2027. It is calculated from imported receipts, expenses, and the bank book. It is not a posted journal.",
            "Accounts payable is zero because the workbook has no separate payable ledger.",
            "Contributed capital is the derived figure Assets minus liabilities minus retained earnings. Replace it when a verified capital balance is available.",
            "The equipment keyword chair also matches Chairman in the source expense descriptions. That is how the workbook formula is written.",
        ],
    }
