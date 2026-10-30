from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from apps.finance.models import Expense, ExpenseClaim
from apps.subscriptions.models import FarmerSubscription, SubscriptionPayment


def _month(value):
    if not value:
        return ""
    return value.strftime("%Y-%m")


def _amount(value):
    return f"{Decimal(str(value or 0)):.2f}"


def build_dashboard_charts(*, farmers, season_name, season_start, season_end, allocations, productions, deliveries, debts, requested, allocated):
    registrations = farmers
    receipts = SubscriptionPayment.objects.all()
    legacy_receipts = FarmerSubscription.objects.filter(paid_amount__gt=0)
    expenses = Expense.objects.exclude(expense_date__isnull=True)
    claims = ExpenseClaim.objects.exclude(status=ExpenseClaim.STATUS_DRAFT)
    if season_start and season_end:
        registrations = registrations.filter(registration_date__gte=season_start, registration_date__lte=season_end)
        receipts = receipts.filter(payment_date__gte=season_start, payment_date__lte=season_end)
        legacy_receipts = legacy_receipts.filter(payment_date__gte=season_start, payment_date__lte=season_end)
        expenses = expenses.filter(expense_date__gte=season_start, expense_date__lte=season_end)
        claims = claims.filter(expense_date__gte=season_start, expense_date__lte=season_end)
    if season_name:
        receipts = receipts.filter(subscription__season__iexact=season_name)
        legacy_receipts = legacy_receipts.filter(season__iexact=season_name)

    registration_rows = [
        {"month": _month(row["month"]), "count": row["count"]}
        for row in registrations.annotate(month=TruncMonth("registration_date")).values("month").annotate(count=Count("id")).order_by("month")
        if row["month"]
    ]
    receipt_map = {}
    for row in receipts.annotate(month=TruncMonth("payment_date")).values("month").annotate(amount=Sum("amount")).order_by("month"):
        if row["month"]:
            receipt_map[_month(row["month"])] = row["amount"] or Decimal("0.00")
    covered = set(SubscriptionPayment.objects.filter(subscription_id__in=legacy_receipts.values("id")).values_list("subscription_id", flat=True))
    for row in legacy_receipts.exclude(pk__in=covered).exclude(payment_date__isnull=True).annotate(month=TruncMonth("payment_date")).values("month").annotate(amount=Sum("paid_amount")):
        if row["month"]:
            key = _month(row["month"])
            receipt_map[key] = receipt_map.get(key, Decimal("0.00")) + (row["amount"] or Decimal("0.00"))

    status_rows = FarmerSubscription.objects.filter(farmer_id__in=farmers.values("id"))
    if season_name:
        status_rows = status_rows.filter(season__iexact=season_name)
    status_counts = _subscription_status(farmers, season_name, status_rows)
    undated_rows = FarmerSubscription.objects.filter(paid_amount__gt=0, payment_date__isnull=True, farmer_id__in=farmers.values("id"))
    if season_name:
        undated_rows = undated_rows.filter(season__iexact=season_name)
    undated_rows = undated_rows.exclude(pk__in=SubscriptionPayment.objects.values("subscription_id"))
    undated_receipts = undated_rows.aggregate(total=Sum("paid_amount"))["total"] or Decimal("0.00")
    expense_months = {}
    category_totals = {}
    for row in claims.annotate(month=TruncMonth("expense_date")).values("month", "expense_account__name").annotate(amount=Sum("amount")):
        label = row["expense_account__name"] or "Other Expenses"
        category_totals[label] = category_totals.get(label, Decimal("0.00")) + (row["amount"] or 0)
        if row["month"]:
            key = _month(row["month"])
            expense_months[key] = expense_months.get(key, Decimal("0.00")) + (row["amount"] or 0)
    for row in expenses.annotate(month=TruncMonth("expense_date")).values("month").annotate(amount=Sum("net_expense")):
        if row["month"]:
            key = _month(row["month"])
            expense_months[key] = expense_months.get(key, Decimal("0.00")) + (row["amount"] or 0)
            category_totals["Recorded expenses"] = category_totals.get("Recorded expenses", Decimal("0.00")) + (row["amount"] or 0)

    subscription_outstanding = status_rows.aggregate(total=Sum("outstanding_amount"))["total"] or Decimal("0.00")
    input_outstanding = debts.aggregate(total=Sum("outstanding_monetary_balance"))["total"] or Decimal("0.00")
    undated_deliveries = deliveries.filter(delivery_date__isnull=True).aggregate(total=Sum("tonnes"))["total"] or Decimal("0.00")
    return {
        "registrations": registration_rows,
        "registrations_undated": farmers.filter(registration_date__isnull=True).count(),
        "subscription_receipts": [{"month": month, "amount": _amount(amount)} for month, amount in sorted(receipt_map.items())],
        "subscription_receipts_undated": _amount(undated_receipts),
        "subscription_status": status_counts,
        "arda_hectares": {"requested": _amount(requested), "allocated": _amount(allocated)},
        "allocations_by_crop": [
            {"label": row["crop"] or "Unspecified", "hectares": _amount(row["hectares"])}
            for row in allocations.values("crop").annotate(hectares=Sum("hectares")).order_by("crop")
        ],
        "production_by_crop": [
            {"label": row["crop"] or "Unspecified", "tonnes": _amount(row["tonnes"])}
            for row in productions.values("crop").annotate(tonnes=Sum("actual_production")).order_by("crop")
        ],
        "deliveries": [
            {"month": _month(row["month"]), "tonnes": _amount(row["tonnes"])}
            for row in deliveries.exclude(delivery_date__isnull=True).annotate(month=TruncMonth("delivery_date")).values("month").annotate(tonnes=Sum("tonnes")).order_by("month")
            if row["month"]
        ],
        "deliveries_undated_tonnes": _amount(undated_deliveries),
        "receivables": {"subscription_outstanding": _amount(subscription_outstanding), "input_debt": _amount(input_outstanding)},
        "expenses_by_category": [{"label": label, "amount": _amount(amount)} for label, amount in sorted(category_totals.items())],
        "expenses_by_month": [{"month": month, "amount": _amount(amount)} for month, amount in sorted(expense_months.items())],
        "recent": _recent_activity(registrations, receipts, legacy_receipts, allocations, deliveries),
    }


def _subscription_status(farmers, season_name, status_rows):
    if season_name:
        from apps.subscriptions.views import FarmerSubscriptionViewSet

        annotated = FarmerSubscriptionViewSet.with_season_payment_status(farmers, season_name)
        counts = annotated.aggregate(
            paid=Count("pk", filter=Q(summary_payment_status="PAID")),
            partial=Count("pk", filter=Q(summary_payment_status="PARTIAL")),
            unpaid=Count("pk", filter=Q(summary_payment_status="UNPAID")),
        )
        return {key: counts[key] or 0 for key in ("paid", "partial", "unpaid")}
    return {
        "paid": status_rows.filter(payment_status__iexact="paid").count(),
        "partial": status_rows.filter(
            Q(payment_status__iexact="partial") | Q(payment_status__iexact="partly paid") | Q(payment_status__iexact="partially paid")
        ).count(),
        "unpaid": status_rows.filter(Q(payment_status__iexact="unpaid") | Q(payment_status="")).count(),
    }


def _recent_activity(registrations, receipts, legacy_receipts, allocations, deliveries):
    events = []
    for farmer in registrations.order_by("-registration_date", "-id")[:4]:
        events.append({"kind": "Registration", "when": _day(farmer.registration_date), "detail": farmer.full_name})
    for payment in receipts.select_related("subscription__farmer").order_by("-payment_date", "-id")[:4]:
        farmer = payment.subscription.farmer
        events.append({"kind": "Subscription payment", "when": _day(payment.payment_date), "detail": f"{farmer.full_name} · USD {_amount(payment.amount)}"})
    dated = legacy_receipts.exclude(payment_date__isnull=True).exclude(pk__in=SubscriptionPayment.objects.filter(subscription_id__in=legacy_receipts.values("id")).values("subscription_id"))
    for subscription in dated.select_related("farmer").order_by("-payment_date", "-id")[:4]:
        events.append({"kind": "Subscription payment", "when": _day(subscription.payment_date), "detail": f"{subscription.farmer.full_name} · USD {_amount(subscription.paid_amount)}"})
    for allocation in allocations.select_related("farmer").order_by("-allocation_date", "-id")[:4]:
        events.append({"kind": "Input allocation", "when": _day(allocation.allocation_date), "detail": f"{allocation.farmer.full_name} · {_amount(allocation.hectares)} ha"})
    for delivery in deliveries.exclude(delivery_date__isnull=True).select_related("farmer").order_by("-delivery_date", "-id")[:4]:
        events.append({"kind": "GMB delivery", "when": _day(delivery.delivery_date), "detail": f"{delivery.farmer.full_name} · {_amount(delivery.tonnes)} t"})
    return sorted(events, key=lambda event: event["when"], reverse=True)[:8]


def _day(value):
    if not value:
        return ""
    return value.isoformat()[:10]
