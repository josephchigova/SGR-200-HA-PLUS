"""Delete operational records while leaving configuration and user accounts in place.

Deletion order follows the foreign keys that use PROTECT: every record is deleted before
the record it points to. QuerySet.delete() is used so Django issues DELETE statements and
still refuses anything the order missed. Sequences are left unchanged. The whole reset runs
in one transaction, so a failure deletes nothing.
"""

from django.db import transaction

from apps.accounts.models import Notification, User
from apps.arda_requests.models import (
    ARDAFarmerRequest,
    ARDARequest,
    ARDARequestBatch,
    ARDARequestNumberSequence,
    BatchStockMovement,
    RequestBatchInput,
    RequestBatchLine,
)
from apps.clusters.models import Cluster
from apps.farmers.models import (
    Farm,
    Farmer,
    FarmerChangeRequest,
    FarmerDocument,
    FarmerReviewEvent,
    RegistrationCropAllocation,
)
from apps.finance.models import (
    AccountingPeriod,
    Asset,
    AssetAuditEvent,
    AssetCategory,
    BankStatement,
    BankStatementLine,
    CashBookAccount,
    CashMovement,
    DepreciationEntry,
    Expense,
    ExpenseClaim,
    FinanceAuditEvent,
    FinanceBudget,
    FinanceBudgetLine,
    JournalEntry,
    JournalLine,
    LedgerAccount,
    OperationalPosting,
    PayablePayment,
    PayrollEntry,
    PayrollPayment,
    Receipt,
    ReceivablePayment,
    RecognizedReceipt,
    TradePayable,
    TradeReceivable,
)
from apps.source_data.models import (
    BalanceSheetLine,
    BudgetLine,
    ClusterPerformance,
    DataBankEntry,
    FinanceCashFlow,
    MonthlySalary,
    ProfitLossLine,
)
from apps.geography.models import District, Province, Ward
from apps.inputs.models import (
    Input,
    InputAllocation,
    InputAllocationLine,
    InputIssue,
    InputSupplyAllocation,
    InputSupplyEvent,
    InputSupplyFarmer,
    InputSupplyLimit,
    InputSupplyLine,
    InputSupplyRequest,
)
from apps.production.models import FarmerProduction, GMBDelivery, ProductionPlan, SeasonalPlantingPlan
from apps.programmes.models import (
    Crop,
    CropInputRequirement,
    CropSellingPrice,
    Programme,
    ProgrammeAllocation,
    ProgrammeCrop,
    Season,
)
from apps.recovery.models import InputDebt, RecoveryRecord
from apps.reports.models import ReportTemplate
from apps.subscriptions.models import FarmerSubscription, Subscription, SubscriptionPayment


def operational_models():
    """Models removed by the reset, children before parents."""
    return (
        ("Bank statement lines", BankStatementLine),
        ("Bank statements", BankStatement),
        ("Finance budget lines", FinanceBudgetLine),
        ("Finance budgets", FinanceBudget),
        ("Payable payments", PayablePayment),
        ("Receivable payments", ReceivablePayment),
        ("Payroll payments", PayrollPayment),
        ("Depreciation entries", DepreciationEntry),
        ("Operational ledger postings", OperationalPosting),
        ("Expense claims", ExpenseClaim),
        ("Recognized receipts", RecognizedReceipt),
        ("Cash movements", CashMovement),
        ("Trade payables", TradePayable),
        ("Trade receivables", TradeReceivable),
        ("Finance audit events", FinanceAuditEvent),
        ("Asset audit events", AssetAuditEvent),
        ("Journal lines", JournalLine),
        ("Journal entries", JournalEntry),
        ("Imported receipt rows", Receipt),
        ("Imported expense rows", Expense),
        # Batch stock history points at allocations, allocation lines and batch inputs (PROTECT).
        ("Request batch stock movements", BatchStockMovement),
        # A confirmed submission points at the allocation it created (PROTECT).
        ("Input supply allocation links", InputSupplyAllocation),
        ("Input allocation lines", InputAllocationLine),
        ("Input debts", InputDebt),
        ("Input issues", InputIssue),
        ("Input allocations", InputAllocation),
        ("Recovery records", RecoveryRecord),
        ("GMB deliveries", GMBDelivery),
        ("Farmer production records", FarmerProduction),
        ("Seasonal planting plans", SeasonalPlantingPlan),
        ("Production plans", ProductionPlan),
        ("Programme allocations", ProgrammeAllocation),
        ("ARDA farmer requests", ARDAFarmerRequest),
        ("ARDA requests", ARDARequest),
        # Batch inputs point at their request batch (PROTECT).
        ("Request batch inputs", RequestBatchInput),
        # Request product lines point at catalogue lines (PROTECT); allocation lines point at them.
        ("Request product lines", RequestBatchLine),
        ("ARDA request batches", ARDARequestBatch),
        ("Subscription payments", SubscriptionPayment),
        ("Farmer subscriptions", FarmerSubscription),
        ("Farmer documents", FarmerDocument),
        ("Subscription reminders", Notification),
        # Supply lines and farmer rows protect catalogue rows, farmers and farms.
        ("Input supply lines", InputSupplyLine),
        ("Input supply limits", InputSupplyLimit),
        ("Input supply events", InputSupplyEvent),
        ("Input supply farmers", InputSupplyFarmer),
        ("Input supply requests", InputSupplyRequest),
        ("Registration crop allocations", RegistrationCropAllocation),
        ("Farmer change requests", FarmerChangeRequest),
        ("Farmer registration history", FarmerReviewEvent),
        ("Farms", Farm),
        ("Farmers", Farmer),
    )


def preserved_models():
    return (
        ("User accounts", User),
        ("Provinces", Province),
        ("Districts", District),
        ("Wards", Ward),
        ("Clusters", Cluster),
        ("Agricultural years", Season),
        ("Crops", Crop),
        ("Crop input requirements", CropInputRequirement),
        ("Crop selling prices", CropSellingPrice),
        ("Programmes", Programme),
        ("Programme crops", ProgrammeCrop),
        ("Input catalogue", Input),
        ("Subscription products", Subscription),
        ("Asset categories", AssetCategory),
        ("Assets", Asset),
        ("Ledger accounts", LedgerAccount),
        ("Cash book accounts", CashBookAccount),
        ("Accounting periods", AccountingPeriod),
        ("Payroll schedules", PayrollEntry),
        ("Report templates", ReportTemplate),
        ("ARDA request number sequence", ARDARequestNumberSequence),
        ("Imported data bank rows", DataBankEntry),
        ("Imported cluster performance rows", ClusterPerformance),
        ("Imported cash flow rows", FinanceCashFlow),
        ("Imported balance sheet rows", BalanceSheetLine),
        ("Imported profit and loss rows", ProfitLossLine),
        ("Imported salary rows", MonthlySalary),
        ("Imported budget rows", BudgetLine),
    )


def collect_counts(entries):
    return [(label, model.objects.count()) for label, model in entries]


@transaction.atomic
def reset_operational_data():
    """Delete operational rows in one transaction: if any delete fails, nothing is deleted."""
    JournalEntry.objects.update(reversal_of=None)
    deleted = []
    for label, model in operational_models():
        count = model.objects.count()
        if count:
            model.objects.all().delete()
        deleted.append((label, count))
    programmes = Programme.objects.exclude(total_allocated_hectares=0).count()
    Programme.objects.update(total_allocated_hectares=0)
    return deleted, programmes
