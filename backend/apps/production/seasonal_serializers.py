from rest_framework import serializers

from .models import SeasonalPlantingPlan
from .seasonal_services import SeasonalPlantingValidationService
from .seasonal_services import SeasonalSubscriptionService


class SeasonalPlantingPlanSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    farm_name = serializers.CharField(source="farm.farm_name", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    summer_crop_name = serializers.CharField(source="summer_crop.name", read_only=True)
    winter_crop_name = serializers.CharField(source="winter_crop.name", read_only=True)
    total_planted_hectares = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    recommended_subscription_amount = serializers.SerializerMethodField()

    class Meta:
        model = SeasonalPlantingPlan
        fields = [
            "id", "farmer", "farmer_name", "farm", "farm_name", "season", "season_name",
            "summer_crop", "summer_crop_name", "summer_hectares", "winter_crop", "winter_crop_name",
            "winter_hectares", "total_planted_hectares", "notes", "created_at", "updated_at",
            "recommended_subscription_amount",
        ]
        read_only_fields = ["created_at", "updated_at", "total_planted_hectares"]

    def validate(self, attrs):
        instance = self.instance
        farmer = attrs.get("farmer", getattr(instance, "farmer", None))
        farm = attrs.get("farm", getattr(instance, "farm", None))
        if farm is None or farmer is None or farm.farmer_id != farmer.pk:
            raise serializers.ValidationError({"farm": "Select a farm belonging to the farmer."})
        try:
            SeasonalPlantingValidationService.validate(
                summer_crop=attrs.get("summer_crop", getattr(instance, "summer_crop", None)),
                winter_crop=attrs.get("winter_crop", getattr(instance, "winter_crop", None)),
                summer_hectares=attrs.get("summer_hectares", getattr(instance, "summer_hectares", 0)),
                winter_hectares=attrs.get("winter_hectares", getattr(instance, "winter_hectares", 0)),
                farm=farm,
            )
        except ValueError as error:
            raise serializers.ValidationError({"non_field_errors": [str(error)]}) from error
        return attrs

    def get_recommended_subscription_amount(self, obj):
        return SeasonalSubscriptionService.subscription_amount(obj.total_planted_hectares)
