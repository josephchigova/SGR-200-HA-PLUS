from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from apps.accounts.scoping import scope_by_farmer
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

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


class ProductionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 500


PLANTED_STATES = {FarmerProduction.STATUS_PLANTED, FarmerProduction.STATUS_HARVESTED, FarmerProduction.STATUS_COMPLETED}
ORDERING = {
    "farmer": "farmer__full_name", "crop": "crop", "season": "season__name", "status": "status",
    "registered": "contracted_hectares", "planted": "planted_hectares", "created": "created_at",
}
TWO = Decimal("0.01")


def _money_free(value):
    return f"{Decimal(value or 0).quantize(TWO)}"


def _irrigated(row):
    """Irrigated land under this crop: the farm's irrigated land, up to the crop's hectares."""
    if row.farm_id is None:
        return Decimal("0.00")
    return min(Decimal(row.farm.irrigated_hectares or 0), Decimal(row.contracted_hectares or 0))


def _summarise(rows):
    """Totals, per-crop, per-lead and per-status figures for a set of production records."""
    registered = planted = irrigated = estimated = actual = Decimal("0.00")
    farmers_planted, crops, farmers = set(), set(), set()
    by_crop, by_lead, by_status = {}, {}, {}
    for row in rows:
        contracted = Decimal(row.contracted_hectares or 0)
        planted_ha = Decimal(row.planted_hectares or 0)
        irrigated_ha = _irrigated(row)
        est = Decimal(row.estimated_production or 0)
        act = Decimal(row.actual_production or 0)
        name = row.crop or "Crop"
        registered += contracted
        planted += planted_ha
        irrigated += irrigated_ha
        estimated += est
        actual += act
        crops.add(name)
        farmers.add(row.farmer_id)
        is_planted = planted_ha > 0 or row.status in PLANTED_STATES
        if is_planted:
            farmers_planted.add(row.farmer_id)
        crop = by_crop.setdefault(name, {
            "crop": name, "farmers": set(), "records": 0, "hectares": Decimal("0.00"), "planted_hectares": Decimal("0.00"),
            "irrigated_hectares": Decimal("0.00"), "estimated_production": Decimal("0.00"), "actual_production": Decimal("0.00"),
        })
        crop["farmers"].add(row.farmer_id)
        crop["records"] += 1
        crop["hectares"] += contracted
        crop["planted_hectares"] += planted_ha
        crop["irrigated_hectares"] += irrigated_ha
        crop["estimated_production"] += est
        crop["actual_production"] += act
        lead_name, district = _lead_place(row.farmer)
        lead = by_lead.setdefault(lead_name, {
            "lead_farmer": lead_name, "district": district, "farmers": set(), "registered_hectares": Decimal("0.00"),
            "planted_hectares": Decimal("0.00"), "irrigated_hectares": Decimal("0.00"),
            "estimated_production": Decimal("0.00"), "actual_production": Decimal("0.00"),
        })
        lead["farmers"].add(row.farmer_id)
        lead["registered_hectares"] += contracted
        lead["planted_hectares"] += planted_ha
        lead["irrigated_hectares"] += irrigated_ha
        lead["estimated_production"] += est
        lead["actual_production"] += act
        status = by_status.setdefault(row.status, {"status": row.status, "label": row.get_status_display(), "records": 0, "hectares": Decimal("0.00")})
        status["records"] += 1
        status["hectares"] += contracted

    def yield_of(produced, area):
        return _money_free(produced / area) if area else "0.00"

    crop_rows = [
        {
            "crop": bucket["crop"], "farmers": len(bucket["farmers"]), "records": bucket["records"],
            "hectares": _money_free(bucket["hectares"]),
            "share": int(round(bucket["hectares"] / registered * 100)) if registered else 0,
            "planted_hectares": _money_free(bucket["planted_hectares"]),
            "irrigated_hectares": _money_free(bucket["irrigated_hectares"]),
            "estimated_production": _money_free(bucket["estimated_production"]),
            "actual_production": _money_free(bucket["actual_production"]),
            "yield_per_hectare": yield_of(bucket["actual_production"], bucket["planted_hectares"]),
            "planting_progress": round(bucket["planted_hectares"] / bucket["hectares"] * 100) if bucket["hectares"] else 0,
        }
        for bucket in sorted(by_crop.values(), key=lambda item: (-item["hectares"], item["crop"]))
    ]
    lead_rows = [
        {
            "lead_farmer": bucket["lead_farmer"], "district": bucket["district"], "farmers": len(bucket["farmers"]),
            "registered_hectares": _money_free(bucket["registered_hectares"]),
            "planted_hectares": _money_free(bucket["planted_hectares"]),
            "irrigated_hectares": _money_free(bucket["irrigated_hectares"]),
            "estimated_production": _money_free(bucket["estimated_production"]),
            "actual_production": _money_free(bucket["actual_production"]),
            "yield_per_hectare": yield_of(bucket["actual_production"], bucket["planted_hectares"]),
            "planting_progress": round(bucket["planted_hectares"] / bucket["registered_hectares"] * 100) if bucket["registered_hectares"] else 0,
        }
        for bucket in sorted(by_lead.values(), key=lambda item: (-item["registered_hectares"], item["lead_farmer"]))
    ]
    order = [code for code, _ in FarmerProduction.STATUS_CHOICES]
    status_rows = [
        {**bucket, "hectares": _money_free(bucket["hectares"])}
        for bucket in sorted(by_status.values(), key=lambda item: order.index(item["status"]) if item["status"] in order else 99)
    ]
    return {
        "records": len(rows),
        "farmers": len(farmers),
        "registered_hectares": _money_free(registered),
        "planted_hectares": _money_free(planted),
        "irrigated_hectares": _money_free(irrigated),
        "farmers_planted": len(farmers_planted),
        "crops": len(crops),
        "estimated_production": _money_free(estimated),
        "actual_production": _money_free(actual),
        "by_crop": crop_rows,
        "by_lead": lead_rows,
        "by_status": status_rows,
    }


class FarmerProductionViewSet(viewsets.ModelViewSet):
    queryset = FarmerProduction.objects.select_related(
        "farmer__province", "farmer__district", "farmer__cluster__lead_member", "farmer__cluster__lead_farmer", "farm", "season",
    ).all()
    serializer_class = FarmerProductionSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    pagination_class = ProductionPagination

    def _filtered(self, queryset):
        """Every filter except the agricultural year, so last year can use the same ones."""
        params = self.request.query_params
        crop_season = parse_crop_season(params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        if params.get("crop"):
            queryset = queryset.filter(crop__iexact=params["crop"])
        if params.get("province"):
            queryset = queryset.filter(farmer__province_id=params["province"])
        if params.get("district"):
            queryset = queryset.filter(farmer__district_id=params["district"])
        if params.get("lead_member"):
            queryset = queryset.filter(farmer__cluster__lead_member_id=params["lead_member"])
        if params.get("status"):
            queryset = queryset.filter(status__in=[code.strip().upper() for code in params["status"].split(",") if code.strip()])
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(farmer__full_name__icontains=search) | Q(farmer__membership_number__icontains=search)
                | Q(farmer__national_id__icontains=search) | Q(crop__icontains=search)
                | Q(farmer__cluster__name__icontains=search)
            )
        ordering = params.get("ordering", "")
        field = ORDERING.get(ordering.lstrip("-"))
        if field:
            queryset = queryset.order_by(f"-{field}" if ordering.startswith("-") else field, "id")
        else:
            queryset = queryset.order_by("farmer__full_name", "crop", "id")
        return queryset

    def get_queryset(self):
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        return self._filtered(queryset)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["crop_categories"] = {name.lower(): category for name, category in Crop.objects.values_list("name", "category")}
        return context

    def _previous_season(self):
        from apps.programmes.models import Season

        params = self.request.query_params
        season = params.get("season")
        current = None
        if season and str(season).isdigit():
            current = Season.objects.filter(pk=int(season)).first()
        elif params.get("season_name") or season:
            current = Season.objects.filter(name__iexact=params.get("season_name") or season).first()
        if current is None:
            return None
        return Season.objects.filter(start_date__lt=current.start_date).order_by("-start_date").first()

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        """Hectares, yields, crop, lead-farmer and status totals for the selected period."""
        summary = _summarise(list(self.get_queryset()))
        previous_season = self._previous_season()
        summary["previous"] = None
        if previous_season is not None:
            base = scope_by_farmer(FarmerProduction.objects.select_related(
                "farmer__district", "farmer__cluster__lead_member", "farmer__cluster__lead_farmer", "farm", "season",
            ).filter(season=previous_season), request.user)
            earlier = _summarise(list(self._filtered(base)))
            if earlier["records"]:
                summary["previous"] = {
                    "season": previous_season.name,
                    **{key: earlier[key] for key in ("registered_hectares", "planted_hectares", "irrigated_hectares", "farmers_planted", "crops", "estimated_production", "actual_production")},
                }
        return Response(summary)


def _lead_place(farmer):
    cluster = farmer.cluster
    if cluster is not None and cluster.lead_member_id:
        name = cluster.lead_member.full_name
    elif cluster is not None and cluster.lead_farmer_id:
        user = cluster.lead_farmer
        name = f"{user.first_name} {user.last_name}".strip() or user.email
    else:
        name = "No lead farmer"
    district = farmer.district.name if farmer.district_id else ""
    return name, district


class GMBDeliveryViewSet(viewsets.ModelViewSet):
    queryset = GMBDelivery.objects.select_related("farmer", "farm", "season", "recorded_by").all()
    serializer_class = GMBDeliverySerializer
    permission_classes = [permissions.IsAuthenticated, RecoveryWorkflowPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
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

    @action(detail=False, methods=["get"], url_path="recovery-preview")
    def recovery_preview(self, request):
        from apps.farmers.models import Farmer, Farm
        from apps.programmes.models import Season

        farmer_id = request.query_params.get("farmer")
        season_id = request.query_params.get("season")
        crop_name = (request.query_params.get("crop") or "").strip()
        farm_id = request.query_params.get("farm")
        if not farmer_id or not season_id or not crop_name:
            return Response(
                {"detail": "Select a farmer, agricultural year and crop before calculating recovery."},
                status=400,
            )
        farmer = Farmer.objects.filter(pk=farmer_id).first()
        season = Season.objects.filter(pk=season_id).first()
        farm = Farm.objects.filter(pk=farm_id, farmer=farmer).first() if farm_id and farmer else None
        if farmer is None or season is None:
            return Response({"detail": "Select a farmer and agricultural year before calculating recovery."}, status=400)
        if farm_id and farm is None:
            return Response({"farm": ["Select a farm that belongs to this farmer."]}, status=400)
        try:
            preview = RecoveryCalculationService.preview_delivery_recovery(
                farmer=farmer,
                farm=farm,
                season=season,
                crop_name=crop_name,
            )
        except ValueError as error:
            return Response({"price": [str(error)]}, status=400)
        return Response(preview)


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
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_planting_by_crop_season(queryset, crop_season)
        return queryset
