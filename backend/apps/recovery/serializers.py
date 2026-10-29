from rest_framework import serializers

from .models import InputDebt, RecoveryRecord
from .services import RecoveryCalculationService


class RecoveryRecordSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)

    class Meta:
        model = RecoveryRecord
        fields = [
            "id",
            "farmer",
            "farmer_name",
            "province",
            "farm_name",
            "crop",
            "contracted_hectares",
            "arda_grand_total",
            "grain_recovery_tonnes",
            "grain_delivered_tonnes",
            "outstanding_tonnes",
            "debt_amount",
            "currency",
            "status",
            "notes",
            "due_date",
            "created_at",
            "updated_at",
        ]


class InputDebtSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    province_name = serializers.CharField(source="province.name", read_only=True)
    district_name = serializers.CharField(source="district.name", read_only=True)

    class Meta:
        model = InputDebt
        fields = [
            "id", "input_allocation", "farmer", "farmer_name", "farm", "province", "province_name", "district", "district_name",
            "programme", "programme_name", "crop", "contracted_hectares", "input_value", "selling_price_per_tonne",
            "required_recovery_tonnes", "recovered_tonnes", "outstanding_tonnes", "amount_recovered",
            "outstanding_monetary_balance", "recovery_percentage", "status", "created_at", "updated_at",
        ]
        read_only_fields = [
            "input_allocation",
            "farmer",
            "farm",
            "province",
            "district",
            "programme",
            "crop",
            "contracted_hectares",
            "input_value",
            "selling_price_per_tonne",
            "required_recovery_tonnes",
            "outstanding_tonnes",
            "amount_recovered",
            "outstanding_monetary_balance",
            "recovery_percentage",
            "status",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        required = getattr(self.instance, "required_recovery_tonnes", 0)
        recovered = attrs.get("recovered_tonnes", getattr(self.instance, "recovered_tonnes", 0))
        selling_price = getattr(self.instance, "selling_price_per_tonne", 0)
        input_cost = getattr(self.instance, "input_value", 0)
        try:
            attrs.update(RecoveryCalculationService.calculate_summary(required, recovered))
            attrs.update(RecoveryCalculationService.calculate_monetary_summary(input_cost, selling_price, recovered))
        except ValueError as error:
            raise serializers.ValidationError({"recovered_tonnes": [str(error)]}) from error
        return attrs
