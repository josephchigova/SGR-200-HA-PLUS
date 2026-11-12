from rest_framework import viewsets

from apps.accounts.permissions import FinanceAccessPermission, ManagementReadPermission

from .models import (
    BalanceSheetLine,
    BudgetLine,
    ClusterPerformance,
    DataBankEntry,
    FinanceCashFlow,
    MonthlySalary,
    ProfitLossLine,
)
from .serializers import (
    BalanceSheetLineSerializer,
    BudgetLineSerializer,
    ClusterPerformanceSerializer,
    DataBankEntrySerializer,
    FinanceCashFlowSerializer,
    MonthlySalarySerializer,
    ProfitLossLineSerializer,
)


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    # Imported workbook tables hold organisation-wide figures.
    permission_classes = [ManagementReadPermission]


class FinanceSourceViewSet(SourceViewSet):
    # Cash flow, statements, salaries and budgets follow the finance rules.
    permission_classes = [FinanceAccessPermission]


class DataBankEntryViewSet(SourceViewSet):
    queryset = DataBankEntry.objects.all()
    serializer_class = DataBankEntrySerializer


class ClusterPerformanceViewSet(SourceViewSet):
    queryset = ClusterPerformance.objects.all()
    serializer_class = ClusterPerformanceSerializer


class FinanceCashFlowViewSet(FinanceSourceViewSet):
    queryset = FinanceCashFlow.objects.all()
    serializer_class = FinanceCashFlowSerializer


class BalanceSheetLineViewSet(FinanceSourceViewSet):
    queryset = BalanceSheetLine.objects.all()
    serializer_class = BalanceSheetLineSerializer


class ProfitLossLineViewSet(FinanceSourceViewSet):
    queryset = ProfitLossLine.objects.all()
    serializer_class = ProfitLossLineSerializer


class MonthlySalaryViewSet(FinanceSourceViewSet):
    queryset = MonthlySalary.objects.all()
    serializer_class = MonthlySalarySerializer


class BudgetLineViewSet(FinanceSourceViewSet):
    queryset = BudgetLine.objects.all()
    serializer_class = BudgetLineSerializer
