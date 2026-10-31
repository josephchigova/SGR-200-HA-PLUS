from rest_framework import serializers

from decimal import Decimal

from rest_framework import serializers

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

    class Meta:
        model = FarmerProduction
        fields = [
            "id", "farmer", "farmer_name", "farm", "farm_name", "season", "season_name", "crop",
            "contracted_hectares", "planted_hectares", "planting_date", "crop_stage", "expected_yield",
            "estimated_production", "actual_production", "harvest_date", "status", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

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
        try:
            FarmerProductionService.validate(data)
            if "farm" not in attrs and data.get("farm") is not None:
                attrs["farm"] = data["farm"]
            return attrs
        except ValueError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error


class GMBDeliverySerializer(serializers.ModelSerializer):
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
