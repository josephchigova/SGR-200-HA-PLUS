from decimal import Decimal

from rest_framework import serializers

from .calendar import crop_seasons_for_date, season_is_current_year, season_is_selectable
from .models import INPUT_CATEGORIES, INPUT_CATEGORY_CHOICES, Crop, CropInputRequirement, CropSellingPrice, Programme, ProgrammeAllocation, Season


class SeasonSerializer(serializers.ModelSerializer):
    is_current = serializers.SerializerMethodField()
    selectable = serializers.SerializerMethodField()
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
            "subscription_due_date",
            "created_at",
            "updated_at",
            "is_current",
            "selectable",
            "crop_seasons",
        ]
        read_only_fields = ["created_at", "updated_at", "is_current", "selectable", "crop_seasons"]

    def get_is_current(self, obj):
        return season_is_current_year(obj)

    def get_selectable(self, obj):
        return season_is_selectable(obj)

    def get_crop_seasons(self, obj):
        return crop_seasons_for_date(obj.start_date)


class ProgrammeSerializer(serializers.ModelSerializer):
    """A programme: its name, agricultural year, the crops and input types it supports, and whether it is active.

    Code, institution and hectare capacity are kept for programmes set up earlier but are not
    asked for any more. A code is generated when none is given.
    """

    remaining_capacity = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    season_name = serializers.SerializerMethodField()
    code = serializers.CharField(max_length=80, required=False, allow_blank=True)
    crop = serializers.CharField(max_length=80, required=False, allow_blank=True)
    crops = serializers.PrimaryKeyRelatedField(many=True, queryset=Crop.objects.all(), required=False)
    crop_names = serializers.SerializerMethodField()
    capacity_status = serializers.ChoiceField(choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")], required=False)
    input_category_labels = serializers.SerializerMethodField()
    figures = serializers.SerializerMethodField()

    class Meta:
        model = Programme
        fields = [
            "id",
            "name",
            "code",
            "description",
            "season",
            "season_name",
            "crop",
            "crops",
            "crop_names",
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
            "capacity_status",
            "input_categories",
            "input_category_labels",
            "figures",
        ]
        read_only_fields = ["total_allocated_hectares", "remaining_capacity", "season_name"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["crops"] = list(instance.supported_crops().values_list("pk", flat=True))
        data["capacity_status"] = instance.capacity_status
        return data

    def get_crop_names(self, obj):
        return list(obj.supported_crops().values_list("name", flat=True))

    def get_input_category_labels(self, obj):
        labels = dict(INPUT_CATEGORY_CHOICES)
        return [labels[code] for code in obj.input_categories or [] if code in labels]

    def get_figures(self, obj):
        from .figures import programme_figures

        cache = self.context.setdefault("_programme_figures", {})
        if obj.pk not in cache:
            cache[obj.pk] = programme_figures(obj)
        return cache[obj.pk]["totals"]

    def validate_input_categories(self, value):
        chosen = [str(item).upper() for item in (value or [])]
        unknown = sorted(set(chosen) - set(INPUT_CATEGORIES))
        if unknown:
            raise serializers.ValidationError(f"Use Seed, Fertilizer or Chemicals, not {', '.join(unknown)}.")
        return [code for code in INPUT_CATEGORIES if code in chosen]

    def get_season_name(self, obj):
        return obj.season.name if obj.season_id else ""

    def validate(self, attrs):
        capacity_status = attrs.pop("capacity_status", None)
        if capacity_status:
            attrs["is_active"] = capacity_status == "ACTIVE"
        name = " ".join((attrs.get("name", getattr(self.instance, "name", "")) or "").split())
        season = attrs.get("season", getattr(self.instance, "season", None))
        if "name" in attrs:
            attrs["name"] = name
        if name and season is not None:
            duplicate = Programme.objects.filter(name__iexact=name, season=season)
            if self.instance is not None:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({"name": [f"{name} already exists for {season.name}. Edit that programme instead."]})
        if self.instance is None:
            crops = attrs.get("crops") or []
            if not crops and not attrs.get("crop"):
                raise serializers.ValidationError({"crops": ["Select at least one crop this programme supports."]})
            if not attrs.get("input_categories"):
                raise serializers.ValidationError({"input_categories": ["Select at least one input type: Seed, Fertilizer or Chemicals."]})
        elif "crops" in attrs and not attrs["crops"]:
            raise serializers.ValidationError({"crops": ["A programme must support at least one crop."]})
        elif "input_categories" in attrs and not attrs["input_categories"]:
            raise serializers.ValidationError({"input_categories": ["A programme must supply at least one input type."]})
        inactive = [crop.name for crop in attrs.get("crops") or [] if not crop.active]
        if inactive:
            raise serializers.ValidationError({"crops": [f"{', '.join(inactive)} is not an active crop."]})
        return attrs

    @staticmethod
    def _generate_code(name, season):
        import re

        base = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:50] or "PROGRAMME"
        year = re.sub(r"[^0-9]+", "", season.name)[:8] if season else ""
        code = f"{base}-{year}" if year else base
        candidate, number = code, 2
        while Programme.objects.filter(code__iexact=candidate).exists():
            candidate = f"{code}-{number}"
            number += 1
        return candidate

    def _save_crops(self, programme, crops):
        from .models import ProgrammeCrop

        if crops is None:
            if (programme.crop or "").strip() and not programme.programme_crops.exists():
                crop = Crop.objects.filter(name__iexact=programme.crop.strip()).first()
                if crop is not None:
                    ProgrammeCrop.objects.get_or_create(programme=programme, crop=crop)
            return
        wanted = {crop.pk for crop in crops}
        for crop in crops:
            link, created = ProgrammeCrop.objects.get_or_create(programme=programme, crop=crop)
            if not created and not link.active:
                link.active = True
                link.save(update_fields=["active"])
        # Removed crops are switched off, not deleted, so requests and allocations made for them stay readable.
        programme.programme_crops.exclude(crop_id__in=wanted).update(active=False)
        first = programme.supported_crops().order_by("name").first()
        if first is not None and programme.crop != first.name:
            programme.crop = first.name
            programme.save(update_fields=["crop", "updated_at"])

    def create(self, validated_data):
        from django.db import transaction

        crops = validated_data.pop("crops", None)
        if not (validated_data.get("code") or "").strip():
            validated_data["code"] = self._generate_code(validated_data["name"], validated_data.get("season"))
        if crops and not validated_data.get("crop"):
            validated_data["crop"] = min(crop.name for crop in crops)
        with transaction.atomic():
            programme = super().create(validated_data)
            self._save_crops(programme, crops)
        return programme

    def update(self, instance, validated_data):
        from django.db import transaction

        crops = validated_data.pop("crops", None)
        if "code" in validated_data and not (validated_data["code"] or "").strip():
            validated_data.pop("code")
        with transaction.atomic():
            programme = super().update(instance, validated_data)
            if crops is not None:
                self._save_crops(programme, crops)
        return programme

    def validate_announced_hectares(self, value):
        if value < 0:
            raise serializers.ValidationError("Programme capacity cannot be negative.")
        if self.instance and value < self.instance.total_allocated_hectares:
            raise serializers.ValidationError("Capacity cannot be lower than hectares already allocated.")
        return value

    def validate_code(self, value):
        normalized = (value or "").strip()
        if not normalized:
            return normalized
        queryset = Programme.objects.filter(code__iexact=normalized)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A programme with this code already exists.")
        return normalized

    def validate_season(self, value):
        if value is None:
            raise serializers.ValidationError("Select an agricultural year.")
        return value

    def validate_crop(self, value):
        normalized = " ".join((value or "").split())
        if not normalized:
            return ""
        crop = Crop.objects.filter(name__iexact=normalized, active=True).first()
        if crop is None:
            raise serializers.ValidationError("Select an active crop from the catalogue.")
        request = self.context.get("request")
        from .period import parse_crop_season

        crop_season = parse_crop_season(request.query_params.get("crop_season")) if request is not None else None
        if crop_season and crop.category != crop_season:
            raise serializers.ValidationError("That crop does not belong to the selected season.")
        return crop.name


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
    programme_name = serializers.CharField(source="programme.name", read_only=True, default="")
    input_product_name = serializers.CharField(source="input_product.name", read_only=True, default="")

    class Meta:
        model = CropInputRequirement
        fields = [
            "id",
            "crop",
            "crop_name",
            "programme",
            "programme_name",
            "input_category",
            "input_product",
            "input_product_name",
            "group_name",
            "item_name",
            "rate_per_hectare",
            "unit",
            "cost_per_unit",
            "pack_label",
            "pack_size",
            "pack_price",
            "cost_per_hectare",
            "cost_type",
            "active",
            "notes",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"group_name": {"required": False}, "item_name": {"required": False}}
        # Duplicates are checked in validate(), separately for the general and programme catalogues.
        validators = []

    def to_internal_value(self, data):
        incoming = data.copy() if hasattr(data, "copy") else dict(data)
        cost_type = incoming.get("cost_type")
        if cost_type in CropInputRequirement.LEGACY_COST_TYPES:
            incoming["cost_type"] = CropInputRequirement.LEGACY_COST_TYPES[cost_type]
        if hasattr(incoming, "pop"):
            incoming.pop("include_in_input_cost", None)
        return super().to_internal_value(incoming)

    def validate(self, attrs):
        instance = self.instance
        rate = Decimal(str(attrs.get("rate_per_hectare", getattr(instance, "rate_per_hectare", 0))))
        if rate <= 0:
            raise serializers.ValidationError({"rate_per_hectare": ["Rate per hectare must be greater than zero."]})
        if instance is None and attrs.get("programme") is None:
            raise serializers.ValidationError({"programme": ["Choose the programme. Every catalogue line belongs to one programme."]})

        # Sold in packs (for example 50 kg bags): the unit price follows the pack price and size.
        pack_size = attrs.get("pack_size", getattr(instance, "pack_size", None))
        pack_price = attrs.get("pack_price", getattr(instance, "pack_price", None))
        if (pack_size is None) != (pack_price is None):
            raise serializers.ValidationError({"pack_size": ["Enter both the pack size and the pack price, or neither."]})
        if pack_size is not None:
            if Decimal(str(pack_size)) <= 0:
                raise serializers.ValidationError({"pack_size": ["Pack size must be greater than zero."]})
            if Decimal(str(pack_price)) <= 0:
                raise serializers.ValidationError({"pack_price": ["Pack price must be greater than zero."]})
            attrs["cost_per_unit"] = (Decimal(str(pack_price)) / Decimal(str(pack_size))).quantize(Decimal("0.0001"))
            attrs.pop("cost_per_hectare", None)
        elif "pack_size" in attrs:
            attrs["pack_label"] = ""

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

        cost_type = attrs.get("cost_type", getattr(instance, "cost_type", CropInputRequirement.COST_TYPE_CROP_INPUT))
        mapped_type = CropInputRequirement.LEGACY_COST_TYPES.get(cost_type)
        if mapped_type is None:
            raise serializers.ValidationError({"cost_type": ["Type must be Crop Input or Farm Equipment."]})
        attrs["cost_type"] = mapped_type
        unit_cost = attrs.get("cost_per_unit")
        if unit_cost is None or Decimal(str(unit_cost)) <= 0:
            raise serializers.ValidationError({
                "cost_per_unit": ["Enter a unit cost greater than zero. Financial calculations are blocked until this price is configured."],
            })

        programme = attrs.get("programme", getattr(instance, "programme", None))
        if programme is None:
            for name, label in (("group_name", "Group"), ("item_name", "Item")):
                if not str(attrs.get(name, getattr(instance, name, "")) or "").strip():
                    raise serializers.ValidationError({name: [f"{label} is required."]})
            duplicate = CropInputRequirement.objects.filter(
                programme__isnull=True,
                crop=attrs.get("crop", getattr(instance, "crop", None)),
                group_name=attrs.get("group_name", getattr(instance, "group_name", "")),
                item_name=attrs.get("item_name", getattr(instance, "item_name", "")),
                cost_type=attrs["cost_type"],
            )
            if instance is not None:
                duplicate = duplicate.exclude(pk=instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({"non_field_errors": ["The fields crop, group_name, item_name, cost_type must make a unique set."]})
        if programme is not None:
            # Programme catalogue: crop -> programme -> category -> product -> quantity -> price.
            category = attrs.get("input_category", getattr(instance, "input_category", ""))
            product = attrs.get("input_product", getattr(instance, "input_product", None))
            if category not in INPUT_CATEGORIES:
                raise serializers.ValidationError({"input_category": ["Choose Seed, Fertilizer or Chemicals."]})
            if product is None:
                raise serializers.ValidationError({"input_product": ["Choose the input product."]})
            if product.category in INPUT_CATEGORIES and product.category != category:
                raise serializers.ValidationError({"input_product": [f"{product.name} is a {product.get_category_display().lower()} product, not {dict(INPUT_CATEGORY_CHOICES)[category].lower()}."]})
            crop = attrs.get("crop", getattr(instance, "crop", None))
            if crop is not None and not programme.supports_crop(crop):
                raise serializers.ValidationError({"crop": [f"{programme.name} does not support {crop.name}. Add the crop to the programme first."]})
            if programme.input_categories and category not in programme.input_categories:
                label = dict(INPUT_CATEGORY_CHOICES)[category].lower()
                raise serializers.ValidationError({"input_category": [f"{programme.name} does not supply {label}. Add it to the programme's input types first."]})
            duplicate = CropInputRequirement.objects.filter(crop=crop, programme=programme, input_product=product)
            if instance is not None:
                duplicate = duplicate.exclude(pk=instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({"input_product": [f"{product.name} is already in {programme.name}'s catalogue for {crop.name}. Edit that line instead."]})
            attrs["group_name"] = dict(INPUT_CATEGORY_CHOICES)[category]
            attrs["item_name"] = product.name
            attrs["cost_type"] = CropInputRequirement.COST_TYPE_CROP_INPUT
            if not attrs.get("unit", getattr(instance, "unit", "")):
                attrs["unit"] = product.unit
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not data.get("programme"):
            data["programme_name"] = ""
        return data


class CropSellingPriceSerializer(serializers.ModelSerializer):
    crop_name = serializers.CharField(source="crop.name", read_only=True)
    season_name = serializers.SerializerMethodField()

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

    def get_season_name(self, obj):
        return obj.season.name if obj.season_id else ""

    def validate(self, attrs):
        crop = attrs.get("crop", getattr(self.instance, "crop", None))
        season = attrs.get("season", getattr(self.instance, "season", None))
        if season is None:
            raise serializers.ValidationError({"season": ["Select an agricultural year."]})
        if not season_is_selectable(season):
            raise serializers.ValidationError({"season": ["Select the configured agricultural year."]})
        price = attrs.get("price_per_tonne", getattr(self.instance, "price_per_tonne", None))
        if price is None or Decimal(str(price)) <= 0:
            raise serializers.ValidationError({"price_per_tonne": ["Price per tonne must be greater than zero."]})
        active = attrs.get("active", getattr(self.instance, "active", True))
        if active and crop is not None:
            existing = CropSellingPrice.objects.filter(crop=crop, season=season, active=True)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({
                    "season": [f"An active selling price already exists for {crop.name} in agricultural year {season.name}."],
                })
        return attrs
