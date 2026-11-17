from decimal import Decimal

from rest_framework import serializers

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch, RequestBatchLine
from .services import RequestWorkflowError


class ARDARequestSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)

    class Meta:
        model = ARDARequest
        fields = [
            "id",
            "farmer",
            "farmer_name",
            "request_type",
            "quantity",
            "unit",
            "reason",
            "status",
            "requested_at",
            "reviewed_at",
            "reviewed_by",
            "notes",
        ]


class RequestBatchLineSerializer(serializers.ModelSerializer):
    """A product or variety in a request. Everything but the hectares is read from the catalogue line."""

    product_name = serializers.SerializerMethodField()
    input_category = serializers.CharField(source="requirement.input_category", read_only=True)
    unit = serializers.CharField(source="requirement.unit", read_only=True)
    rate_per_hectare = serializers.DecimalField(source="requirement.rate_per_hectare", max_digits=14, decimal_places=4, read_only=True)
    unit_price = serializers.DecimalField(source="requirement.cost_per_unit", max_digits=14, decimal_places=4, read_only=True)
    pack_label = serializers.CharField(source="requirement.pack_label", read_only=True)
    pack_size = serializers.DecimalField(source="requirement.pack_size", max_digits=14, decimal_places=4, read_only=True)
    catalogue_active = serializers.BooleanField(source="requirement.active", read_only=True)
    allocated_hectares = serializers.SerializerMethodField()
    remaining_hectares = serializers.SerializerMethodField()
    farmers = serializers.SerializerMethodField()

    class Meta:
        model = RequestBatchLine
        fields = [
            "id", "requirement", "product_name", "input_category", "unit", "rate_per_hectare", "unit_price", "pack_label", "pack_size",
            "catalogue_active", "requested_hectares", "approved_hectares", "allocated_hectares", "remaining_hectares", "farmers",
        ]

    def get_product_name(self, obj):
        requirement = obj.requirement
        return requirement.input_product.name if requirement.input_product_id else requirement.item_name

    def _figures(self, obj):
        from .services import line_figures

        cache = self.context.setdefault("_line_figures", {})
        if obj.pk not in cache:
            cache[obj.pk] = line_figures(obj)
        return cache[obj.pk]

    def get_allocated_hectares(self, obj):
        return str(self._figures(obj)["allocated_hectares"])

    def get_remaining_hectares(self, obj):
        return str(self._figures(obj)["available_hectares"])

    def get_farmers(self, obj):
        return self._figures(obj)["farmers"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request is not None:
            from apps.accounts.privacy import hides_money

            if hides_money(request.user):
                data["unit_price"] = None
        return data


class ARDARequestBatchSerializer(serializers.ModelSerializer):
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    season_name = serializers.SerializerMethodField()
    capacity_hectares = serializers.DecimalField(source="programme.announced_hectares", max_digits=14, decimal_places=2, read_only=True)
    request_number = serializers.CharField(read_only=True)
    # Worked out from the product lines. Only requests without product lines give it directly.
    requested_hectares = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False)
    allocated_hectares = serializers.SerializerMethodField()
    available_hectares = serializers.SerializerMethodField()
    total_farmers = serializers.SerializerMethodField()
    # The Input requests form always asks for it. Blank means the request covers every input.
    input_category = serializers.ChoiceField(
        choices=[("SEED", "Seed"), ("FERTILIZER", "Fertilizer"), ("CHEMICALS", "Chemicals")], required=False, allow_blank=True,
    )
    input_category_label = serializers.SerializerMethodField()
    approved_hectares = serializers.SerializerMethodField()
    remaining_hectares = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    crop_season = serializers.SerializerMethodField()
    programme_active = serializers.BooleanField(source="programme.is_active", read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    lines = serializers.ListField(child=serializers.DictField(), required=False, write_only=True)
    products = serializers.SerializerMethodField()

    class Meta:
        model = ARDARequestBatch
        fields = [
            "id", "request_number", "programme", "programme_name", "programme_active", "capacity_hectares", "season", "season_name",
            "crop", "crop_season", "input_category", "input_category_label",
            "requested_hectares", "approved_hectares", "allocated_hectares", "available_hectares", "remaining_hectares",
            "date_created", "date_submitted", "decided_at", "decision_notes", "total_farmers", "total_requested_hectares", "status", "status_label",
            "created_by", "created_by_name", "approved_by", "approved_by_name", "submission_reference", "notes",
            "lines", "products",
        ]
        read_only_fields = [
            "request_number", "created_by", "approved_by", "date_created", "date_submitted", "decided_at", "decision_notes",
            "total_farmers", "total_requested_hectares", "status", "season_name",
        ]

    def get_products(self, obj):
        rows = obj.lines.select_related("requirement__input_product", "batch")
        return RequestBatchLineSerializer(rows, many=True, context=self.context).data

    def get_approved_hectares(self, obj):
        return self._snapshot(obj)["approved_hectares"]

    def get_remaining_hectares(self, obj):
        return self._snapshot(obj)["available_hectares"]

    def get_crop_season(self, obj):
        from apps.programmes.models import Crop

        crop = Crop.objects.filter(name__iexact=(obj.crop or "").strip()).first()
        return crop.get_category_display() if crop else ""

    def get_approved_by_name(self, obj):
        user = obj.approved_by
        return (user.get_full_name() or user.username) if user else ""

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else ""

    def get_season_name(self, obj):
        return obj.season.name if obj.season_id else ""

    def get_input_category_label(self, obj):
        return obj.get_input_category_display() if obj.input_category else "All inputs"

    def _snapshot(self, obj):
        from .services import ARDARequestBatchService

        cache = self.context.setdefault("_arda_batch_snapshot_cache", {})
        snapshot = cache.get(obj.pk)
        if snapshot is None:
            snapshot = ARDARequestBatchService.batch_snapshot(obj)
            cache[obj.pk] = snapshot
        return snapshot

    def get_allocated_hectares(self, obj):
        return self._snapshot(obj)["allocated_hectares"]

    def get_available_hectares(self, obj):
        return self._snapshot(obj)["available_hectares"]

    def get_total_farmers(self, obj):
        return self._snapshot(obj)["unique_farmers"]

    def validate(self, attrs):
        programme = attrs.get("programme", getattr(self.instance, "programme", None))
        requested_hectares = attrs.get("requested_hectares", getattr(self.instance, "requested_hectares", None))
        capacity = getattr(programme, "announced_hectares", None)
        if programme and capacity and capacity > 0 and requested_hectares is not None and requested_hectares > capacity:
            raise serializers.ValidationError({"requested_hectares": ["Cannot exceed programme capacity."]})
        request = self.context.get("request")
        from apps.programmes.period import parse_crop_season

        crop_season = parse_crop_season(request.query_params.get("crop_season")) if request is not None else None
        if "crop" in attrs or crop_season:
            from apps.programmes.models import Crop

            crop_name = attrs.get("crop", getattr(self.instance, "crop", ""))
            crop = Crop.objects.filter(name__iexact=str(crop_name).strip(), active=True).first() if crop_name else None
            if crop_season and (crop is None or crop.category != crop_season):
                raise serializers.ValidationError({"crop": ["Select a crop that belongs to the selected season."]})
            if crop is not None:
                attrs["crop"] = crop.name
        return attrs

    def create(self, validated_data):
        from .services import ARDARequestBatchService

        try:
            return ARDARequestBatchService.create_batch(
                validated_data=validated_data,
                created_by=self.context["request"].user,
            )
        except RequestWorkflowError as error:
            raise serializers.ValidationError({"lines": [str(error)]}) from error
        except ValueError as error:
            message = str(error)
            raise serializers.ValidationError({self._error_field(message): [message]}) from error

    @staticmethod
    def _error_field(message):
        lowered = message.lower()
        if "hectare" in lowered:
            return "requested_hectares"
        if "does not support" in lowered or "select the crop" in lowered:
            return "crop"
        if "does not supply" in lowered:
            return "input_category"
        return "non_field_errors"

    def update(self, instance, validated_data):
        from .services import ARDARequestBatchService

        try:
            return ARDARequestBatchService.update_batch(instance=instance, validated_data=validated_data)
        except RequestWorkflowError as error:
            raise serializers.ValidationError({"lines": [str(error)]}) from error
        except ValueError as error:
            message = str(error)
            raise serializers.ValidationError({self._error_field(message): [message]}) from error


class ARDAFarmerRequestSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    farm_name = serializers.CharField(source="farm.farm_name", read_only=True)

    class Meta:
        model = ARDAFarmerRequest
        fields = [
            "id", "request_batch", "farmer", "farmer_name", "farm", "farm_name", "requested_hectares",
            "approved_hectares", "status", "remarks", "created_at",
        ]
        read_only_fields = ["approved_hectares", "status", "created_at"]

    def create(self, validated_data):
        from .services import ARDARequestService

        batch = validated_data.pop("request_batch")
        farmer = validated_data.pop("farmer")
        requested_hectares = validated_data.pop("requested_hectares")
        farm = validated_data.pop("farm", None)
        try:
            return ARDARequestService.add_farmer(
                batch=batch,
                farmer=farmer,
                requested_hectares=requested_hectares,
                farm=farm,
            )
        except ValueError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error
