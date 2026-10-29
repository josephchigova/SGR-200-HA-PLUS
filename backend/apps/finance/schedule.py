from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError

from apps.finance.ledger import account_by_code, approve_expense, cash_book_for, ensure_default_chart, ensure_open_period, money, recognize_expense

from .models import ExpenseClaim

EXPENSE_CATEGORIES = {
    "SALARIES": ("6000", "Salaries and Wages"),
    "TRANSPORT": ("6100", "Transport and Fuel"),
    "RENT": ("6200", "Office Rent"),
    "UTILITIES": ("6200", "Utilities"),
    "COMMUNICATION": ("6200", "Communication and Internet"),
    "VERIFICATION": ("6300", "Farmer Verification"),
    "STATIONERY": ("6200", "Stationery and Printing"),
    "REPAIRS": ("6500", "Repairs and Maintenance"),
    "OTHER": ("6500", "Other Expenses"),
}


@transaction.atomic
def record_expense(*, expense_date, description, amount, method, category, reference="", paid=True, notes="", user):
    amount = money(amount)
    if amount <= 0:
        raise ValidationError({"amount": ["Enter an amount greater than zero."]})
    if method not in {"CASH", "BANK"}:
        raise ValidationError({"method": ["Choose Cash or Bank."]})
    if category not in EXPENSE_CATEGORIES:
        raise ValidationError({"category": ["Choose an expense category."]})
    if not description or not str(description).strip():
        raise ValidationError({"description": ["Enter a description."]})
    if isinstance(expense_date, str):
        expense_date = date.fromisoformat(expense_date)
    if not expense_date:
        raise ValidationError({"expense_date": ["Enter the expense date."]})

    ensure_default_chart()
    ensure_open_period(expense_date)
    account_code, category_label = EXPENSE_CATEGORIES[category]
    system_reference = reference.strip() if reference and reference.strip() else f"EXP-{uuid4().hex[:10].upper()}"
    if ExpenseClaim.objects.filter(reference=system_reference).exists():
        raise ValidationError({"reference": ["This reference has already been used."]})

    claim = ExpenseClaim.objects.create(
        reference=system_reference,
        payee=category_label,
        expense_date=expense_date,
        amount=amount,
        method=method,
        description=f"{description.strip()}" + (f" — {notes.strip()}" if notes and notes.strip() else ""),
        basis=ExpenseClaim.CASH if paid else ExpenseClaim.ACCRUAL,
        expense_account=account_by_code(account_code),
        payable_account=None if paid else account_by_code("2000"),
        cash_account=cash_book_for(method) if paid else None,
        status=ExpenseClaim.STATUS_DRAFT,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    approve_expense(claim.pk, user)
    recognize_expense(claim.pk, user)
    claim.refresh_from_db()
    return claim


def expense_queryset(start=None, end=None, category="", method="", search=""):
    queryset = ExpenseClaim.objects.select_related("expense_account").exclude(status=ExpenseClaim.STATUS_DRAFT)
    if start:
        queryset = queryset.filter(expense_date__gte=start)
    if end:
        queryset = queryset.filter(expense_date__lte=end)
    if method:
        queryset = queryset.filter(method=method)
    if category:
        account_code = EXPENSE_CATEGORIES.get(category, (None, None))[0]
        if account_code:
            queryset = queryset.filter(expense_account__code=account_code)
    if search:
        queryset = queryset.filter(Q(description__icontains=search) | Q(reference__icontains=search))
    return queryset.order_by("-expense_date", "-id")


def expense_total(queryset):
    return queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
