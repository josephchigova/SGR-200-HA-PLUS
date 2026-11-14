from decimal import Decimal

from rest_framework import serializers

from apps.accounts.privacy import MoneyPrivacyMixin

from .models import FarmerProduction, GMBDelivery, ProductionPlan
from .services import FarmerProductionService


class ProductionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionPlan
        fields = "__all__"


class FarmerProductionSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    farm_name = serializers.CharField(source="farm.farm_name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    membership_number = serializers.CharField(source="farmer.membership_number", read_only=True)
    province_name = serializers.CharField(source="farmer.province.name", read_only=True, default="")
    district_name = serializers.CharField(source="farmer.district.name", read_only=True, default="")
    cluster_name = serializers.CharField(source="farmer.cluster.name", read_only=True, default="")
    lead_farmer_name = serializers.SerializerMethodField()
    irrigated_hectares = serializers.SerializerMethodField()
    crop_season = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = FarmerProduction
        fields = [
            "id", "farmer", "farmer_name", "membership_number", "province_name", "district_name", "cluster_name",
            "lead_farmer_name", "irrigated_hectares", "crop_season", "status_label",
            "farm", "farm_name", "season", "season_name", "crop",
            "contracted_hectares", "planted_hectares", "planting_date", "crop_stage", "expected_yield",
            "estimated_production", "actual_production", "harvest_date", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_lead_farmer_name(self, obj):
        cluster = obj.farmer.cluster
        if cluster is None:
            return ""
        if cluster.lead_member_id:
            return cluster.lead_member.full_name
        if cluster.lead_farmer_id:
            user = cluster.lead_farmer
            return f"{user.first_name} {user.last_name}".strip() or user.email
        return ""

    def get_irrigated_hectares(self, obj):
        """The farm's irrigated land, up to this crop's hectares."""
        if obj.farm_id is None:
            return "0.00"
        value = min(Decimal(obj.farm.irrigated_hectares or 0), Decimal(obj.contracted_hectares or 0))
        return f"{value.quantize(Decimal('0.01'))}"

    def get_crop_season(self, obj):
        categories = self.context.get("crop_categories")
        if categories is None:
            from apps.programmes.models import Crop

            categories = {name.lower(): category for name, category in Crop.objects.values_list("name", "category")}
            self.context["crop_categories"] = categories
        return categories.get((obj.crop or "").lower(), "")

    def validate(self, attrs):
        data = {}
        for field_name in (
            "farmer",
            "farm",
            "season",
            "contracted_hectares",
            "planted_hectares",
        ):
            if field_name in attrs:
                data[field_name] = attrs[field_name]
            elif self.instance:
                data[field_name] = getattr(self.instance, field_name)
        # The approved input hectares are checked when a record is captured or its land changes.
        # Moving an existing record to its next stage, or recording yields, leaves them as they were.
        allocation_fields = ("farmer", "farm", "season", "contracted_hectares")
        check_allocation = self.instance is None or any(
            name in attrs and attrs[name] != getattr(self.instance, name) for name in allocation_fields
        )
        try:
            FarmerProductionService.validate(data, check_allocation=check_allocation)
            if "farm" not in attrs and data.get("farm") is not None:
                attrs["farm"] = data["farm"]
            return attrs
        except ValueError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error


class GMBDeliverySerializer(MoneyPrivacyMixin, serializers.ModelSerializer):
    money_fields = ('price', 'value', 'amount_recovered', 'farmer_balance')

    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)

    class Meta:
        model = GMBDelivery
        fields = [
            "id", "farmer", "farmer_name", "farm", "season", "season_name", "crop", "delivery_date",
            "gmb_depot", "delivery_reference", "ticket_number", "tonnes", "price", "value", "recovery_tonnes",
            "amount_recovered", "farmer_balance", "document", "recorded_by", "created_at", "updated_at",
        ]
        read_only_fields = ["recorded_by", "created_at", "updated_at", "value", "amount_recovered", "farmer_balance"]

    def validate(self, attrs):
        tonnes = attrs.get("tonnes", getattr(self.instance, "tonnes", Decimal("0.00")))
        price = attrs.get("price", getattr(self.instance, "price", Decimal("0.00")))
        depot = attrs.get("gmb_depot", getattr(self.instance, "gmb_depot", ""))
        reference = attrs.get("delivery_reference", getattr(self.instance, "delivery_reference", ""))
        ticket = attrs.get("ticket_number", getattr(self.instance, "ticket_number", ""))
        recovery_tonnes = attrs.get("recovery_tonnes", getattr(self.instance, "recovery_tonnes", None))
        if recovery_tonnes is None:
            recovery_tonnes = tonnes
        if tonnes <= 0:
            raise serializers.ValidationError({"tonnes": "Delivered tonnes must be greater than zero."})
        if self.instance is None:
            from apps.programmes.models import Crop
            from apps.programmes.services import CropPricingService

            season = attrs.get("season")
            farmer = attrs.get("farmer")
            crop_name = str(attrs.get("crop") or "").strip()
            catalogue_crop = Crop.objects.filter(name__iexact=crop_name, active=True).first() if crop_name else None
            if catalogue_crop is None or season is None:
                raise serializers.ValidationError({
                    "crop": ["Select a catalogue crop and agricultural year so the selling price can be applied."],
                })
            try:
                catalogue_price = CropPricingService.resolve_price_per_tonne(crop=catalogue_crop, season=season)
            except ValueError as error:
                raise serializers.ValidationError({"price": [str(error)]}) from error
            if catalogue_price <= 0:
                raise serializers.ValidationError({
                    "price": [
                        f"{catalogue_crop.name} has no configured price per tonne for {season.name}. "
                        "Configure the price in the Crop Catalogue before recording this delivery."
                    ],
                })
            price = catalogue_price
            attrs["price"] = catalogue_price
            attrs["crop"] = catalogue_crop.name
            reference = reference.strip()
            ticket = ticket.strip()
            duplicate_filters = {"farmer": farmer, "season": season}
            if ticket and GMBDelivery.objects.filter(**duplicate_filters, ticket_number__iexact=ticket).exists():
                raise serializers.ValidationError({
                    "ticket_number": ["A delivery with this ticket number is already recorded for this farmer and season."],
                })
            if reference and GMBDelivery.objects.filter(**duplicate_filters, delivery_reference__iexact=reference).exists():
                raise serializers.ValidationError({
                    "delivery_reference": ["A delivery with this reference is already recorded for this farmer and season."],
                })
        else:
            price = self.instance.price
            attrs["price"] = price
        if price < 0:
            raise serializers.ValidationError({"price": "Price cannot be negative."})
        if recovery_tonnes < 0 or recovery_tonnes > tonnes:
            raise serializers.ValidationError({"recovery_tonnes": "Recovery tonnes must be between zero and delivered tonnes."})
        if not depot.strip():
            raise serializers.ValidationError({"gmb_depot": "GMB depot is required."})
        if not reference.strip() and not ticket.strip():
            raise serializers.ValidationError({"ticket_number": "A delivery reference or ticket number is required."})
        attrs["value"] = tonnes * price
        attrs["recovery_tonnes"] = recovery_tonnes
        attrs["amount_recovered"] = recovery_tonnes * price
        attrs["farmer_balance"] = attrs["value"] - attrs["amount_recovered"]
        return attrs
