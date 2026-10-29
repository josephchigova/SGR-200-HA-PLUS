from rest_framework.routers import DefaultRouter

from .views import (
    BalanceSheetLineViewSet,
    BudgetLineViewSet,
    ClusterPerformanceViewSet,
    DataBankEntryViewSet,
    FinanceCashFlowViewSet,
    MonthlySalaryViewSet,
    ProfitLossLineViewSet,
)

router = DefaultRouter()
router.register(r"data-bank", DataBankEntryViewSet, basename="data-bank")
router.register(r"cluster-performance", ClusterPerformanceViewSet, basename="cluster-performance")
router.register(r"finance-cash-flow", FinanceCashFlowViewSet, basename="finance-cash-flow")
router.register(r"balance-sheet", BalanceSheetLineViewSet, basename="balance-sheet")
router.register(r"profit-loss", ProfitLossLineViewSet, basename="profit-loss")
router.register(r"monthly-salary", MonthlySalaryViewSet, basename="monthly-salary")
router.register(r"budget-lines", BudgetLineViewSet, basename="budget-line")

urlpatterns = router.urls
