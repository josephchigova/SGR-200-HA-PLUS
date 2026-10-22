import csv
import io
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import FinanceAccessPermission
from apps.inputs.models import InputAllocation
from apps.production.models import GMBDelivery
from apps.programmes.models import Programme
from apps.recovery.models import InputDebt
from apps.subscriptions.models import FarmerSubscription

from . import ledger
from .models import (
    AccountingPeriod,
    Asset,
    BankStatement,
    BankStatementLine,
    CashBookAccount,
    CashMovement,
    ExpenseClaim,
    FinanceAuditEvent,
    FinanceBudget,
    JournalEntry,
    LedgerAccount,
    OperationalPosting,
    PayrollPayment,
    RecognizedReceipt,
    TradePayable,
    TradeReceivable,
)
from .serializers import (
    AccountingPeriodSerializer,
    BankStatementSerializer,
    CashBookAccountSerializer,
    CashMovementSerializer,
    ExpenseClaimSerializer,
    FinanceBudgetSerializer,
    JournalEntrySerializer,
    LedgerAccountSerializer,
    PayrollPaymentSerializer,
    RecognizedReceiptSerializer,
    TradePayableSerializer,
    TradeReceivableSerializer,
)


def parse_date(value, field):
    if not value:
        ledger.reject(f"{field} is required.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        ledger.reject(f"{field} must be a YYYY-MM-DD date.")


class LedgerAccountViewSet(viewsets.ModelViewSet):
    queryset = LedgerAccount.objects.all()
    serializer_class = LedgerAccountSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["post"])
    def ensure_defaults(self, request):
        created = ledger.ensure_default_chart()
        return Response({"created": created, "accounts": LedgerAccount.objects.count()})


class AccountingPeriodViewSet(viewsets.ModelViewSet):
    queryset = AccountingPeriod.objects.all()
    serializer_class = AccountingPeriodSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        period = ledger.close_period(pk, request.user)
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"], url_path="close-books")
    def close_books(self, request, pk=None):
        entry = ledger.close_books_to_retained_earnings(pk, request.user)
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)


class JournalEntryViewSet(viewsets.ModelViewSet):
    queryset = JournalEntry.objects.prefetch_related("lines__account").all()
    serializer_class = JournalEntrySerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def create(self, request, *args, **kwargs):
        programme = Programme.objects.filter(pk=request.data.get("programme")).first() if request.data.get("programme") else None
        entry = ledger.create_journal(
            entry_date=parse_date(request.data.get("entry_date"), "entry_date"),
            description=request.data.get("description") or "",
            lines=request.data.get("lines") or [],
            user=request.user,
            source_module=request.data.get("source_module") or "",
            programme=programme,
            post=bool(request.data.get("post")),
            is_adjustment=bool(request.data.get("is_adjustment")),
        )
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        entry = self.get_object()
        if entry.status != JournalEntry.STATUS_DRAFT:
            return Response({"detail": "Posted journal entries cannot be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def post_entry(self, request, pk=None):
        entry = ledger.post_journal(pk, request.user)
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        entry = ledger.reverse_journal(
            pk,
            request.user,
            parse_date(request.data.get("entry_date"), "entry_date"),
            request.data.get("description") or "",
        )
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)


class CashBookAccountViewSet(viewsets.ModelViewSet):
    queryset = CashBookAccount.objects.all()
    serializer_class = CashBookAccountSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]


class CashMovementViewSet(viewsets.ModelViewSet):
    queryset = CashMovement.objects.all()
    serializer_class = CashMovementSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        search = self.request.query_params.get("search")
        if start:
            queryset = queryset.filter(movement_date__gte=start)
        if end:
            queryset = queryset.filter(movement_date__lte=end)
        if search:
            queryset = queryset.filter(description__icontains=search)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post_entry(self, request, pk=None):
        movement = ledger.post_cash_movement(pk, request.user)
        return Response(self.get_serializer(movement).data)


class RecognizedReceiptViewSet(viewsets.ModelViewSet):
    queryset = RecognizedReceipt.objects.all()
    serializer_class = RecognizedReceiptSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        number = serializer.validated_data.get("receipt_number") or next_number("RCT", RecognizedReceipt, "receipt_number")
        serializer.save(receipt_number=number, created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def post_entry(self, request, pk=None):
        receipt = ledger.post_recognized_receipt(pk, request.user)
        return Response(self.get_serializer(receipt).data)


class ExpenseClaimViewSet(viewsets.ModelViewSet):
    queryset = ExpenseClaim.objects.all()
    serializer_class = ExpenseClaimSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(payee__icontains=search)
        return queryset

    def perform_create(self, serializer):
        reference = serializer.validated_data.get("reference") or next_number("EXP", ExpenseClaim, "reference")
        serializer.save(reference=reference, created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(self.get_serializer(ledger.approve_expense(pk, request.user)).data)

    @action(detail=True, methods=["post"])
    def recognize(self, request, pk=None):
        return Response(self.get_serializer(ledger.recognize_expense(pk, request.user)).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        cash_account = CashBookAccount.objects.get(pk=request.data.get("cash_account"))
        claim = ledger.pay_expense(pk, request.user, parse_date(request.data.get("paid_on"), "paid_on"), cash_account)
        return Response(self.get_serializer(claim).data)


class TradeReceivableViewSet(viewsets.ModelViewSet):
    queryset = TradeReceivable.objects.all()
    serializer_class = TradeReceivableSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        return Response(self.get_serializer(ledger.issue_receivable(pk, request.user)).data)

    @action(detail=True, methods=["post"])
    def collect(self, request, pk=None):
        cash_account = CashBookAccount.objects.get(pk=request.data.get("cash_account"))
        receivable = ledger.receive_receivable(
            pk,
            request.user,
            parse_date(request.data.get("received_on"), "received_on"),
            request.data.get("amount"),
            request.data.get("reference"),
            cash_account,
        )
        return Response(self.get_serializer(receivable).data)


class TradePayableViewSet(viewsets.ModelViewSet):
    queryset = TradePayable.objects.all()
    serializer_class = TradePayableSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        return Response(self.get_serializer(ledger.issue_payable(pk, request.user)).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        cash_account = CashBookAccount.objects.get(pk=request.data.get("cash_account"))
        payable = ledger.pay_payable(
            pk,
            request.user,
            parse_date(request.data.get("paid_on"), "paid_on"),
            request.data.get("amount"),
            request.data.get("reference"),
            cash_account,
        )
        return Response(self.get_serializer(payable).data)


class PayrollPaymentViewSet(viewsets.ModelViewSet):
    queryset = PayrollPayment.objects.select_related("schedule")
    serializer_class = PayrollPaymentSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        schedule = serializer.validated_data["schedule"]
        gross, allowances = ledger.gross_from_schedule(schedule)
        deductions = ledger.money(serializer.validated_data.get("deductions") or 0)
        serializer.save(
            gross_salary=gross,
            allowances=allowances,
            deductions=deductions,
            net_salary=ledger.money(gross + allowances - deductions),
            created_by=self.request.user,
        )

    @action(detail=True, methods=["post"])
    def post_entry(self, request, pk=None):
        return Response(self.get_serializer(ledger.post_payroll(pk, request.user)).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        cash_account = CashBookAccount.objects.get(pk=request.data.get("cash_account"))
        payment = ledger.pay_payroll(pk, request.user, parse_date(request.data.get("paid_on"), "paid_on"), cash_account)
        return Response(self.get_serializer(payment).data)


class FinanceBudgetViewSet(viewsets.ModelViewSet):
    queryset = FinanceBudget.objects.prefetch_related("lines").all()
    serializer_class = FinanceBudgetSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        budget = self.get_object()
        budget.status = FinanceBudget.STATUS_APPROVED
        budget.approved_by = request.user
        budget.save(update_fields=["status", "approved_by"])
        return Response(self.get_serializer(budget).data)

    @action(detail=True, methods=["get"])
    def variance(self, request, pk=None):
        return Response(ledger.budget_variance(pk))


class BankStatementViewSet(viewsets.ModelViewSet):
    queryset = BankStatement.objects.prefetch_related("lines").all()
    serializer_class = BankStatementSerializer
    permission_classes = [FinanceAccessPermission]
    http_method_names = ["get", "post", "head", "options"]

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        statement = self.get_object()
        line = statement.lines.get(pk=request.data.get("line"))
        movement = CashMovement.objects.get(pk=request.data.get("movement"), status=CashMovement.STATUS_POSTED)
        side = request.data.get("side") or BankStatementLine.SIDE_SOURCE
        same_account = movement.cash_account_id == statement.cash_account_id or (
            movement.transfer_to_id == statement.cash_account_id and side == BankStatementLine.SIDE_DESTINATION
        )
        if not same_account:
            ledger.reject("The cashbook transaction does not belong to this bank account.")
        line.matched_movement = movement
        line.matched_side = side
        line.save(update_fields=["matched_movement", "matched_side"])
        return Response(self.get_serializer(statement).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        statement = self.get_object()
        book = ledger.account_balance(statement.cash_account.ledger_account, as_of=statement.statement_date)
        difference = ledger.money(statement.closing_balance - book)
        unmatched = statement.lines.filter(matched_movement__isnull=True).count()
        if difference != 0:
            return Response(
                {
                    "detail": "The statement does not reconcile to the ledger.",
                    "book_balance": ledger.text_amount(book),
                    "statement_closing": ledger.text_amount(statement.closing_balance),
                    "difference": ledger.text_amount(difference),
                    "unmatched_lines": unmatched,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        statement.status = BankStatement.STATUS_RECONCILED
        statement.reconciled_at = timezone.now()
        statement.reconciled_by = request.user
        statement.save(update_fields=["status", "reconciled_at", "reconciled_by"])
        payload = self.get_serializer(statement).data
        payload["book_balance"] = ledger.text_amount(book)
        payload["difference"] = "0.00"
        payload["unmatched_lines"] = unmatched
        return Response(payload)


class AssetDepreciationView(APIView):
    permission_classes = [FinanceAccessPermission]

    def post(self, request, pk):
        asset = Asset.objects.get(pk=pk)
        entry = ledger.post_depreciation(
            asset,
            parse_date(request.data.get("period_start"), "period_start"),
            parse_date(request.data.get("period_end"), "period_end"),
            request.user,
        )
        return Response(
            {"id": entry.pk, "amount": ledger.text_amount(entry.amount), "journal": entry.journal.reference},
            status=status.HTTP_201_CREATED,
        )


class OperationalPostingView(APIView):
    permission_classes = [FinanceAccessPermission]

    def post(self, request):
        source = request.data.get("source")
        source_id = int(request.data.get("source_id"))
        amount = request.data.get("amount")
        debit = LedgerAccount.objects.get(pk=request.data.get("debit_account"))
        credit = LedgerAccount.objects.get(pk=request.data.get("credit_account"))
        programme = Programme.objects.filter(pk=request.data.get("programme")).first()
        external_reference = request.data.get("external_reference") or "balance"
        posting = ledger.post_operational(
            source=source,
            source_id=source_id,
            source_key=f"{source}:{source_id}:{external_reference}",
            amount=amount,
            entry_date=parse_date(request.data.get("entry_date"), "entry_date"),
            description=request.data.get("description") or f"{source} {source_id}",
            debit_account=debit,
            credit_account=credit,
            user=request.user,
            programme=programme,
            note=request.data.get("note") or "Explicit posting. Operational balances were not changed.",
        )
        return Response({"id": posting.pk, "journal": posting.journal.reference, "amount": ledger.text_amount(posting.amount)}, status=status.HTTP_201_CREATED)


class FinanceReportView(APIView):
    permission_classes = [FinanceAccessPermission]

    def get(self, request, report):
        payload = build_report(report, request)
        export_format = request.query_params.get("format")
        if export_format == "csv":
            return csv_response(report, payload)
        if export_format == "pdf":
            return pdf_response(report, payload)
        return Response(payload)


def build_report(report, request):
    params = request.query_params
    start = parse_date(params.get("start") or "1900-01-01", "start") if report != "balance-sheet" else None
    end = parse_date(params.get("end") or timezone.localdate().isoformat(), "end") if report != "balance-sheet" else None
    as_of = parse_date(params.get("as_of") or params.get("end") or timezone.localdate().isoformat(), "as_of")
    if report == "trial-balance":
        return ledger.trial_balance(as_of)
    if report == "profit-loss":
        compare_start = params.get("compare_start")
        compare_end = params.get("compare_end")
        return ledger.profit_and_loss(
            parse_date(params.get("start"), "start"),
            parse_date(params.get("end"), "end"),
            parse_date(compare_start, "compare_start") if compare_start else None,
            parse_date(compare_end, "compare_end") if compare_end else None,
        )
    if report == "balance-sheet":
        compare = params.get("compare_as_of")
        payload = ledger.balance_sheet(as_of, parse_date(compare, "compare_as_of") if compare else None)
        from .workbook_statement import workbook_opening_position
        payload["workbook"] = workbook_opening_position()
        return payload
    if report == "cash-flow":
        return ledger.cash_flow(parse_date(params.get("start"), "start"), parse_date(params.get("end"), "end"))
    if report == "general-ledger":
        return ledger.general_ledger(params.get("account"), parse_date(params.get("start"), "start"), parse_date(params.get("end"), "end"))
    if report == "journal-register":
        entries = JournalEntry.objects.filter(status__in=ledger.POSTED_STATUSES, entry_date__gte=start, entry_date__lte=end)
        return {"rows": JournalEntrySerializer(entries, many=True).data}
    if report == "dashboard":
        return ledger.dashboard(parse_date(params.get("start"), "start"), parse_date(params.get("end"), "end"))
    if report == "receivables-aging":
        records = TradeReceivable.objects.exclude(status=TradeReceivable.STATUS_DRAFT)
        return ledger.aging_rows(records, as_of, lambda row: row.outstanding, lambda row: row.due_date)
    if report == "payables-aging":
        records = TradePayable.objects.exclude(status=TradePayable.STATUS_DRAFT)
        return ledger.aging_rows(records, as_of, lambda row: row.outstanding, lambda row: row.due_date)
    if report == "budget-variance":
        return ledger.budget_variance(params.get("budget"))
    if report == "asset-register":
        rows = []
        for asset in Asset.objects.all():
            rows.append(
                {
                    "asset_id": asset.asset_id,
                    "description": asset.description,
                    "cost": ledger.text_amount(asset.cost),
                    "accumulated_depreciation": ledger.text_amount(asset.accumulated_depreciation),
                    "net_book_value": ledger.text_amount(asset.closing_nbv),
                }
            )
        return {"rows": rows, "note": "Net book value changes only when a depreciation entry is posted."}
    if report == "operations":
        return operations_report(params)
    if report == "audit":
        events = FinanceAuditEvent.objects.select_related("actor", "journal").order_by("-created_at")[:100]
        return {
            "rows": [
                {"action": event.action, "actor": getattr(event.actor, "email", ""), "journal": getattr(event.journal, "reference", ""), "detail": event.detail, "created_at": event.created_at.isoformat()}
                for event in events
            ]
        }
    ledger.reject("This report is not available.")


def operations_report(params):
    season_name = params.get("season_name") or ""
    programme_id = params.get("programme")
    subscriptions = FarmerSubscription.objects.all()
    allocations = InputAllocation.objects.all()
    debts = InputDebt.objects.all()
    deliveries = GMBDelivery.objects.all()
    if season_name:
        subscriptions = subscriptions.filter(season=season_name)
        deliveries = deliveries.filter(season__name=season_name)
    if programme_id:
        allocations = allocations.filter(programme_id=programme_id)
        debts = debts.filter(programme_id=programme_id)
        programme = Programme.objects.filter(pk=programme_id).first()
        if programme:
            deliveries = deliveries.filter(season_id=programme.season_id)
    posted = OperationalPosting.objects.all()
    if programme_id:
        posted = posted.filter(journal__programme_id=programme_id)
    expected = subscriptions.aggregate(total=Sum("expected_amount"))["total"] or 0
    paid = subscriptions.aggregate(total=Sum("paid_amount"))["total"] or 0
    collection = None
    if expected:
        collection = ledger.text_amount(ledger.money(paid) / ledger.money(expected) * Decimal("100"))
    programmes = [
        {
            "programme": row["programme__name"] or "Unassigned",
            "hectares": ledger.text_amount(row["hectares"] or 0),
            "cost": ledger.text_amount(row["cost"] or 0),
        }
        for row in allocations.values("programme__name").annotate(hectares=Sum("hectares"), cost=Sum("total_input_cost")).order_by("programme__name")
    ]
    return {
        "subscriptions": {
            "expected": ledger.text_amount(expected),
            "paid": ledger.text_amount(paid),
            "outstanding": ledger.text_amount(subscriptions.aggregate(total=Sum("outstanding_amount"))["total"] or 0),
            "ledger_posted": ledger.text_amount(posted.filter(source=OperationalPosting.SOURCE_SUBSCRIPTION).aggregate(total=Sum("amount"))["total"] or 0),
            "collection_percent": collection,
            "note": "Expected and paid amounts are operational subscription records. Only the ledger amount has been recognized as subscription revenue.",
        },
        "input_allocations": {
            "total_input_cost": ledger.text_amount(allocations.aggregate(total=Sum("total_input_cost"))["total"] or 0),
            "hectares": ledger.text_amount(allocations.aggregate(total=Sum("hectares"))["total"] or 0),
            "programmes": programmes,
            "note": "Allocation cost and hectares are operational programme figures. They are not accounting expenses or income.",
        },
        "input_debts": {
            "total_debt": ledger.text_amount(debts.aggregate(total=Sum("total_debt"))["total"] or 0),
            "sgr_amount": ledger.text_amount(debts.aggregate(total=Sum("sgr_amount"))["total"] or 0),
            "arda_amount": ledger.text_amount(debts.aggregate(total=Sum("arda_amount"))["total"] or 0),
            "amount_recovered": ledger.text_amount(debts.aggregate(total=Sum("amount_recovered"))["total"] or 0),
            "outstanding": ledger.text_amount(debts.aggregate(total=Sum("outstanding_monetary_balance"))["total"] or 0),
            "recognized_receivables": TradeReceivable.objects.filter(input_debt__isnull=False).count(),
            "note": "Farmer input debt stays on the operational record. It is a ledger receivable only when a recognized receivable is issued.",
        },
        "deliveries": {
            "tonnes": ledger.text_amount(deliveries.aggregate(total=Sum("tonnes"))["total"] or 0),
            "recorded_value": ledger.text_amount(deliveries.aggregate(total=Sum("value"))["total"] or 0),
            "amount_recovered": ledger.text_amount(deliveries.aggregate(total=Sum("amount_recovered"))["total"] or 0),
            "farmer_balance": ledger.text_amount(deliveries.aggregate(total=Sum("farmer_balance"))["total"] or 0),
            "note": "Delivery value, recovery, and farmer balance are the amounts already stored on the delivery. No grain price is calculated here.",
        },
    }


def next_number(prefix, model, field):
    today = timezone.localdate()
    stem = f"{prefix}-{today:%Y%m%d}-"
    last = model.objects.filter(**{f"{field}__startswith": stem}).order_by(f"-{field}").first()
    number = 1
    if last:
        try:
            number = int(getattr(last, field).rsplit("-", 1)[-1]) + 1
        except ValueError:
            number = 1
    return f"{stem}{number:04d}"


def flatten(payload, prefix=""):
    rows = []
    if isinstance(payload, list):
        for item in payload:
            rows.extend(flatten(item))
        return rows
    if isinstance(payload, dict):
        nested = {key: value for key, value in payload.items() if isinstance(value, (list, dict))}
        flat = {key: value for key, value in payload.items() if not isinstance(value, (list, dict))}
        if flat:
            rows.append(flat)
        for value in nested.values():
            rows.extend(flatten(value))
        return rows
    return rows


def csv_response(report, payload):
    rows = flatten(payload) or [{}]
    fieldnames = sorted({key for row in rows for key in row})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{report}.csv"'
    return response


def pdf_response(report, payload):
    lines = [report.replace("-", " ").title(), ""]
    for row in flatten(payload)[:80]:
        lines.append(" | ".join(f"{key}: {value}" for key, value in row.items()))
    content = pdf_document(lines)
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{report}.pdf"'
    return response


def pdf_document(lines):
    commands = ["BT /F1 9 Tf 40 800 Td 12 TL"]
    for line in lines[:60]:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped[:140]}) Tj T*")
    commands.append("ET")
    stream = "\n".join(commands).encode()
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n")
    objects.append(b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n")
    objects.append(f"4 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    objects.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)
