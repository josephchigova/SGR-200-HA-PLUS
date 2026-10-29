from rest_framework import permissions, viewsets

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
    permission_classes = [permissions.IsAuthenticated]


class DataBankEntryViewSet(SourceViewSet):
    queryset = DataBankEntry.objects.all()
    serializer_class = DataBankEntrySerializer


class ClusterPerformanceViewSet(SourceViewSet):
    queryset = ClusterPerformance.objects.all()
    serializer_class = ClusterPerformanceSerializer


class FinanceCashFlowViewSet(SourceViewSet):
    queryset = FinanceCashFlow.objects.all()
    serializer_class = FinanceCashFlowSerializer


class BalanceSheetLineViewSet(SourceViewSet):
    queryset = BalanceSheetLine.objects.all()
    serializer_class = BalanceSheetLineSerializer


class ProfitLossLineViewSet(SourceViewSet):
    queryset = ProfitLossLine.objects.all()
    serializer_class = ProfitLossLineSerializer


class MonthlySalaryViewSet(SourceViewSet):
    queryset = MonthlySalary.objects.all()
    serializer_class = MonthlySalarySerializer


class BudgetLineViewSet(SourceViewSet):
    queryset = BudgetLine.objects.all()
    serializer_class = BudgetLineSerializer
