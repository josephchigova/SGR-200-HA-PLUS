from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import (
    ExpenseScheduleDetailView,
    ExpenseScheduleView,
    AccountingPeriodViewSet,
    AssetDepreciationView,
    BankStatementViewSet,
    CashBookAccountViewSet,
    CashMovementViewSet,
    ExpenseClaimViewSet,
    FinanceBudgetViewSet,
    FinanceReportView,
    JournalEntryViewSet,
    LedgerAccountViewSet,
    OperationalPostingView,
    PayrollPaymentViewSet,
    RecognizedReceiptViewSet,
    TradePayableViewSet,
    TradeReceivableViewSet,
)
from .views import AssetCategoryViewSet, AssetViewSet, ExpenseViewSet, PayrollEntryViewSet, ReceiptViewSet

router = DefaultRouter()
router.register(r"receipts", ReceiptViewSet, basename="receipt")
router.register(r"expenses", ExpenseViewSet, basename="expense")
router.register(r"asset-categories", AssetCategoryViewSet, basename="asset-category")
router.register(r"assets", AssetViewSet, basename="asset")
router.register(r"payroll", PayrollEntryViewSet, basename="payroll-entry")
router.register(r"ledger-accounts", LedgerAccountViewSet, basename="ledger-account")
router.register(r"accounting-periods", AccountingPeriodViewSet, basename="accounting-period")
router.register(r"journals", JournalEntryViewSet, basename="journal")
router.register(r"cash-accounts", CashBookAccountViewSet, basename="cash-account")
router.register(r"cash-movements", CashMovementViewSet, basename="cash-movement")
router.register(r"recognized-receipts", RecognizedReceiptViewSet, basename="recognized-receipt")
router.register(r"expense-claims", ExpenseClaimViewSet, basename="expense-claim")
router.register(r"receivables", TradeReceivableViewSet, basename="receivable")
router.register(r"payables", TradePayableViewSet, basename="payable")
router.register(r"payroll-payments", PayrollPaymentViewSet, basename="payroll-payment")
router.register(r"finance-budgets", FinanceBudgetViewSet, basename="finance-budget")
router.register(r"bank-statements", BankStatementViewSet, basename="bank-statement")

urlpatterns = [
    path("assets/<int:pk>/depreciate/", AssetDepreciationView.as_view(), name="asset-depreciate"),
    path("operational-postings/", OperationalPostingView.as_view(), name="operational-posting"),
    path("finance-reports/<slug:report>/", FinanceReportView.as_view(), name="finance-report"),
    path("expense-schedule/", ExpenseScheduleView.as_view(), name="expense-schedule"),
    path("expense-schedule/<int:pk>/", ExpenseScheduleDetailView.as_view(), name="expense-schedule-detail"),
    *router.urls,
]
