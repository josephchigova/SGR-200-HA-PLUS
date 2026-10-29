from rest_framework import serializers

from .models import (
    BalanceSheetLine,
    BudgetLine,
    ClusterPerformance,
    DataBankEntry,
    FinanceCashFlow,
    MonthlySalary,
    ProfitLossLine,
)


class SourceDataSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"


class DataBankEntrySerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = DataBankEntry


class ClusterPerformanceSerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = ClusterPerformance


class FinanceCashFlowSerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = FinanceCashFlow


class BalanceSheetLineSerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = BalanceSheetLine


class ProfitLossLineSerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = ProfitLossLine


class MonthlySalarySerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = MonthlySalary


class BudgetLineSerializer(SourceDataSerializer):
    class Meta(SourceDataSerializer.Meta):
        model = BudgetLine
