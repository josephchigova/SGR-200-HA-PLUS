from apps.accounts.privacy import MoneyPrivacyMixin
from rest_framework import serializers

from .models import Input, InputAllocation, InputAllocationLine, InputIssue


class InputAllocationLineSerializer(MoneyPrivacyMixin, serializers.ModelSerializer):
    money_fields = ('cost_per_unit', 'cost_per_hectare', 'calculated_cost')
    programme_name = serializers.CharField(source="programme.name", read_only=True, default="")
    batch_number = serializers.CharField(source="batch_input.batch.request_number", read_only=True, default="")

    class Meta:
        model = InputAllocationLine
        fields = [
            "id",
            "input_category",
            "programme",
            "programme_name",
            "input_product",
            "batch_input",
            "batch_number",
            "group_name",
            "item_name",
            "rate_per_hectare",
            "required_quantity",
            "unit",
            "cost_per_unit",
            "cost_per_hectare",
            "calculated_cost",
            "included_in_total",
        ]


class InputIssueSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)

    class Meta:
        model = InputIssue
        fields = [
            "id",
            "farmer",
            "farmer_name",
            "input_name",
            "batch_number",
            "quantity",
            "unit",
            "issue_status",
            "issue_date",
            "collected_date",
            "issued_by",
            "notes",
        ]


class InputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Input
        fields = "__all__"


class InputAllocationSerializer(MoneyPrivacyMixin, serializers.ModelSerializer):
    money_fields = ('calculated_input_cost_per_hectare', 'total_input_cost')

    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    crop_name = serializers.CharField(source="crop_reference.name", read_only=True)
    calculation_lines = InputAllocationLineSerializer(many=True, read_only=True)
    season_name = serializers.SerializerMethodField()
    membership_number = serializers.CharField(source="farmer.membership_number", read_only=True)
    cancelled_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InputAllocation
        fields = [
            "id", "farmer", "farmer_name", "membership_number", "farm", "programme", "programme_name", "crop_reference", "crop_name",
            "crop", "hectares", "calculated_input_cost_per_hectare", "total_input_cost",
            "allocation_date", "allocation_reference", "status", "collection_date", "created_at", "updated_at",
            "season", "season_name", "sourced_by_category", "cancelled_at", "cancelled_by_name", "cancellation_reason",
            "calculation_lines",
        ]
        read_only_fields = [
            "crop",
            "calculated_input_cost_per_hectare",
            "total_input_cost",
            "allocation_date",
            "created_at",
            "updated_at",
            "status",
            "collection_date",
            "calculation_lines",
            "season",
            "sourced_by_category",
            "cancelled_at",
            "cancellation_reason",
        ]

    def get_season_name(self, obj):
        season = obj.season or getattr(obj.programme, "season", None)
        return season.name if season else ""

    def get_cancelled_by_name(self, obj):
        user = obj.cancelled_by
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""

    def validate(self, attrs):
        crop_reference = attrs.get("crop_reference", getattr(self.instance, "crop_reference", None))
        if crop_reference is None:
            raise serializers.ValidationError({"crop_reference": ["Select a crop."]})
        return attrs

    def create(self, validated_data):
        return self._save_with_service(validated_data)

    def update(self, instance, validated_data):
        if instance.sourced_by_category:
            raise serializers.ValidationError({"detail": ["Allocations sourced per input category cannot be edited. Cancel it and allocate again."]})
        data = {
            field: validated_data.get(field, getattr(instance, field))
            for field in ("farmer", "farm", "programme", "crop_reference", "crop", "hectares")
        }
        return self._save_with_service(data, allocation_id=instance.pk)

    def _save_with_service(self, validated_data, allocation_id=None):
        from .services import InputAllocationService

        try:
            request = self.context.get("request")
            crop_season = None
            if request is not None:
                from apps.programmes.period import parse_crop_season

                crop_season = parse_crop_season(request.query_params.get("crop_season"))
            return InputAllocationService.create_allocation(
                farmer=validated_data.pop("farmer"),
                farm=validated_data.pop("farm", None),
                programme=validated_data.pop("programme"),
                crop_reference=validated_data.pop("crop_reference", None),
                crop=validated_data.pop("crop", ""),
                hectares=validated_data.pop("hectares"),
                allocation_id=allocation_id,
                crop_season=crop_season,
                **validated_data,
            )
        except ValueError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error
