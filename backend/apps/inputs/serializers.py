from rest_framework import serializers

from .models import Input, InputAllocation, InputAllocationLine, InputIssue


class InputAllocationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InputAllocationLine
        fields = [
            "id",
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


class InputAllocationSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    crop_name = serializers.CharField(source="crop_reference.name", read_only=True)
    calculation_lines = InputAllocationLineSerializer(many=True, read_only=True)

    class Meta:
        model = InputAllocation
        fields = [
            "id", "farmer", "farmer_name", "farm", "programme", "programme_name", "crop_reference", "crop_name",
            "crop", "hectares", "calculated_input_cost_per_hectare", "total_input_cost",
            "allocation_date", "allocation_reference", "status", "collection_date", "created_at", "updated_at",
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
        ]

    def validate(self, attrs):
        crop_reference = attrs.get("crop_reference", getattr(self.instance, "crop_reference", None))
        if crop_reference is None:
            raise serializers.ValidationError({"crop_reference": ["Select a crop."]})
        return attrs

    def create(self, validated_data):
        return self._save_with_service(validated_data)

    def update(self, instance, validated_data):
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
