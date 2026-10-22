from decimal import Decimal

from rest_framework import serializers

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch


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
