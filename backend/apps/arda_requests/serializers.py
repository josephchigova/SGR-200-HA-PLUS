from decimal import Decimal

from rest_framework import serializers

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch, BatchStockMovement, RequestBatchInput


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


class ARDARequestBatchSerializer(serializers.ModelSerializer):
    programme_name = serializers.CharField(source="programme.name", read_only=True)
    season_name = serializers.SerializerMethodField()
    capacity_hectares = serializers.DecimalField(source="programme.announced_hectares", max_digits=14, decimal_places=2, read_only=True)
    request_number = serializers.CharField(read_only=True)
    requested_hectares = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    allocated_hectares = serializers.SerializerMethodField()
    available_hectares = serializers.SerializerMethodField()
    total_farmers = serializers.SerializerMethodField()

    class Meta:
        model = ARDARequestBatch
        fields = [
            "id", "request_number", "programme", "programme_name", "capacity_hectares", "season", "season_name", "crop", "requested_hectares",
            "allocated_hectares", "available_hectares", "date_created", "date_submitted", "total_farmers", "total_requested_hectares", "status",
            "created_by", "approved_by", "submission_reference", "notes",
        ]
        read_only_fields = ["request_number", "created_by", "approved_by", "date_created", "total_farmers", "total_requested_hectares", "status", "season_name"]

    def get_season_name(self, obj):
        return obj.season.name if obj.season_id else ""

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
        if programme and requested_hectares is not None and requested_hectares > programme.announced_hectares:
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
        except ValueError as error:
            message = str(error)
            key = "requested_hectares" if "hectare" in message.lower() else "non_field_errors"
            raise serializers.ValidationError({key: [message]}) from error

    def update(self, instance, validated_data):
        from .services import ARDARequestBatchService

        try:
            return ARDARequestBatchService.update_batch(instance=instance, validated_data=validated_data)
        except ValueError as error:
            message = str(error)
            key = "requested_hectares" if "hectare" in message.lower() else "non_field_errors"
            raise serializers.ValidationError({key: [message]}) from error


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


class RequestBatchInputSerializer(serializers.ModelSerializer):
    """An input product held by a request batch, with its requested, allocated and available quantities."""

    batch_number = serializers.CharField(source="batch.request_number", read_only=True)
    batch_status = serializers.CharField(source="batch.status", read_only=True)
    programme = serializers.IntegerField(source="batch.programme_id", read_only=True)
    programme_name = serializers.CharField(source="batch.programme.name", read_only=True)
    season_name = serializers.SerializerMethodField()
    product_name = serializers.CharField(source="input_product.name", read_only=True)
    available_quantity = serializers.DecimalField(max_digits=16, decimal_places=4, read_only=True)
    reason = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = RequestBatchInput
        fields = [
            "id", "batch", "batch_number", "batch_status", "programme", "programme_name", "season_name",
            "input_product", "product_name", "input_category", "unit", "requested_quantity", "allocated_quantity",
            "available_quantity", "notes", "reason", "created_at", "updated_at",
        ]
        read_only_fields = ["allocated_quantity", "created_at", "updated_at"]

    def get_season_name(self, obj):
        return obj.batch.season.name if obj.batch.season_id else ""

    def validate(self, attrs):
        product = attrs.get("input_product", getattr(self.instance, "input_product", None))
        category = attrs.get("input_category", getattr(self.instance, "input_category", ""))
        if self.instance is not None:
            for name in ("batch", "input_product", "input_category"):
                if name in attrs and attrs[name] != getattr(self.instance, name):
                    raise serializers.ValidationError({name: ["Add a new line instead of changing the batch, product or category of this one."]})
        if product is not None and product.category in {"SEED", "FERTILIZER", "CHEMICALS"} and category and product.category != category:
            raise serializers.ValidationError({"input_category": [f"{product.name} is a {product.get_category_display().lower()} product."]})
        return attrs

    def create(self, validated_data):
        from .stock import StockError, open_line

        try:
            return open_line(
                batch=validated_data["batch"], input_product=validated_data["input_product"],
                input_category=validated_data["input_category"], requested_quantity=validated_data.get("requested_quantity"),
                unit=validated_data.get("unit", ""), notes=validated_data.get("notes", ""), user=self.context["request"].user,
            )
        except StockError as error:
            raise serializers.ValidationError({"requested_quantity": [str(error)]}) from error

    def update(self, instance, validated_data):
        from .stock import StockError, change_requested

        reason = validated_data.pop("reason", "")
        if "requested_quantity" in validated_data:
            try:
                instance = change_requested(
                    batch_input_id=instance.pk, requested_quantity=validated_data.pop("requested_quantity"),
                    reason=reason, user=self.context["request"].user,
                )
            except StockError as error:
                raise serializers.ValidationError({"requested_quantity": [str(error)]}) from error
        for name in ("unit", "notes"):
            if name in validated_data:
                setattr(instance, name, validated_data[name])
        instance.save(update_fields=["unit", "notes", "updated_at"])
        return instance


class BatchStockMovementSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    farmer_name = serializers.CharField(source="allocation.farmer.full_name", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BatchStockMovement
        fields = ["id", "kind", "kind_label", "quantity", "available_after", "allocation", "farmer_name", "reason", "created_by_name", "created_at"]

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""
