from rest_framework import serializers

from .models import (
    AccountingPeriod,
    Asset,
    BankStatement,
    BankStatementLine,
    CashBookAccount,
    CashMovement,
    Expense,
    ExpenseClaim,
    FinanceBudget,
    FinanceBudgetLine,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    PayrollEntry,
    PayrollPayment,
    Receipt,
    RecognizedReceipt,
    TradePayable,
    TradeReceivable,
)


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = "__all__"


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = "__all__"


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = "__all__"


class PayrollEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollEntry
        fields = "__all__"


class LedgerAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerAccount
        fields = [
            "id", "code", "name", "account_type", "category", "cash_flow_section",
            "normal_balance", "description", "parent", "is_active", "created_at",
        ]
        read_only_fields = ["created_at"]


class AccountingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingPeriod
        fields = ["id", "name", "start_date", "end_date", "status", "closed_at", "closed_by", "created_at"]
        read_only_fields = ["status", "closed_at", "closed_by", "created_at"]


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalLine
        fields = ["id", "account", "account_code", "account_name", "memo", "debit", "credit"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id", "reference", "entry_date", "description", "source_module", "source_key",
            "period", "status", "is_adjustment", "programme", "season", "reversal_of",
            "posted_at", "posted_by", "created_at", "lines",
        ]
        read_only_fields = fields


class CashBookAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashBookAccount
        fields = ["id", "name", "kind", "ledger_account", "is_active", "created_at"]
        read_only_fields = ["created_at"]


class CashMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashMovement
        fields = [
            "id", "cash_account", "kind", "movement_date", "amount", "counterparty",
            "reference", "description", "transfer_to", "offset_account", "status", "journal", "created_at",
        ]
        read_only_fields = ["status", "journal", "created_at"]


class RecognizedReceiptSerializer(serializers.ModelSerializer):
    receipt_number = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = RecognizedReceipt
        fields = [
            "id", "receipt_number", "payer", "received_on", "amount", "method", "external_reference",
            "recognition", "credit_account", "cash_account", "farmer", "programme", "subscription",
            "status", "journal", "created_at",
        ]
        read_only_fields = ["status", "journal", "created_at"]


class ExpenseClaimSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = ExpenseClaim
        fields = [
            "id", "reference", "payee", "expense_date", "amount", "method", "description", "basis",
            "expense_account", "payable_account", "cash_account", "programme", "status",
            "recognition_journal", "payment_journal", "created_at",
        ]
        read_only_fields = ["status", "recognition_journal", "payment_journal", "created_at"]


class TradeReceivableSerializer(serializers.ModelSerializer):
    outstanding = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = TradeReceivable
        fields = [
            "id", "party", "reference", "kind", "credit_treatment", "issue_date", "due_date",
            "original_amount", "amount_received", "outstanding", "receivable_account", "credit_account",
            "programme", "input_debt", "status", "journal", "created_at",
        ]
        read_only_fields = ["amount_received", "outstanding", "status", "journal", "created_at"]


class TradePayableSerializer(serializers.ModelSerializer):
    outstanding = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = TradePayable
        fields = [
            "id", "supplier", "invoice_number", "invoice_date", "due_date", "amount", "amount_paid",
            "outstanding", "classification", "payable_account", "offset_account", "status", "journal", "created_at",
        ]
        read_only_fields = ["amount_paid", "outstanding", "status", "journal", "created_at"]


class PayrollPaymentSerializer(serializers.ModelSerializer):
    employee_id = serializers.CharField(source="schedule.employee_id", read_only=True)

    class Meta:
        model = PayrollPayment
        fields = [
            "id", "schedule", "employee_id", "period_start", "period_end", "gross_salary", "allowances",
            "deductions", "net_salary", "status", "journal", "payment_journal", "paid_on", "created_at",
        ]
        read_only_fields = ["gross_salary", "allowances", "net_salary", "status", "journal", "payment_journal", "created_at"]


class FinanceBudgetLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinanceBudgetLine
        fields = ["id", "account", "amount"]


class FinanceBudgetSerializer(serializers.ModelSerializer):
    lines = FinanceBudgetLineSerializer(many=True, required=False)

    class Meta:
        model = FinanceBudget
        fields = ["id", "name", "start_date", "end_date", "status", "lines", "created_at"]
        read_only_fields = ["status", "created_at"]

    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        budget = FinanceBudget.objects.create(**validated_data)
        for line in lines:
            FinanceBudgetLine.objects.create(budget=budget, **line)
        return budget


class BankStatementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankStatementLine
        fields = ["id", "txn_date", "amount", "description", "reference", "matched_movement", "matched_side"]
        read_only_fields = ["matched_movement", "matched_side"]


class BankStatementSerializer(serializers.ModelSerializer):
    lines = BankStatementLineSerializer(many=True, required=False)

    class Meta:
        model = BankStatement
        fields = ["id", "cash_account", "statement_date", "opening_balance", "closing_balance", "status", "lines", "created_at"]
        read_only_fields = ["status", "created_at"]

    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        statement = BankStatement.objects.create(**validated_data)
        for line in lines:
            BankStatementLine.objects.create(statement=statement, **line)
        return statement
