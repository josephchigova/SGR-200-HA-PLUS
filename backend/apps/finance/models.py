from django.conf import settings
from django.db import models


class Receipt(models.Model):
    month = models.DateField(null=True, blank=True)
    receipt_date = models.DateField(null=True, blank=True)
    farmer_name = models.CharField(max_length=255, blank=True)
    amount_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_type = models.CharField(max_length=80, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-receipt_date", "-id"]


class Expense(models.Model):
    expense_date = models.DateField(null=True, blank=True)
    particulars = models.CharField(max_length=255)
    amount_debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reimbursement = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_expense = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_row = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-expense_date", "-id"]


class AssetCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Asset(models.Model):
    CONDITION_NEW = "NEW"
    CONDITION_GOOD = "GOOD"
    CONDITION_FAIR = "FAIR"
    CONDITION_POOR = "POOR"
    CONDITION_DAMAGED = "DAMAGED"
    CONDITION_CHOICES = [
        (CONDITION_NEW, "New"),
        (CONDITION_GOOD, "Good"),
        (CONDITION_FAIR, "Fair"),
        (CONDITION_POOR, "Poor"),
        (CONDITION_DAMAGED, "Damaged"),
    ]

    STATUS_ACTIVE = "ACTIVE"
    STATUS_MAINTENANCE = "UNDER_MAINTENANCE"
    STATUS_DISPOSED = "DISPOSED"
    STATUS_WRITTEN_OFF = "WRITTEN_OFF"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_MAINTENANCE, "Under Maintenance"),
        (STATUS_DISPOSED, "Disposed"),
        (STATUS_WRITTEN_OFF, "Written Off"),
    ]

    METHOD_NONE = "NONE"
    METHOD_STRAIGHT_LINE = "STRAIGHT_LINE"
    METHOD_REDUCING = "REDUCING_BALANCE"
    METHOD_CHOICES = [
        (METHOD_NONE, "No depreciation"),
        (METHOD_STRAIGHT_LINE, "Straight line"),
        (METHOD_REDUCING, "Reducing balance"),
    ]

    asset_id = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=180, blank=True)
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=120, blank=True)
    category_ref = models.ForeignKey(
        AssetCategory, null=True, blank=True, on_delete=models.PROTECT, related_name="assets"
    )
    purchase_date = models.DateField(null=True, blank=True)
    supplier = models.CharField(max_length=180, blank=True)
    cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    current_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    location = models.CharField(max_length=180, blank=True)
    department = models.CharField(max_length=180, blank=True)
    responsible_person = models.CharField(max_length=180, blank=True)
    condition = models.CharField(max_length=16, choices=CONDITION_CHOICES, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    warranty_expiry = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    residual_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    useful_life_years = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    depreciation_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_STRAIGHT_LINE)
    depreciation_rate = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    annual_depreciation = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    accumulated_depreciation = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    closing_nbv = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assets_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assets_updated"
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["asset_id"]

    def __str__(self):
        return f"{self.asset_id} {self.name or self.description}"

    @property
    def display_name(self):
        return self.name or self.description


class AssetDocument(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=180, blank=True)
    file = models.FileField(upload_to="finance/assets/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_documents_uploaded"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]


class AssetValuation(models.Model):
    KIND_ACQUISITION = "ACQUISITION"
    KIND_REVALUATION = "REVALUATION"
    KIND_CHOICES = [
        (KIND_ACQUISITION, "Acquisition cost"),
        (KIND_REVALUATION, "Estimated value"),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="valuations")
    valued_on = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_valuations_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valued_on", "-id"]


class AssetMaintenance(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="maintenance_records")
    activity_date = models.DateField()
    description = models.CharField(max_length=255)
    cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    supplier = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_maintenance_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-activity_date", "-id"]


class AssetTransfer(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="transfers")
    transfer_date = models.DateField()
    from_location = models.CharField(max_length=180, blank=True)
    to_location = models.CharField(max_length=180, blank=True)
    from_department = models.CharField(max_length=180, blank=True)
    to_department = models.CharField(max_length=180, blank=True)
    from_person = models.CharField(max_length=180, blank=True)
    to_person = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_transfers_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transfer_date", "-id"]


class AssetDisposal(models.Model):
    KIND_DISPOSED = "DISPOSED"
    KIND_WRITTEN_OFF = "WRITTEN_OFF"
    KIND_CHOICES = [
        (KIND_DISPOSED, "Disposed"),
        (KIND_WRITTEN_OFF, "Written Off"),
    ]

    asset = models.OneToOneField(Asset, on_delete=models.PROTECT, related_name="disposal")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    disposed_on = models.DateField()
    reason = models.TextField()
    proceeds = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_disposals_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-disposed_on", "-id"]


class AssetAuditEvent(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="audit_events")
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="asset_audit_events"
    )
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class PayrollEntry(models.Model):
    employee_id = models.CharField(max_length=80, unique=True)
    employee_position = models.CharField(max_length=255)
    department = models.CharField(max_length=120, blank=True)
    basic_salary_monthly = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    housing_allowance_monthly = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transport_allowance_monthly = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_allowance_monthly = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_monthly_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    annual_salary_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    annual_employment_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)


class LedgerAccount(models.Model):
    TYPE_ASSET = "ASSET"
    TYPE_LIABILITY = "LIABILITY"
    TYPE_EQUITY = "EQUITY"
    TYPE_REVENUE = "REVENUE"
    TYPE_EXPENSE = "EXPENSE"
    TYPE_CHOICES = [
        (TYPE_ASSET, "Asset"),
        (TYPE_LIABILITY, "Liability"),
        (TYPE_EQUITY, "Equity"),
        (TYPE_REVENUE, "Revenue"),
        (TYPE_EXPENSE, "Expense"),
    ]

    CATEGORY_CASH = "CASH"
    CATEGORY_BANK = "BANK"
    CATEGORY_RECEIVABLE = "RECEIVABLE"
    CATEGORY_INVENTORY = "INVENTORY"
    CATEGORY_PPE = "PPE"
    CATEGORY_CONTRA_ASSET = "CONTRA_ASSET"
    CATEGORY_PAYABLE = "PAYABLE"
    CATEGORY_EQUITY = "EQUITY"
    CATEGORY_RETAINED = "RETAINED_EARNINGS"
    CATEGORY_REVENUE = "REVENUE"
    CATEGORY_EXPENSE = "EXPENSE"
    CATEGORY_OTHER = "OTHER"
    CATEGORY_CHOICES = [
        (CATEGORY_CASH, "Cash"),
        (CATEGORY_BANK, "Bank"),
        (CATEGORY_RECEIVABLE, "Receivable"),
        (CATEGORY_INVENTORY, "Inventory"),
        (CATEGORY_PPE, "Property, plant and equipment"),
        (CATEGORY_CONTRA_ASSET, "Contra asset"),
        (CATEGORY_PAYABLE, "Payable"),
        (CATEGORY_EQUITY, "Equity"),
        (CATEGORY_RETAINED, "Retained earnings"),
        (CATEGORY_REVENUE, "Revenue"),
        (CATEGORY_EXPENSE, "Expense"),
        (CATEGORY_OTHER, "Other"),
    ]

    FLOW_OPERATING = "OPERATING"
    FLOW_INVESTING = "INVESTING"
    FLOW_FINANCING = "FINANCING"
    FLOW_NON_CASH = "NON_CASH"
    FLOW_NONE = "NONE"
    FLOW_CHOICES = [
        (FLOW_OPERATING, "Operating"),
        (FLOW_INVESTING, "Investing"),
        (FLOW_FINANCING, "Financing"),
        (FLOW_NON_CASH, "Non-cash"),
        (FLOW_NONE, "Cash equivalent"),
    ]

    NORMAL_DEBIT = "DEBIT"
    NORMAL_CREDIT = "CREDIT"
    NORMAL_CHOICES = [(NORMAL_DEBIT, "Debit"), (NORMAL_CREDIT, "Credit")]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=180)
    account_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER)
    cash_flow_section = models.CharField(max_length=20, choices=FLOW_CHOICES, default=FLOW_OPERATING)
    normal_balance = models.CharField(max_length=10, choices=NORMAL_CHOICES)
    description = models.TextField(blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="ledger_accounts_created"
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class AccountingPeriod(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_CLOSED = "CLOSED"
    STATUS_CHOICES = [(STATUS_OPEN, "Open"), (STATUS_CLOSED, "Closed")]

    name = models.CharField(max_length=120)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounting_periods_closed"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="accounting_period_dates"),
            models.UniqueConstraint(fields=["start_date", "end_date"], name="unique_accounting_period_dates"),
        ]

    def __str__(self):
        return self.name


class JournalEntry(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_POSTED = "POSTED"
    STATUS_REVERSED = "REVERSED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_POSTED, "Posted"),
        (STATUS_REVERSED, "Reversed"),
    ]

    reference = models.CharField(max_length=40, unique=True)
    entry_date = models.DateField()
    description = models.CharField(max_length=255)
    source_module = models.CharField(max_length=40, blank=True)
    source_key = models.CharField(max_length=160, blank=True)
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT, related_name="journal_entries")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_adjustment = models.BooleanField(default=False)
    programme = models.ForeignKey("programmes.Programme", null=True, blank=True, on_delete=models.SET_NULL, related_name="journal_entries")
    season = models.ForeignKey("programmes.Season", null=True, blank=True, on_delete=models.SET_NULL, related_name="journal_entries")
    reversal_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversals")
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="journal_entries_posted"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="journal_entries_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-entry_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_key"],
                condition=~models.Q(source_key=""),
                name="unique_journal_source_key",
            ),
        ]

    def __str__(self):
        return self.reference


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="lines")
    memo = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(debit__gte=0) & models.Q(credit__gte=0), name="journal_line_non_negative"),
            models.CheckConstraint(
                condition=~(models.Q(debit__gt=0) & models.Q(credit__gt=0)),
                name="journal_line_one_side",
            ),
            models.CheckConstraint(condition=models.Q(debit__gt=0) | models.Q(credit__gt=0), name="journal_line_has_amount"),
        ]


class FinanceAuditEvent(models.Model):
    action = models.CharField(max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="finance_audit_events")
    journal = models.ForeignKey(JournalEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events")
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class CashBookAccount(models.Model):
    KIND_CASH = "CASH"
    KIND_BANK = "BANK"
    KIND_CHOICES = [(KIND_CASH, "Cash"), (KIND_BANK, "Bank")]

    name = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    ledger_account = models.OneToOneField(LedgerAccount, on_delete=models.PROTECT, related_name="cash_book")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CashMovement(models.Model):
    KIND_RECEIPT = "RECEIPT"
    KIND_PAYMENT = "PAYMENT"
    KIND_TRANSFER = "TRANSFER"
    KIND_CHOICES = [
        (KIND_RECEIPT, "Receipt"),
        (KIND_PAYMENT, "Payment"),
        (KIND_TRANSFER, "Transfer"),
    ]
    STATUS_DRAFT = "DRAFT"
    STATUS_POSTED = "POSTED"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_POSTED, "Posted")]

    cash_account = models.ForeignKey(CashBookAccount, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    movement_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    counterparty = models.CharField(max_length=180, blank=True)
    reference = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255)
    transfer_to = models.ForeignKey(CashBookAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_transfers")
    offset_account = models.ForeignKey(LedgerAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="cash_movements")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="cash_movement")
    attachment = models.FileField(upload_to="finance/cashbook/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="cash_movements_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-movement_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="cash_movement_positive"),
        ]


class RecognizedReceipt(models.Model):
    """Money received. Recognition says whether it is earned, in advance, or held for another party."""

    EARNED = "EARNED"
    ADVANCE = "ADVANCE"
    AGENCY = "AGENCY"
    RECOGNITION_CHOICES = [
        (EARNED, "Income earned"),
        (ADVANCE, "Received in advance"),
        (AGENCY, "Received for another party"),
    ]
    STATUS_DRAFT = "DRAFT"
    STATUS_POSTED = "POSTED"

    receipt_number = models.CharField(max_length=40, unique=True)
    payer = models.CharField(max_length=180)
    received_on = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    method = models.CharField(max_length=40, blank=True)
    external_reference = models.CharField(max_length=80, blank=True)
    recognition = models.CharField(max_length=12, choices=RECOGNITION_CHOICES)
    credit_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="recognized_receipts")
    cash_account = models.ForeignKey(CashBookAccount, on_delete=models.PROTECT, related_name="recognized_receipts")
    farmer = models.ForeignKey("farmers.Farmer", null=True, blank=True, on_delete=models.SET_NULL, related_name="recognized_receipts")
    programme = models.ForeignKey("programmes.Programme", null=True, blank=True, on_delete=models.SET_NULL, related_name="recognized_receipts")
    subscription = models.ForeignKey(
        "subscriptions.FarmerSubscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="recognized_receipts"
    )
    status = models.CharField(max_length=12, default=STATUS_DRAFT)
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="recognized_receipt")
    attachment = models.FileField(upload_to="finance/receipts/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="recognized_receipts_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="recognized_receipt_positive"),
            models.UniqueConstraint(
                fields=["subscription", "external_reference"],
                condition=~models.Q(external_reference="") & models.Q(subscription__isnull=False),
                name="unique_subscription_receipt_reference",
            ),
        ]


class ExpenseClaim(models.Model):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"
    BASIS_CHOICES = [(ACCRUAL, "Accrual"), (CASH, "Cash")]
    STATUS_DRAFT = "DRAFT"
    STATUS_APPROVED = "APPROVED"
    STATUS_RECOGNIZED = "RECOGNIZED"
    STATUS_PAID = "PAID"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_RECOGNIZED, "Recognized"),
        (STATUS_PAID, "Paid"),
    ]

    reference = models.CharField(max_length=40, unique=True)
    payee = models.CharField(max_length=180)
    expense_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    method = models.CharField(max_length=40, blank=True)
    description = models.CharField(max_length=255)
    basis = models.CharField(max_length=10, choices=BASIS_CHOICES, default=ACCRUAL)
    expense_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="expense_claims")
    payable_account = models.ForeignKey(
        LedgerAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="accrued_expense_claims"
    )
    cash_account = models.ForeignKey(CashBookAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="expense_claims")
    programme = models.ForeignKey("programmes.Programme", null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_claims")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    recognition_journal = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="recognized_expense"
    )
    payment_journal = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="paid_expense"
    )
    attachment = models.FileField(upload_to="finance/expenses/", blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_claims_approved"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="expense_claims_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-expense_date", "-id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_claim_positive")]


class TradeReceivable(models.Model):
    KIND_TRADE = "TRADE"
    KIND_PROGRAMME = "PROGRAMME"
    KIND_FARMER = "FARMER"
    KIND_CHOICES = [
        (KIND_TRADE, "Trade receivable"),
        (KIND_PROGRAMME, "Programme receivable"),
        (KIND_FARMER, "Recognized farmer receivable"),
    ]
    CREDIT_REVENUE = "REVENUE"
    CREDIT_LIABILITY = "LIABILITY"
    CREDIT_CHOICES = [(CREDIT_REVENUE, "Credit revenue"), (CREDIT_LIABILITY, "Credit a liability")]
    STATUS_DRAFT = "DRAFT"
    STATUS_OPEN = "OPEN"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_SETTLED = "SETTLED"

    party = models.CharField(max_length=180)
    reference = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_TRADE)
    credit_treatment = models.CharField(max_length=12, choices=CREDIT_CHOICES, default=CREDIT_REVENUE)
    issue_date = models.DateField()
    due_date = models.DateField()
    original_amount = models.DecimalField(max_digits=16, decimal_places=2)
    amount_received = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    receivable_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="receivables")
    credit_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="receivable_credits")
    programme = models.ForeignKey("programmes.Programme", null=True, blank=True, on_delete=models.SET_NULL, related_name="trade_receivables")
    input_debt = models.OneToOneField("recovery.InputDebt", null=True, blank=True, on_delete=models.PROTECT, related_name="recognized_receivable")
    status = models.CharField(max_length=12, default=STATUS_DRAFT)
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="trade_receivable")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="receivables_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(original_amount__gt=0), name="receivable_positive")]

    @property
    def outstanding(self):
        return self.original_amount - self.amount_received


class ReceivablePayment(models.Model):
    receivable = models.ForeignKey(TradeReceivable, on_delete=models.PROTECT, related_name="payments")
    received_on = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    cash_account = models.ForeignKey(CashBookAccount, on_delete=models.PROTECT, related_name="receivable_payments")
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="receivable_payment")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="receivable_payments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="receivable_payment_positive")]


class TradePayable(models.Model):
    CLASS_EXPENSE = "EXPENSE"
    CLASS_ASSET = "ASSET"
    CLASS_CHOICES = [(CLASS_EXPENSE, "Expense"), (CLASS_ASSET, "Asset")]
    STATUS_DRAFT = "DRAFT"
    STATUS_OPEN = "OPEN"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_SETTLED = "SETTLED"

    supplier = models.CharField(max_length=180)
    invoice_number = models.CharField(max_length=80)
    invoice_date = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    classification = models.CharField(max_length=12, choices=CLASS_CHOICES, default=CLASS_EXPENSE)
    payable_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="payables")
    offset_account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="payable_offsets")
    status = models.CharField(max_length=12, default=STATUS_DRAFT)
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="trade_payable")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payables_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payable_positive"),
            models.UniqueConstraint(fields=["supplier", "invoice_number"], name="unique_supplier_invoice"),
        ]

    @property
    def outstanding(self):
        return self.amount - self.amount_paid


class PayablePayment(models.Model):
    payable = models.ForeignKey(TradePayable, on_delete=models.PROTECT, related_name="payments")
    paid_on = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    reference = models.CharField(max_length=80, unique=True)
    cash_account = models.ForeignKey(CashBookAccount, on_delete=models.PROTECT, related_name="payable_payments")
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="payable_payment")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payable_payments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="payable_payment_positive")]


class PayrollPayment(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_POSTED = "POSTED"
    STATUS_PAID = "PAID"

    schedule = models.ForeignKey(PayrollEntry, on_delete=models.PROTECT, related_name="payments")
    period_start = models.DateField()
    period_end = models.DateField()
    gross_salary = models.DecimalField(max_digits=16, decimal_places=2)
    allowances = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=12, default=STATUS_DRAFT)
    journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="payroll_recognition")
    payment_journal = models.OneToOneField(JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="payroll_payment")
    paid_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="payroll_payments_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "schedule_id"]
        constraints = [
            models.UniqueConstraint(fields=["schedule", "period_start", "period_end"], name="unique_payroll_period"),
            models.CheckConstraint(condition=models.Q(deductions__gte=0), name="payroll_deductions_non_negative"),
        ]


class DepreciationEntry(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="depreciation_entries")
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    journal = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="depreciation_entry")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="depreciation_entries_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "period_start"], name="unique_asset_depreciation_period"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="depreciation_positive"),
        ]


class FinanceBudget(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_APPROVED = "APPROVED"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_APPROVED, "Approved")]

    name = models.CharField(max_length=160)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="budgets_approved"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="budgets_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]


class FinanceBudgetLine(models.Model):
    budget = models.ForeignKey(FinanceBudget, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="budget_lines")
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["budget", "account"], name="unique_budget_account")]


class BankStatement(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_RECONCILED = "RECONCILED"

    cash_account = models.ForeignKey(CashBookAccount, on_delete=models.PROTECT, related_name="statements")
    statement_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=12, default=STATUS_OPEN)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="bank_statements_reconciled"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-statement_date"]
        constraints = [models.UniqueConstraint(fields=["cash_account", "statement_date"], name="unique_statement_date")]


class BankStatementLine(models.Model):
    SIDE_SOURCE = "SOURCE"
    SIDE_DESTINATION = "DESTINATION"

    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    txn_date = models.DateField()
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=80, blank=True)
    matched_movement = models.ForeignKey(CashMovement, null=True, blank=True, on_delete=models.PROTECT, related_name="statement_lines")
    matched_side = models.CharField(max_length=12, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["matched_movement", "matched_side"],
                condition=models.Q(matched_movement__isnull=False),
                name="unique_statement_movement_side",
            ),
        ]


class OperationalPosting(models.Model):
    """Explicit link from an operational record to one ledger entry. Operational balances are not rewritten."""

    SOURCE_SUBSCRIPTION = "SUBSCRIPTION"
    SOURCE_INPUT_DEBT = "INPUT_DEBT"
    SOURCE_DELIVERY = "DELIVERY"
    SOURCE_CHOICES = [
        (SOURCE_SUBSCRIPTION, "Subscription"),
        (SOURCE_INPUT_DEBT, "Input debt"),
        (SOURCE_DELIVERY, "GMB delivery"),
    ]

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_id = models.PositiveIntegerField()
    source_key = models.CharField(max_length=160, unique=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    journal = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="operational_posting")
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="operational_postings"
    )
    created_at = models.DateTimeField(auto_now_add=True)
