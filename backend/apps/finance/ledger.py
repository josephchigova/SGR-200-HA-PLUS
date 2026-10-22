"""Double-entry ledger. Posted journals are the only source of financial statements."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User

from .models import (
    AccountingPeriod,
    CashMovement,
    DepreciationEntry,
    ExpenseClaim,
    FinanceAuditEvent,
    FinanceBudget,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OperationalPosting,
    PayablePayment,
    PayrollPayment,
    ReceivablePayment,
    RecognizedReceipt,
    TradePayable,
    TradeReceivable,
)

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0.00")

POSTED_STATUSES = (JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED)

DEFAULT_ACCOUNTS = [
    ("1000", "Cash on Hand", "ASSET", "CASH", "NONE", "DEBIT"),
    ("1010", "Bank Accounts", "ASSET", "BANK", "NONE", "DEBIT"),
    ("1100", "Accounts Receivable", "ASSET", "RECEIVABLE", "OPERATING", "DEBIT"),
    ("1110", "Input Programme Receivables", "ASSET", "RECEIVABLE", "OPERATING", "DEBIT"),
    ("1200", "Inventory", "ASSET", "INVENTORY", "OPERATING", "DEBIT"),
    ("1500", "Property, Plant and Equipment", "ASSET", "PPE", "INVESTING", "DEBIT"),
    ("1510", "Accumulated Depreciation", "ASSET", "CONTRA_ASSET", "NON_CASH", "CREDIT"),
    ("2000", "Accounts Payable", "LIABILITY", "PAYABLE", "OPERATING", "CREDIT"),
    ("2100", "Payroll Payable", "LIABILITY", "PAYABLE", "OPERATING", "CREDIT"),
    ("2110", "Payroll Deductions Payable", "LIABILITY", "PAYABLE", "OPERATING", "CREDIT"),
    ("2200", "Unearned Receipts", "LIABILITY", "PAYABLE", "OPERATING", "CREDIT"),
    ("2210", "Amounts Held for Other Parties", "LIABILITY", "PAYABLE", "OPERATING", "CREDIT"),
    ("2300", "Loans Payable", "LIABILITY", "PAYABLE", "FINANCING", "CREDIT"),
    ("2400", "Farmer Input Recovery Obligations", "LIABILITY", "OTHER", "OPERATING", "CREDIT"),
    ("2500", "Programme Funding", "LIABILITY", "PAYABLE", "FINANCING", "CREDIT"),
    ("3000", "Contributed Funds", "EQUITY", "EQUITY", "FINANCING", "CREDIT"),
    ("3100", "Retained Earnings", "EQUITY", "RETAINED_EARNINGS", "FINANCING", "CREDIT"),
    ("4000", "Membership and Subscription Revenue", "REVENUE", "REVENUE", "OPERATING", "CREDIT"),
    ("4100", "Other Operating Revenue", "REVENUE", "REVENUE", "OPERATING", "CREDIT"),
    ("4200", "Service Fee Revenue", "REVENUE", "REVENUE", "OPERATING", "CREDIT"),
    ("6000", "Salaries and Wages", "EXPENSE", "EXPENSE", "OPERATING", "DEBIT"),
    ("6100", "Transport and Fuel", "EXPENSE", "EXPENSE", "OPERATING", "DEBIT"),
    ("6200", "Office Expenses", "EXPENSE", "EXPENSE", "OPERATING", "DEBIT"),
    ("6300", "Administrative Expenses", "EXPENSE", "EXPENSE", "OPERATING", "DEBIT"),
    ("6400", "Depreciation Expense", "EXPENSE", "EXPENSE", "NON_CASH", "DEBIT"),
    ("6500", "Other Operating Expenses", "EXPENSE", "EXPENSE", "OPERATING", "DEBIT"),
]


def money(value):
    if value is None or value == "":
        return ZERO
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def text_amount(value):
    return f"{money(value):.2f}"


def reject(message):
    raise ValidationError({"detail": message})


def ensure_default_chart():
    created = []
    for code, name, account_type, category, flow, normal in DEFAULT_ACCOUNTS:
        account, was_created = LedgerAccount.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "category": category,
                "cash_flow_section": flow,
                "normal_balance": normal,
                "description": "Default SGR chart account. Classification can be changed before it is used.",
            },
        )
        if was_created:
            created.append(account.code)
    return created


def account_by_code(code):
    try:
        return LedgerAccount.objects.get(code=code, is_active=True)
    except LedgerAccount.DoesNotExist:
        reject(f"Active ledger account {code} is not configured.")


def _audit(action, actor, journal=None, detail=""):
    FinanceAuditEvent.objects.create(action=action, actor=actor, journal=journal, detail=detail)


def _next_reference(prefix):
    last = (
        JournalEntry.objects.select_for_update()
        .filter(reference__startswith=prefix)
        .order_by("-reference")
        .first()
    )
    number = 1
    if last:
        try:
            number = int(last.reference.rsplit("-", 1)[-1]) + 1
        except ValueError:
            number = JournalEntry.objects.filter(reference__startswith=prefix).count() + 1
    return f"{prefix}{number:04d}"


def _period_for(on_date):
    period = AccountingPeriod.objects.filter(start_date__lte=on_date, end_date__gte=on_date).order_by("start_date").first()
    if period is None:
        reject("No accounting period covers this date. Open a period before posting.")
    return period


def _may_post_to_period(user, period, is_adjustment):
    if period.status != AccountingPeriod.STATUS_CLOSED:
        return
    if is_adjustment and user and (user.is_superuser or user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE}):
        return
    reject("This accounting period is closed. Only an authorized adjustment can be posted to it.")


def _clean_lines(raw_lines):
    if len(raw_lines) < 2:
        reject("A journal entry needs at least two lines.")
    cleaned = []
    for raw in raw_lines:
        account = raw.get("account")
        if not isinstance(account, LedgerAccount):
            account = LedgerAccount.objects.filter(pk=account, is_active=True).first()
        if account is None:
            reject("Each line must use an active ledger account.")
        debit = money(raw.get("debit"))
        credit = money(raw.get("credit"))
        if debit < 0 or credit < 0:
            reject("Debit and credit amounts cannot be negative.")
        if debit > 0 and credit > 0:
            reject("A journal line cannot have both a debit and a credit.")
        if debit == 0 and credit == 0:
            reject("A journal line needs a debit or a credit.")
        cleaned.append({"account": account, "debit": debit, "credit": credit, "memo": raw.get("memo") or ""})
    return cleaned


def _totals(lines):
    return sum(line["debit"] for line in lines), sum(line["credit"] for line in lines)


@transaction.atomic
def create_journal(*, entry_date, description, lines, user, source_module="", source_key="", programme=None, season=None, post=False, is_adjustment=False):
    cleaned = _clean_lines(lines)
    debits, credits = _totals(cleaned)
    if post and debits != credits:
        reject("A posted journal entry must balance. Debits must equal credits.")
    if post and debits == 0:
        reject("A posted journal entry must have a non-zero amount.")
    period = _period_for(entry_date)
    if post:
        _may_post_to_period(user, period, is_adjustment)
    prefix = f"JE-{entry_date:%Y%m%d}-"
    reference = _next_reference(prefix)
    try:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                reference=reference,
                entry_date=entry_date,
                description=description,
                source_module=source_module,
                source_key=source_key,
                period=period,
                is_adjustment=is_adjustment,
                programme=programme,
                season=season,
                status=JournalEntry.STATUS_DRAFT,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
    except IntegrityError:
        reject("This source has already been posted.")
    JournalLine.objects.bulk_create(
        [
            JournalLine(entry=entry, account=line["account"], debit=line["debit"], credit=line["credit"], memo=line["memo"])
            for line in cleaned
        ]
    )
    _audit("create", user, entry, description)
    if post:
        return post_journal(entry.pk, user)
    return entry


@transaction.atomic
def post_journal(entry_id, user):
    entry = JournalEntry.objects.select_for_update().get(pk=entry_id)
    if entry.status != JournalEntry.STATUS_DRAFT:
        reject("Only a draft journal entry can be posted.")
    period = AccountingPeriod.objects.select_for_update().get(pk=entry.period_id)
    _may_post_to_period(user, period, entry.is_adjustment)
    lines = list(entry.lines.select_related("account"))
    if len(lines) < 2:
        reject("A journal entry needs at least two lines.")
    debits = sum((line.debit for line in lines), ZERO)
    credits = sum((line.credit for line in lines), ZERO)
    if debits != credits or debits == 0:
        reject("A posted journal entry must balance. Debits must equal credits.")
    if any(not line.account.is_active for line in lines):
        reject("Posted lines must use active accounts.")
    entry.status = JournalEntry.STATUS_POSTED
    entry.posted_at = timezone.now()
    entry.posted_by = user if getattr(user, "is_authenticated", False) else None
    entry.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])
    _audit("post", user, entry, entry.reference)
    return entry


@transaction.atomic
def reverse_journal(entry_id, user, entry_date, description):
    entry = JournalEntry.objects.select_for_update().get(pk=entry_id)
    if entry.status != JournalEntry.STATUS_POSTED:
        reject("Only a posted journal entry can be reversed.")
    if entry.reversals.exists():
        reject("This journal entry has already been reversed.")
    lines = [
        {"account": line.account, "debit": line.credit, "credit": line.debit, "memo": f"Reversal of {entry.reference}"}
        for line in entry.lines.select_related("account")
    ]
    reversal = create_journal(
        entry_date=entry_date,
        description=description or f"Reversal of {entry.reference}",
        lines=lines,
        user=user,
        source_module=entry.source_module,
        source_key=f"reversal:{entry.reference}",
        programme=entry.programme,
        season=entry.season,
        post=True,
        is_adjustment=entry.is_adjustment,
    )
    reversal.reversal_of = entry
    reversal.save(update_fields=["reversal_of", "updated_at"])
    entry.status = JournalEntry.STATUS_REVERSED
    entry.save(update_fields=["status", "updated_at"])
    _audit("reverse", user, entry, reversal.reference)
    return reversal


def posted_lines(start=None, end=None, as_of=None, account_id=None):
    queryset = JournalLine.objects.filter(entry__status__in=POSTED_STATUSES).select_related("entry", "account")
    if as_of is not None:
        queryset = queryset.filter(entry__entry_date__lte=as_of)
    if start is not None:
        queryset = queryset.filter(entry__entry_date__gte=start)
    if end is not None:
        queryset = queryset.filter(entry__entry_date__lte=end)
    if account_id is not None:
        queryset = queryset.filter(account_id=account_id)
    return queryset


def account_balance(account, as_of=None, start=None, end=None):
    totals = posted_lines(start=start, end=end, as_of=as_of, account_id=account.pk).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    debit = totals["debit"] or ZERO
    credit = totals["credit"] or ZERO
    if account.normal_balance == LedgerAccount.NORMAL_DEBIT:
        return money(debit - credit)
    return money(credit - debit)


def trial_balance(as_of):
    rows = []
    debit_total = ZERO
    credit_total = ZERO
    for account in LedgerAccount.objects.all():
        totals = posted_lines(as_of=as_of, account_id=account.pk).aggregate(debit=Sum("debit"), credit=Sum("credit"))
        debit = money(totals["debit"] or ZERO)
        credit = money(totals["credit"] or ZERO)
        if debit == 0 and credit == 0:
            continue
        rows.append({"account_id": account.pk, "code": account.code, "name": account.name, "debit": text_amount(debit), "credit": text_amount(credit)})
        debit_total += debit
        credit_total += credit
    return {
        "as_of": as_of.isoformat(),
        "rows": rows,
        "total_debit": text_amount(debit_total),
        "total_credit": text_amount(credit_total),
        "balanced": debit_total == credit_total,
    }


def _statement_accounts(account_type, start, end):
    rows = []
    total = ZERO
    for account in LedgerAccount.objects.filter(account_type=account_type, is_active=True):
        amount = account_balance(account, start=start, end=end)
        if amount == 0:
            continue
        rows.append(
            {
                "account_id": account.pk,
                "code": account.code,
                "name": account.name,
                "category": account.category,
                "amount": text_amount(amount),
            }
        )
        total += amount
    return rows, money(total)


def _is_subscription_revenue(account):
    return account.code == "4000" or "subscription" in account.name.lower()


def _split_revenue(start, end):
    subscription_rows = []
    other_rows = []
    subscription = ZERO
    other = ZERO
    for account in LedgerAccount.objects.filter(account_type=LedgerAccount.TYPE_REVENUE, is_active=True):
        amount = account_balance(account, start=start, end=end)
        if amount == 0:
            continue
        row = {"account_id": account.pk, "code": account.code, "name": account.name, "category": account.category, "amount": text_amount(amount)}
        if _is_subscription_revenue(account):
            subscription_rows.append(row)
            subscription += amount
        else:
            other_rows.append(row)
            other += amount
    return subscription_rows, money(subscription), other_rows, money(other)


def profit_and_loss(start, end, compare_start=None, compare_end=None):
    subscription_rows, subscription, other_rows, other = _split_revenue(start, end)
    expense_rows, expenses = _statement_accounts(LedgerAccount.TYPE_EXPENSE, start, end)
    result = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "revenue": subscription_rows,
        "other_revenue": other_rows,
        "expenses": expense_rows,
        "subscription_revenue": text_amount(subscription),
        "total_revenue": text_amount(subscription),
        "excluded_revenue": text_amount(other),
        "total_expenses": text_amount(expenses),
        "net_profit": text_amount(subscription - expenses),
        "basis": "Subscriptions are the only authorized income. Revenue is the posted balance of the subscription revenue account. Expected and unposted subscription amounts are excluded. Draft journals are excluded.",
    }
    if compare_start and compare_end:
        _, compare_subscription, _, _other = _split_revenue(compare_start, compare_end)
        _, compare_expenses = _statement_accounts(LedgerAccount.TYPE_EXPENSE, compare_start, compare_end)
        result["comparison"] = {
            "start": compare_start.isoformat(),
            "end": compare_end.isoformat(),
            "total_revenue": text_amount(compare_subscription),
            "total_expenses": text_amount(compare_expenses),
            "net_profit": text_amount(compare_subscription - compare_expenses),
        }
    return result


def balance_sheet(as_of, compare_as_of=None):
    def section(account_type):
        rows = []
        total = ZERO
        for account in LedgerAccount.objects.filter(account_type=account_type):
            amount = account_balance(account, as_of=as_of)
            if amount == 0:
                continue
            presented = amount
            if account_type == LedgerAccount.TYPE_ASSET and account.normal_balance == LedgerAccount.NORMAL_CREDIT:
                presented = -amount
            rows.append(
                {
                    "account_id": account.pk,
                    "code": account.code,
                    "name": account.name,
                    "category": account.category,
                    "amount": text_amount(presented),
                }
            )
            total += presented
        return rows, money(total)

    assets, asset_total = section(LedgerAccount.TYPE_ASSET)
    liabilities, liability_total = section(LedgerAccount.TYPE_LIABILITY)
    equity_rows, equity_total = section(LedgerAccount.TYPE_EQUITY)
    _, revenue = _statement_accounts(LedgerAccount.TYPE_REVENUE, date_min(), as_of)
    _, expenses = _statement_accounts(LedgerAccount.TYPE_EXPENSE, date_min(), as_of)
    current_earnings = money(revenue - expenses)
    equity_total = money(equity_total + current_earnings)
    difference = money(asset_total - liability_total - equity_total)
    payload = {
        "as_of": as_of.isoformat(),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity_rows,
        "current_earnings": text_amount(current_earnings),
        "total_assets": text_amount(asset_total),
        "total_liabilities": text_amount(liability_total),
        "total_equity": text_amount(equity_total),
        "equation_difference": text_amount(difference),
        "balanced": difference == 0,
    }
    if not payload["balanced"]:
        payload["discrepancy"] = "Assets do not equal liabilities plus equity. Review unposted drafts, missing periods, and accounts whose normal balance does not match their type."
    if compare_as_of:
        payload["comparison_as_of"] = compare_as_of.isoformat()
        payload["comparison_total_assets"] = balance_sheet(compare_as_of)["total_assets"]
    return payload


def date_min():
    return timezone.datetime(1900, 1, 1).date()


def cash_flow(start, end):
    cash_accounts = list(LedgerAccount.objects.filter(category__in=[LedgerAccount.CATEGORY_CASH, LedgerAccount.CATEGORY_BANK]))
    cash_ids = {account.pk for account in cash_accounts}
    day_before = start - timedelta(days=1)
    opening = money(sum((account_balance(account, as_of=day_before) for account in cash_accounts), ZERO))
    closing = money(sum((account_balance(account, as_of=end) for account in cash_accounts), ZERO))
    sections = {
        LedgerAccount.FLOW_OPERATING: ZERO,
        LedgerAccount.FLOW_INVESTING: ZERO,
        LedgerAccount.FLOW_FINANCING: ZERO,
        LedgerAccount.FLOW_NON_CASH: ZERO,
    }
    transfers = []
    non_cash = []
    journals = (
        JournalEntry.objects.filter(status__in=POSTED_STATUSES, entry_date__gte=start, entry_date__lte=end, lines__account_id__in=cash_ids)
        .distinct()
        .prefetch_related("lines__account")
    )
    for entry in journals:
        lines = list(entry.lines.all())
        cash_lines = [line for line in lines if line.account_id in cash_ids]
        other = [line for line in lines if line.account_id not in cash_ids]
        cash_delta = money(sum((line.debit - line.credit for line in cash_lines), ZERO))
        if not other:
            transfers.append({"reference": entry.reference, "date": entry.entry_date.isoformat(), "description": entry.description, "amount": text_amount(cash_delta)})
            continue
        magnitudes = [(line, line.debit + line.credit) for line in other]
        total_magnitude = sum((magnitude for _, magnitude in magnitudes), ZERO) or Decimal("1.00")
        for line, magnitude in magnitudes:
            share = money(cash_delta * magnitude / total_magnitude)
            section = line.account.cash_flow_section
            if section not in sections:
                section = LedgerAccount.FLOW_OPERATING
            sections[section] += share
    for account in LedgerAccount.objects.filter(cash_flow_section=LedgerAccount.FLOW_NON_CASH, account_type=LedgerAccount.TYPE_EXPENSE):
        amount = account_balance(account, start=start, end=end)
        if amount:
            non_cash.append({"code": account.code, "name": account.name, "amount": text_amount(amount)})
    net_change = money(closing - opening)
    classified = money(sum(sections.values(), ZERO))
    rounding = money(net_change - classified)
    sections[LedgerAccount.FLOW_OPERATING] += rounding
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "opening_cash": text_amount(opening),
        "operating": text_amount(sections[LedgerAccount.FLOW_OPERATING]),
        "investing": text_amount(sections[LedgerAccount.FLOW_INVESTING]),
        "financing": text_amount(sections[LedgerAccount.FLOW_FINANCING]),
        "non_cash_cash_movement": text_amount(sections[LedgerAccount.FLOW_NON_CASH]),
        "net_change": text_amount(net_change),
        "closing_cash": text_amount(closing),
        "reconciled": money(opening + net_change) == closing,
        "transfers": transfers,
        "non_cash_expenses": non_cash,
        "rounding_adjustment": text_amount(rounding),
        "note": "Internal transfers between cash and bank accounts are excluded from operating, investing, and financing totals. Depreciation is disclosed as a non-cash expense.",
    }


def general_ledger(account_id, start, end):
    account = LedgerAccount.objects.get(pk=account_id)
    rows = []
    running = account_balance(account, as_of=start - timedelta(days=1))
    for line in posted_lines(start=start, end=end, account_id=account.pk).order_by("entry__entry_date", "id"):
        movement = line.debit - line.credit
        if account.normal_balance == LedgerAccount.NORMAL_CREDIT:
            movement = line.credit - line.debit
        running = money(running + movement)
        rows.append(
            {
                "date": line.entry.entry_date.isoformat(),
                "reference": line.entry.reference,
                "description": line.entry.description,
                "debit": text_amount(line.debit),
                "credit": text_amount(line.credit),
                "balance": text_amount(running),
            }
        )
    return {"account": f"{account.code} {account.name}", "opening_balance": text_amount(account_balance(account, as_of=start - timedelta(days=1))), "rows": rows}


def dashboard(start, end):
    statement = profit_and_loss(start, end)
    position = balance_sheet(end)
    flow = cash_flow(start, end)
    cash = ZERO
    bank = ZERO
    receivable = ZERO
    payable = ZERO
    for account in LedgerAccount.objects.all():
        amount = account_balance(account, as_of=end)
        if account.category == LedgerAccount.CATEGORY_CASH:
            cash += amount
        elif account.category == LedgerAccount.CATEGORY_BANK:
            bank += amount
        elif account.category == LedgerAccount.CATEGORY_RECEIVABLE:
            receivable += amount
        elif account.category == LedgerAccount.CATEGORY_PAYABLE and account.account_type == LedgerAccount.TYPE_LIABILITY:
            payable += amount
    recent = [
        {"reference": entry.reference, "date": entry.entry_date.isoformat(), "description": entry.description, "status": entry.status}
        for entry in JournalEntry.objects.filter(status__in=POSTED_STATUSES, entry_date__gte=start, entry_date__lte=end).order_by("-entry_date", "-id")[:8]
    ]
    from .workbook_statement import workbook_opening_position

    opening = workbook_opening_position()
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "subscription_revenue": statement["subscription_revenue"],
        "total_revenue": statement["total_revenue"],
        "excluded_revenue": statement["excluded_revenue"],
        "total_expenses": statement["total_expenses"],
        "net_profit": statement["net_profit"],
        "revenue_caption": "Recognized subscription revenue posted to the ledger for these dates.",
        "expense_caption": "Recognized expenses posted to the ledger for these dates.",
        "total_assets": opening["total_assets"],
        "total_liabilities": opening["total_liabilities"],
        "total_equity": opening["total_equity"],
        "cash_on_hand": text_amount(cash),
        "bank_balances": next((row["amount"] for row in opening["assets"] if row["name"] == "Cash at Bank"), None),
        "accounts_receivable": next((row["amount"] for row in opening["assets"] if "Receivable" in row["name"]), None),
        "accounts_payable": opening["liabilities"][0]["amount"] if opening["liabilities"] else text_amount(payable),
        "ledger_cash": text_amount(cash),
        "ledger_bank": text_amount(bank),
        "ledger_receivable": text_amount(receivable),
        "ledger_payable": text_amount(payable),
        "position_caption": opening["title"],
        "position_as_of": opening["as_of"],
        "operating_cash_flow": flow["operating"],
        "balanced": opening["balanced"],
        "ledger_balanced": position["balanced"],
        "recent": recent,
    }


def _cash_lines(movement, user):
    cash = movement.cash_account.ledger_account
    amount = money(movement.amount)
    if movement.kind == CashMovement.KIND_RECEIPT:
        if movement.offset_account_id is None:
            reject("A cash receipt needs the account to credit.")
        return [
            {"account": cash, "debit": amount, "credit": ZERO},
            {"account": movement.offset_account, "debit": ZERO, "credit": amount},
        ]
    if movement.kind == CashMovement.KIND_PAYMENT:
        if movement.offset_account_id is None:
            reject("A cash payment needs the account to debit.")
        return [
            {"account": movement.offset_account, "debit": amount, "credit": ZERO},
            {"account": cash, "debit": ZERO, "credit": amount},
        ]
    if movement.transfer_to_id is None or movement.transfer_to_id == movement.cash_account_id:
        reject("A transfer needs a different destination cash or bank account.")
    return [
        {"account": movement.transfer_to.ledger_account, "debit": amount, "credit": ZERO},
        {"account": cash, "debit": ZERO, "credit": amount},
    ]


@transaction.atomic
def post_cash_movement(movement_id, user):
    movement = CashMovement.objects.select_for_update().get(pk=movement_id)
    if movement.status == CashMovement.STATUS_POSTED:
        reject("This cashbook transaction is already posted.")
    if movement.cash_account.ledger_account.category not in {LedgerAccount.CATEGORY_CASH, LedgerAccount.CATEGORY_BANK}:
        reject("The cashbook account must point at a cash or bank ledger account.")
    journal = create_journal(
        entry_date=movement.movement_date,
        description=movement.description,
        lines=_cash_lines(movement, user),
        user=user,
        source_module="cashbook",
        source_key=f"cash:{movement.reference}",
        post=True,
    )
    movement.journal = journal
    movement.status = CashMovement.STATUS_POSTED
    movement.save(update_fields=["journal", "status"])
    _audit("cash-post", user, journal, movement.reference)
    return movement


@transaction.atomic
def post_recognized_receipt(receipt_id, user):
    receipt = RecognizedReceipt.objects.select_for_update().select_related("credit_account", "cash_account__ledger_account").get(pk=receipt_id)
    if receipt.status == RecognizedReceipt.STATUS_POSTED:
        reject("This receipt is already posted.")
    if receipt.recognition == RecognizedReceipt.EARNED and receipt.credit_account.account_type != LedgerAccount.TYPE_REVENUE:
        reject("Earned income must credit a revenue account.")
    if receipt.recognition in {RecognizedReceipt.ADVANCE, RecognizedReceipt.AGENCY} and receipt.credit_account.account_type != LedgerAccount.TYPE_LIABILITY:
        reject("Receipts in advance or held for another party must credit a liability, not revenue.")
    journal = create_journal(
        entry_date=receipt.received_on,
        description=f"Receipt {receipt.receipt_number} from {receipt.payer}",
        lines=[
            {"account": receipt.cash_account.ledger_account, "debit": receipt.amount, "credit": ZERO},
            {"account": receipt.credit_account, "debit": ZERO, "credit": receipt.amount},
        ],
        user=user,
        source_module="receipts",
        source_key=f"receipt:{receipt.receipt_number}",
        programme=receipt.programme,
        post=True,
    )
    receipt.journal = journal
    receipt.status = RecognizedReceipt.STATUS_POSTED
    receipt.save(update_fields=["journal", "status"])
    return receipt


@transaction.atomic
def approve_expense(claim_id, user):
    claim = ExpenseClaim.objects.select_for_update().get(pk=claim_id)
    if claim.status != ExpenseClaim.STATUS_DRAFT:
        reject("Only a draft expense can be approved.")
    claim.status = ExpenseClaim.STATUS_APPROVED
    claim.approved_by = user
    claim.save(update_fields=["status", "approved_by"])
    _audit("expense-approve", user, detail=claim.reference)
    return claim


@transaction.atomic
def recognize_expense(claim_id, user):
    claim = ExpenseClaim.objects.select_for_update().get(pk=claim_id)
    if claim.status != ExpenseClaim.STATUS_APPROVED:
        reject("Approve the expense before recognizing it.")
    amount = money(claim.amount)
    if claim.basis == ExpenseClaim.CASH:
        if claim.cash_account_id is None:
            reject("A cash expense needs the cash or bank account that paid it.")
        lines = [
            {"account": claim.expense_account, "debit": amount, "credit": ZERO},
            {"account": claim.cash_account.ledger_account, "debit": ZERO, "credit": amount},
        ]
        journal = create_journal(
            entry_date=claim.expense_date,
            description=claim.description,
            lines=lines,
            user=user,
            source_module="expenses",
            source_key=f"expense:{claim.reference}",
            programme=claim.programme,
            post=True,
        )
        claim.recognition_journal = journal
        claim.payment_journal = journal
        claim.status = ExpenseClaim.STATUS_PAID
    else:
        if claim.payable_account_id is None:
            reject("An accrued expense needs the liability account to credit.")
        journal = create_journal(
            entry_date=claim.expense_date,
            description=claim.description,
            lines=[
                {"account": claim.expense_account, "debit": amount, "credit": ZERO},
                {"account": claim.payable_account, "debit": ZERO, "credit": amount},
            ],
            user=user,
            source_module="expenses",
            source_key=f"expense:{claim.reference}",
            programme=claim.programme,
            post=True,
        )
        claim.recognition_journal = journal
        claim.status = ExpenseClaim.STATUS_RECOGNIZED
    claim.save(update_fields=["recognition_journal", "payment_journal", "status"])
    return claim


@transaction.atomic
def pay_expense(claim_id, user, paid_on, cash_account):
    claim = ExpenseClaim.objects.select_for_update().get(pk=claim_id)
    if claim.status != ExpenseClaim.STATUS_RECOGNIZED:
        reject("Only a recognized accrued expense can be paid. A cash expense is already paid.")
    journal = create_journal(
        entry_date=paid_on,
        description=f"Payment of {claim.reference}",
        lines=[
            {"account": claim.payable_account, "debit": claim.amount, "credit": ZERO},
            {"account": cash_account.ledger_account, "debit": ZERO, "credit": claim.amount},
        ],
        user=user,
        source_module="expenses",
        source_key=f"expense-payment:{claim.reference}",
        programme=claim.programme,
        post=True,
    )
    claim.payment_journal = journal
    claim.cash_account = cash_account
    claim.status = ExpenseClaim.STATUS_PAID
    claim.save(update_fields=["payment_journal", "cash_account", "status"])
    return claim


def _refresh_receivable_status(receivable):
    outstanding = money(receivable.original_amount - receivable.amount_received)
    if outstanding < 0:
        reject("Receipts exceed the receivable.")
    if receivable.amount_received == 0:
        receivable.status = TradeReceivable.STATUS_OPEN
    elif outstanding == 0:
        receivable.status = TradeReceivable.STATUS_SETTLED
    else:
        receivable.status = TradeReceivable.STATUS_PARTIAL
    receivable.save(update_fields=["amount_received", "status"])


@transaction.atomic
def issue_receivable(receivable_id, user):
    receivable = TradeReceivable.objects.select_for_update().select_related("receivable_account", "credit_account").get(pk=receivable_id)
    if receivable.status != TradeReceivable.STATUS_DRAFT:
        reject("This receivable is already issued.")
    if receivable.credit_treatment == TradeReceivable.CREDIT_REVENUE and receivable.credit_account.account_type != LedgerAccount.TYPE_REVENUE:
        reject("Revenue recognition must credit a revenue account.")
    if receivable.credit_treatment == TradeReceivable.CREDIT_LIABILITY and receivable.credit_account.account_type != LedgerAccount.TYPE_LIABILITY:
        reject("This receivable credits a liability, so the credit account must be a liability.")
    journal = create_journal(
        entry_date=receivable.issue_date,
        description=f"Receivable {receivable.reference}",
        lines=[
            {"account": receivable.receivable_account, "debit": receivable.original_amount, "credit": ZERO},
            {"account": receivable.credit_account, "debit": ZERO, "credit": receivable.original_amount},
        ],
        user=user,
        source_module="receivables",
        source_key=f"receivable:{receivable.reference}",
        programme=receivable.programme,
        post=True,
    )
    receivable.journal = journal
    receivable.status = TradeReceivable.STATUS_OPEN
    receivable.save(update_fields=["journal", "status"])
    return receivable


@transaction.atomic
def receive_receivable(receivable_id, user, received_on, amount, reference, cash_account):
    receivable = TradeReceivable.objects.select_for_update().select_related("receivable_account").get(pk=receivable_id)
    if receivable.status not in {TradeReceivable.STATUS_OPEN, TradeReceivable.STATUS_PARTIAL}:
        reject("This receivable is not open for collection.")
    amount = money(amount)
    outstanding = money(receivable.original_amount - receivable.amount_received)
    if amount <= 0 or amount > outstanding:
        reject("The receipt must be positive and cannot exceed the outstanding balance.")
    if ReceivablePayment.objects.filter(reference=reference).exists():
        reject("This receipt reference has already been used.")
    try:
        journal = create_journal(
            entry_date=received_on,
            description=f"Collection {reference}",
            lines=[
                {"account": cash_account.ledger_account, "debit": amount, "credit": ZERO},
                {"account": receivable.receivable_account, "debit": ZERO, "credit": amount},
            ],
            user=user,
            source_module="receivables",
            source_key=f"receivable-payment:{reference}",
            programme=receivable.programme,
            post=True,
        )
    except IntegrityError:
        reject("This receipt reference has already been used.")
    ReceivablePayment.objects.create(
        receivable=receivable,
        received_on=received_on,
        amount=amount,
        reference=reference,
        cash_account=cash_account,
        journal=journal,
        created_by=user,
    )
    receivable.amount_received = money(receivable.amount_received + amount)
    _refresh_receivable_status(receivable)
    return receivable


@transaction.atomic
def issue_payable(payable_id, user):
    payable = TradePayable.objects.select_for_update().select_related("payable_account", "offset_account").get(pk=payable_id)
    if payable.status != TradePayable.STATUS_DRAFT:
        reject("This bill is already recorded.")
    if payable.classification == TradePayable.CLASS_EXPENSE and payable.offset_account.account_type != LedgerAccount.TYPE_EXPENSE:
        reject("An expense bill must debit an expense account.")
    if payable.classification == TradePayable.CLASS_ASSET and payable.offset_account.account_type != LedgerAccount.TYPE_ASSET:
        reject("A capitalized bill must debit an asset account.")
    journal = create_journal(
        entry_date=payable.invoice_date,
        description=f"Bill {payable.invoice_number} from {payable.supplier}",
        lines=[
            {"account": payable.offset_account, "debit": payable.amount, "credit": ZERO},
            {"account": payable.payable_account, "debit": ZERO, "credit": payable.amount},
        ],
        user=user,
        source_module="payables",
        source_key=f"payable:{payable.supplier}:{payable.invoice_number}",
        post=True,
    )
    payable.journal = journal
    payable.status = TradePayable.STATUS_OPEN
    payable.save(update_fields=["journal", "status"])
    return payable


@transaction.atomic
def pay_payable(payable_id, user, paid_on, amount, reference, cash_account):
    payable = TradePayable.objects.select_for_update().select_related("payable_account").get(pk=payable_id)
    if payable.status not in {TradePayable.STATUS_OPEN, TradePayable.STATUS_PARTIAL}:
        reject("This bill is not open for payment.")
    amount = money(amount)
    outstanding = money(payable.amount - payable.amount_paid)
    if amount <= 0 or amount > outstanding:
        reject("The payment must be positive and cannot exceed the outstanding balance.")
    journal = create_journal(
        entry_date=paid_on,
        description=f"Payment {reference}",
        lines=[
            {"account": payable.payable_account, "debit": amount, "credit": ZERO},
            {"account": cash_account.ledger_account, "debit": ZERO, "credit": amount},
        ],
        user=user,
        source_module="payables",
        source_key=f"payable-payment:{reference}",
        post=True,
    )
    PayablePayment.objects.create(
        payable=payable, paid_on=paid_on, amount=amount, reference=reference, cash_account=cash_account, journal=journal, created_by=user
    )
    payable.amount_paid = money(payable.amount_paid + amount)
    outstanding = money(payable.amount - payable.amount_paid)
    payable.status = TradePayable.STATUS_SETTLED if outstanding == 0 else TradePayable.STATUS_PARTIAL
    payable.save(update_fields=["amount_paid", "status"])
    return payable


def aging_rows(records, as_of, amount_getter, due_getter):
    buckets = {"current": ZERO, "1_30": ZERO, "31_60": ZERO, "61_90": ZERO, "over_90": ZERO}
    rows = []
    for record in records:
        outstanding = money(amount_getter(record))
        if outstanding <= 0:
            continue
        days = (as_of - due_getter(record)).days
        if days <= 0:
            key = "current"
        elif days <= 30:
            key = "1_30"
        elif days <= 60:
            key = "31_60"
        elif days <= 90:
            key = "61_90"
        else:
            key = "over_90"
        buckets[key] += outstanding
        rows.append({"reference": getattr(record, "reference", None) or getattr(record, "invoice_number", ""), "party": getattr(record, "party", None) or getattr(record, "supplier", ""), "due_date": due_getter(record).isoformat(), "days": days, "bucket": key, "outstanding": text_amount(outstanding)})
    return {"as_of": as_of.isoformat(), "buckets": {key: text_amount(value) for key, value in buckets.items()}, "rows": rows}


def straight_line_amount(asset):
    if asset.useful_life_years is None or asset.useful_life_years <= 0:
        reject("Set a useful life before calculating depreciation.")
    depreciable = money(asset.cost - asset.residual_value)
    if depreciable <= 0:
        return ZERO
    annual = money(depreciable / asset.useful_life_years)
    monthly = money(annual / Decimal(12))
    remaining = money(depreciable - asset.accumulated_depreciation)
    if remaining <= 0:
        return ZERO
    if monthly > remaining:
        return remaining
    return monthly


@transaction.atomic
def post_depreciation(asset, period_start, period_end, user):
    if asset.purchase_date and period_end < asset.purchase_date:
        reject("Depreciation cannot start before the acquisition date.")
    if DepreciationEntry.objects.filter(asset=asset, period_start=period_start).exists():
        reject("Depreciation for this asset and period is already posted.")
    amount = straight_line_amount(asset)
    if amount <= 0:
        reject("This asset has no remaining depreciable amount.")
    expense = account_by_code("6400")
    accumulated = account_by_code("1510")
    journal = create_journal(
        entry_date=period_end,
        description=f"Depreciation {asset.asset_id} {period_start.isoformat()}",
        lines=[
            {"account": expense, "debit": amount, "credit": ZERO},
            {"account": accumulated, "debit": ZERO, "credit": amount},
        ],
        user=user,
        source_module="assets",
        source_key=f"depreciation:{asset.pk}:{period_start.isoformat()}",
        post=True,
    )
    asset.accumulated_depreciation = money(asset.accumulated_depreciation + amount)
    asset.annual_depreciation = money((asset.cost - asset.residual_value) / asset.useful_life_years)
    asset.closing_nbv = money(asset.cost - asset.accumulated_depreciation)
    asset.save(update_fields=["accumulated_depreciation", "annual_depreciation", "closing_nbv"])
    return DepreciationEntry.objects.create(
        asset=asset, period_start=period_start, period_end=period_end, amount=amount, journal=journal, created_by=user
    )


def gross_from_schedule(schedule):
    allowances = money(schedule.housing_allowance_monthly + schedule.transport_allowance_monthly + schedule.other_allowance_monthly)
    gross = money(schedule.basic_salary_monthly)
    return gross, allowances


@transaction.atomic
def post_payroll(payment_id, user):
    payment = PayrollPayment.objects.select_for_update().select_related("schedule").get(pk=payment_id)
    if payment.status != PayrollPayment.STATUS_DRAFT:
        reject("This payroll record is already posted.")
    if payment.deductions < 0 or payment.deductions > money(payment.gross_salary + payment.allowances):
        reject("Deductions must be configured as an amount and cannot exceed gross pay.")
    expected_net = money(payment.gross_salary + payment.allowances - payment.deductions)
    if payment.net_salary != expected_net:
        reject("Net salary must equal gross salary plus allowances minus the configured deductions.")
    salaries = account_by_code("6000")
    payable = account_by_code("2100")
    lines = [{"account": salaries, "debit": money(payment.gross_salary + payment.allowances), "credit": ZERO}]
    if payment.deductions:
        lines.append({"account": account_by_code("2110"), "debit": ZERO, "credit": payment.deductions})
    lines.append({"account": payable, "debit": ZERO, "credit": payment.net_salary})
    journal = create_journal(
        entry_date=payment.period_end,
        description=f"Payroll {payment.schedule.employee_id} {payment.period_start.isoformat()}",
        lines=lines,
        user=user,
        source_module="payroll",
        source_key=f"payroll:{payment.pk}",
        post=True,
    )
    payment.journal = journal
    payment.status = PayrollPayment.STATUS_POSTED
    payment.save(update_fields=["journal", "status"])
    return payment


@transaction.atomic
def pay_payroll(payment_id, user, paid_on, cash_account):
    payment = PayrollPayment.objects.select_for_update().get(pk=payment_id)
    if payment.status != PayrollPayment.STATUS_POSTED:
        reject("Recognize the payroll before paying it.")
    journal = create_journal(
        entry_date=paid_on,
        description=f"Salary payment {payment.schedule.employee_id}",
        lines=[
            {"account": account_by_code("2100"), "debit": payment.net_salary, "credit": ZERO},
            {"account": cash_account.ledger_account, "debit": ZERO, "credit": payment.net_salary},
        ],
        user=user,
        source_module="payroll",
        source_key=f"payroll-payment:{payment.pk}",
        post=True,
    )
    payment.payment_journal = journal
    payment.paid_on = paid_on
    payment.status = PayrollPayment.STATUS_PAID
    payment.save(update_fields=["payment_journal", "paid_on", "status"])
    return payment


@transaction.atomic
def close_period(period_id, user):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    if period.status == AccountingPeriod.STATUS_CLOSED:
        reject("This period is already closed.")
    if JournalEntry.objects.filter(period=period, status=JournalEntry.STATUS_DRAFT).exists():
        reject("Post or delete draft journals in this period before closing it.")
    period.status = AccountingPeriod.STATUS_CLOSED
    period.closed_at = timezone.now()
    period.closed_by = user
    period.save(update_fields=["status", "closed_at", "closed_by"])
    _audit("period-close", user, detail=period.name)
    return period


@transaction.atomic
def close_books_to_retained_earnings(period_id, user):
    period = AccountingPeriod.objects.select_for_update().get(pk=period_id)
    source_key = f"close:{period.pk}"
    if JournalEntry.objects.filter(source_key=source_key).exists():
        reject("Closing entries for this period already exist.")
    lines = []
    net = ZERO
    for account in LedgerAccount.objects.filter(account_type__in=[LedgerAccount.TYPE_REVENUE, LedgerAccount.TYPE_EXPENSE]):
        amount = account_balance(account, start=period.start_date, end=period.end_date)
        if amount == 0:
            continue
        if account.account_type == LedgerAccount.TYPE_REVENUE:
            lines.append({"account": account, "debit": amount, "credit": ZERO})
            net += amount
        else:
            lines.append({"account": account, "debit": ZERO, "credit": amount})
            net -= amount
    if not lines:
        reject("There is no posted profit or loss to close.")
    retained = account_by_code("3100")
    if net > 0:
        lines.append({"account": retained, "debit": ZERO, "credit": net})
    elif net < 0:
        lines.append({"account": retained, "debit": -net, "credit": ZERO})
    return create_journal(
        entry_date=period.end_date,
        description=f"Close {period.name} to retained earnings",
        lines=lines,
        user=user,
        source_module="periods",
        source_key=source_key,
        post=True,
        is_adjustment=period.status == AccountingPeriod.STATUS_CLOSED,
    )


def budget_variance(budget_id):
    budget = FinanceBudget.objects.prefetch_related("lines__account").get(pk=budget_id)
    rows = []
    for line in budget.lines.all():
        actual = account_balance(line.account, start=budget.start_date, end=budget.end_date)
        variance = money(actual - line.amount)
        percent = None
        if line.amount:
            percent = text_amount(variance / line.amount * Decimal(100))
        rows.append(
            {
                "code": line.account.code,
                "name": line.account.name,
                "budget": text_amount(line.amount),
                "actual": text_amount(actual),
                "variance": text_amount(variance),
                "variance_percent": percent,
            }
        )
    return {"budget": budget.name, "status": budget.status, "rows": rows, "note": "Budget figures do not change posted accounting entries."}


@transaction.atomic
def post_operational(*, source, source_id, source_key, amount, entry_date, description, debit_account, credit_account, user, programme=None, season=None, note=""):
    if OperationalPosting.objects.filter(source_key=source_key).exists():
        reject("This operational record has already been posted to the ledger.")
    amount = money(amount)
    if amount <= 0:
        reject("The posting amount must be positive.")
    journal = create_journal(
        entry_date=entry_date,
        description=description,
        lines=[
            {"account": debit_account, "debit": amount, "credit": ZERO},
            {"account": credit_account, "debit": ZERO, "credit": amount},
        ],
        user=user,
        source_module=source.lower(),
        source_key=source_key,
        programme=programme,
        season=season,
        post=True,
    )
    return OperationalPosting.objects.create(
        source=source,
        source_id=source_id,
        source_key=source_key,
        amount=amount,
        note=note,
        journal=journal,
        posted_by=user,
    )
