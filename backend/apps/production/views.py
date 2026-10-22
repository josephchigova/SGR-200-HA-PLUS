from django.db import transaction
from rest_framework import permissions, viewsets
from rest_framework.exceptions import ValidationError

from apps.accounts.permissions import ProgrammeWorkflowPermission, RecoveryWorkflowPermission
from apps.programmes.models import Crop, CropInputRequirement, CropSellingPrice
from apps.programmes.period import (
    filter_by_agricultural_year,
    filter_by_crop_name,
    filter_planting_by_crop_season,
    parse_crop_season,
)
from apps.programmes.serializers import CropInputRequirementSerializer, CropSellingPriceSerializer, CropSerializer
from apps.recovery.services import RecoveryCalculationService

from .models import FarmerProduction, GMBDelivery, ProductionPlan, SeasonalPlantingPlan
from .seasonal_serializers import SeasonalPlantingPlanSerializer
from .serializers import FarmerProductionSerializer, GMBDeliverySerializer, ProductionPlanSerializer


class ProductionPlanViewSet(viewsets.ModelViewSet):
    queryset = ProductionPlan.objects.all()
    serializer_class = ProductionPlanSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        if season and str(season).isdigit():
            from apps.programmes.models import Season

            season = Season.objects.filter(pk=int(season)).values_list("name", flat=True).first() or ""
            if season == "":
                return queryset.none()
        if season:
            queryset = queryset.filter(season__iexact=season)
        if season_name:
            queryset = queryset.filter(season__iexact=season_name)
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        return queryset


class FarmerProductionViewSet(viewsets.ModelViewSet):
    queryset = FarmerProduction.objects.select_related("farmer", "farm", "season").all()
    serializer_class = FarmerProductionSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        return queryset


class GMBDeliveryViewSet(viewsets.ModelViewSet):
    queryset = GMBDelivery.objects.select_related("farmer", "farm", "season", "recorded_by").all()
    serializer_class = GMBDeliverySerializer
    permission_classes = [permissions.IsAuthenticated, RecoveryWorkflowPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        return queryset

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                delivery = serializer.save(recorded_by=self.request.user)
                RecoveryCalculationService.apply_delivery(delivery)
        except ValueError as error:
            raise ValidationError({"recovery_tonnes": [str(error)]}) from error


class CropViewSet(viewsets.ModelViewSet):
    queryset = Crop.objects.all()
    serializer_class = CropSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        active = self.request.query_params.get("active")
        if active is not None:
            queryset = queryset.filter(active=str(active).lower() in {"1", "true", "yes"})
        category = parse_crop_season(self.request.query_params.get("category") or self.request.query_params.get("crop_season"))
        if category:
            queryset = queryset.filter(category=category)
        return queryset


class CropInputRequirementViewSet(viewsets.ModelViewSet):
    queryset = CropInputRequirement.objects.select_related("crop").all()
    serializer_class = CropInputRequirementSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        crop_id = self.request.query_params.get("crop")
        if crop_id:
            queryset = queryset.filter(crop_id=crop_id)
        return queryset

    def perform_destroy(self, instance):
        from apps.inputs.models import InputAllocationLine

        if InputAllocationLine.objects.filter(source_requirement=instance).exists():
            raise ValidationError({
                "detail": ["This input requirement is used by allocations. Deactivate it instead of deleting it."],
            })
        instance.delete()


class CropSellingPriceViewSet(viewsets.ModelViewSet):
    queryset = CropSellingPrice.objects.select_related("crop", "season").all()
    serializer_class = CropSellingPriceSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        crop_id = self.request.query_params.get("crop")
        season_id = self.request.query_params.get("season")
        if crop_id:
            queryset = queryset.filter(crop_id=crop_id)
        if season_id:
            queryset = queryset.filter(season_id=season_id)
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = queryset.filter(crop__category=crop_season)
        return queryset

    def perform_destroy(self, instance):
        from apps.inputs.models import InputAllocation
        from apps.production.models import GMBDelivery
        from apps.recovery.models import InputDebt

        used_by_debt = InputDebt.objects.filter(crop__iexact=instance.crop.name, programme__season=instance.season).exists()
        used_by_delivery = GMBDelivery.objects.filter(crop__iexact=instance.crop.name, season=instance.season).exists()
        used_by_allocation = InputAllocation.objects.filter(crop_reference=instance.crop, programme__season=instance.season).exists()
        if used_by_debt or used_by_delivery or used_by_allocation:
            raise ValidationError({
                "detail": [
                    "This selling price has already been used for this crop and agricultural year. "
                    "Deactivate it instead of deleting it. Saved deliveries and recovery records keep their own price."
                ],
            })
        instance.delete()


class SeasonalPlantingPlanViewSet(viewsets.ModelViewSet):
    queryset = SeasonalPlantingPlan.objects.select_related(
        "farmer", "farm", "season", "summer_crop", "winter_crop"
    ).all()
    serializer_class = SeasonalPlantingPlanSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_planting_by_crop_season(queryset, crop_season)
        return queryset
