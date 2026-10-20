from decimal import Decimal

from rest_framework import serializers

from .calendar import crop_seasons_for_date, season_is_current_year
from .models import Crop, CropInputRequirement, CropSellingPrice, Programme, ProgrammeAllocation, Season


class SeasonSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()
    crop_seasons = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            "status",
            "notes",
            "created_at",
            "updated_at",
            "is_current",
            "crop_seasons",
        ]
        read_only_fields = ["created_at", "updated_at", "is_current", "crop_seasons"]

    def get_is_current(self, obj):
        return season_is_current_year(obj)

    def get_crop_seasons(self, obj):
        return crop_seasons_for_date(obj.start_date)


class ProgrammeSerializer(serializers.ModelSerializer):
    remaining_capacity = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Programme
        fields = [
            "id",
            "name",
            "code",
            "description",
            "season",
            "crop",
            "institution",
            "announced_hectares",
            "total_allocated_hectares",
            "remaining_capacity",
            "application_open_date",
            "application_deadline",
            "status",
            "notes",
            "start_date",
            "end_date",
            "is_active",
        ]
        read_only_fields = ["total_allocated_hectares", "remaining_capacity"]

    def validate_announced_hectares(self, value):
        if value < 0:
            raise serializers.ValidationError("Programme capacity cannot be negative.")
        if self.instance and value < self.instance.total_allocated_hectares:
            raise serializers.ValidationError("Capacity cannot be lower than hectares already allocated.")
        return value


class ProgrammeAllocationSerializer(serializers.ModelSerializer):
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)

    class Meta:
        model = ProgrammeAllocation
        fields = [
            "id",
            "programme",
            "programme_name",
            "farmer",
            "farmer_name",
            "input_type",
            "quantity",
            "unit",
            "allocated_by",
            "allocation_date",
            "notes",
        ]


class CropSerializer(serializers.ModelSerializer):
    input_cost_per_hectare = serializers.DecimalField(
        source="total_input_cost_per_hectare",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    inputs_count = serializers.IntegerField(source="active_input_count", read_only=True)

    class Meta:
        model = Crop
        fields = ["id", "name", "category", "active", "input_cost_per_hectare", "inputs_count", "created_at", "updated_at"]

    def validate_name(self, value):
        normalized = " ".join(value.split())
        queryset = Crop.objects.filter(name__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A crop with this name already exists.")
        return normalized


class CropInputRequirementSerializer(serializers.ModelSerializer):
    crop_name = serializers.CharField(source="crop.name", read_only=True)

    class Meta:
        model = CropInputRequirement
        fields = [
            "id",
            "crop",
            "crop_name",
            "group_name",
            "item_name",
            "rate_per_hectare",
            "unit",
            "cost_per_unit",
            "cost_per_hectare",
            "cost_type",
            "include_in_input_cost",
            "active",
            "notes",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        instance = self.instance
        rate = Decimal(str(attrs.get("rate_per_hectare", getattr(instance, "rate_per_hectare", 0))))
        if rate <= 0:
            raise serializers.ValidationError({"rate_per_hectare": ["Rate per hectare must be greater than zero."]})

        cost_per_unit = attrs.get("cost_per_unit", getattr(instance, "cost_per_unit", None))
        cost_per_hectare = attrs.get("cost_per_hectare", getattr(instance, "cost_per_hectare", None))
        if cost_per_unit is None and cost_per_hectare is None:
            raise serializers.ValidationError({"cost_per_unit": ["Provide cost per unit so cost per hectare can be calculated."]})

        if cost_per_unit is not None:
            cpu = Decimal(str(cost_per_unit))
            if cpu < 0:
                raise serializers.ValidationError({"cost_per_unit": ["Cost per unit cannot be negative."]})
            attrs["cost_per_hectare"] = (rate * cpu).quantize(Decimal("0.0001"))
        else:
            cph = Decimal(str(cost_per_hectare))
            if cph < 0:
                raise serializers.ValidationError({"cost_per_hectare": ["Cost per hectare cannot be negative."]})
            attrs["cost_per_unit"] = (cph / rate).quantize(Decimal("0.0001"))

        cost_type = attrs.get("cost_type", getattr(instance, "cost_type", CropInputRequirement.COST_TYPE_INPUT))
        include_in_input_cost = attrs.get("include_in_input_cost", getattr(instance, "include_in_input_cost", True))
        if cost_type != CropInputRequirement.COST_TYPE_INPUT and include_in_input_cost:
            attrs["include_in_input_cost"] = False

        group_name = str(attrs.get("group_name", getattr(instance, "group_name", ""))).lower()
        item_name = str(attrs.get("item_name", getattr(instance, "item_name", ""))).lower()
        blocked = {"transport", "labour", "combine"}
        if any(term in group_name or term in item_name for term in blocked):
            attrs["include_in_input_cost"] = False

        return attrs


class CropSellingPriceSerializer(serializers.ModelSerializer):
    crop_name = serializers.CharField(source="crop.name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)

    class Meta:
        model = CropSellingPrice
        fields = [
            "id",
            "crop",
            "crop_name",
            "season",
            "season_name",
            "price_per_tonne",
            "currency",
            "active",
            "effective_from",
            "notes",
            "created_at",
            "updated_at",
        ]
