from django.db.models import Q
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.privacy import hides_money
from apps.accounts.permissions import ProgrammeWorkflowPermission
from apps.accounts.scoping import scope_by_farmer
from apps.farmers.models import Farmer
from apps.programmes.models import Crop, Programme, Season
from apps.programmes.period import filter_allocations_by_crop_season, parse_crop_season

from .models import Input, InputAllocation, InputIssue
from .serializers import InputAllocationSerializer, InputIssueSerializer, InputSerializer
from . import programme_allocation
from .services import InputAllocationService


class InputIssueViewSet(viewsets.ModelViewSet):
    queryset = InputIssue.objects.select_related("farmer").all()
    serializer_class = InputIssueSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    # Stores officers record physical distribution.
    extra_write_roles = {User.ROLE_STORES_OFFICER}

    def get_queryset(self):
        return scope_by_farmer(super().get_queryset(), self.request.user)


class InputViewSet(viewsets.ModelViewSet):
    queryset = Input.objects.filter(active=True)
    serializer_class = InputSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    # Procurement and stores officers maintain the input product list.
    extra_write_roles = {User.ROLE_PROCUREMENT_OFFICER, User.ROLE_STORES_OFFICER}


class InputAllocationViewSet(viewsets.ModelViewSet):
    queryset = InputAllocation.objects.select_related("farmer", "farm", "programme", "crop_reference", "input").prefetch_related("calculation_lines").all()
    serializer_class = InputAllocationSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        # Allocations sourced per category carry their own year; older ones use the programme's.
        if season and str(season).isdigit():
            queryset = queryset.filter(Q(season_id=season) | Q(season__isnull=True, programme__season_id=season))
        elif season:
            queryset = queryset.filter(Q(season__name__iexact=season) | Q(season__isnull=True, programme__season__name__iexact=season))
        if season_name:
            queryset = queryset.filter(Q(season__name__iexact=season_name) | Q(season__isnull=True, programme__season__name__iexact=season_name))
        queryset = queryset.select_related("season", "cancelled_by").prefetch_related("calculation_lines__programme", "calculation_lines__batch_input__batch")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status__in=[part.strip().upper() for part in status_filter.split(",") if part.strip()])
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_allocations_by_crop_season(queryset, crop_season)
        return queryset

    @action(detail=False, methods=["get"], url_path="preview")
    def preview(self, request):
        try:
            farmer = Farmer.objects.get(pk=request.query_params.get("farmer"))
            programme = Programme.objects.get(pk=request.query_params.get("programme"))
            farm = farmer.farms.filter(pk=request.query_params.get("farm")).first() if request.query_params.get("farm") else None
            crop_reference = Crop.objects.filter(pk=request.query_params.get("crop_reference")).first() if request.query_params.get("crop_reference") else None
            crop_name = request.query_params.get("crop", "")
            hectares = request.query_params.get("hectares", "0")
            preview_data = InputAllocationService.preview_allocation(
                farmer=farmer,
                farm=farm,
                programme=programme,
                crop_reference=crop_reference,
                crop_name=crop_name,
                hectares=hectares,
                crop_season=parse_crop_season(request.query_params.get("crop_season")),
            )
        except Farmer.DoesNotExist as error:
            raise ValidationError({"farmer": ["Select a valid farmer."]}) from error
        except Programme.DoesNotExist as error:
            raise ValidationError({"programme": ["Select a valid programme."]}) from error
        except ValueError as error:
            raise ValidationError({"non_field_errors": [str(error)]}) from error

        response_payload = {
            "farmer_id": preview_data["farmer_id"],
            "farm_id": preview_data["farm_id"],
            "programme_id": preview_data["programme_id"],
            "crop": preview_data["crop"],
            "hectares": str(preview_data["hectares"]),
            "calculated_input_cost_per_hectare": str(preview_data["calculated_input_cost_per_hectare"]),
            "total_input_cost": str(preview_data["total_input_cost"]),
            "selling_price_per_tonne": str(preview_data["selling_price_per_tonne"]),
            "required_recovery_tonnes": str(preview_data["required_recovery_tonnes"]),
            "arda_requested_hectares": str(preview_data["arda_requested_hectares"]),
            "arda_allocated_hectares": str(preview_data["arda_allocated_hectares"]),
            "arda_available_hectares": str(preview_data["arda_available_hectares"]),
            "lines": [
                {
                    "group_name": line["group_name"],
                    "item_name": line["item_name"],
                    "rate_per_hectare": str(line["rate_per_hectare"]),
                    "required_quantity": str(line["required_quantity"]),
                    "unit": line["unit"],
                    "cost_per_unit": str(line["cost_per_unit"]) if line["cost_per_unit"] is not None else None,
                    "cost_per_hectare": str(line["cost_per_hectare"]),
                    "calculated_cost": str(line["calculated_cost"]),
                    "included_in_total": line["included_in_total"],
                }
                for line in preview_data["lines"]
            ],
        }
        return Response(response_payload)


    # Seed, Fertilizer and Chemicals each from their own programme ------------------------

    def _plan_inputs(self, data):
        try:
            farmer = Farmer.objects.get(pk=data.get("farmer"))
        except (Farmer.DoesNotExist, ValueError, TypeError) as error:
            raise ValidationError({"farmer": ["Select a farmer from the suggestions."]}) from error
        if not _in_scope(farmer, self.request.user):
            raise ValidationError({"farmer": ["This farmer is outside your area."]})
        farm = farmer.farms.filter(pk=data.get("farm")).first() if data.get("farm") else None
        season = Season.objects.filter(pk=data.get("season")).first() if str(data.get("season") or "").isdigit() else None
        crop = Crop.objects.filter(pk=data.get("crop")).first() if str(data.get("crop") or "").isdigit() else None
        selections = data.get("selections") or {}
        if not isinstance(selections, dict):
            raise ValidationError({"selections": ["Send one programme choice per input category."]})
        return {"farmer": farmer, "farm": farm, "season": season, "crop": crop, "hectares": data.get("hectares"), "selections": selections}

    def perform_destroy(self, instance):
        if instance.sourced_by_category or instance.stock_movements.exists():
            raise ValidationError({"detail": ["This allocation took stock from request batches. Cancel it instead, so the stock is returned with a record."]})
        instance.delete()

    @action(detail=False, methods=["get"], url_path="programme-options")
    def programme_options(self, request):
        crop = Crop.objects.filter(pk=request.query_params.get("crop")).first()
        season = Season.objects.filter(pk=request.query_params.get("season")).first()
        if crop is None or season is None:
            raise ValidationError({"detail": ["Choose the crop and the agricultural year first."]})
        options = programme_allocation.programme_options(crop=crop, season=season)
        if hides_money(request.user):
            for entries in options.values():
                for entry in entries:
                    for product in entry["products"]:
                        product["unit_price"] = None
        farmer_id = request.query_params.get("farmer")
        limit = None
        if farmer_id and str(farmer_id).isdigit():
            farmer = Farmer.objects.filter(pk=farmer_id).first()
            if farmer is not None:
                limit = programme_allocation.crop_hectares(farmer, crop, season)
        return Response({"crop_hectares": str(limit) if limit is not None else None, "categories": options})

    @action(detail=False, methods=["post"], url_path="programme-preview")
    def programme_preview(self, request):
        try:
            plan = programme_allocation.build_plan(**self._plan_inputs(request.data))
        except ValueError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        return Response(programme_allocation.serialize_plan(plan, show_money=not hides_money(request.user)))

    @action(detail=False, methods=["post"], url_path="programme-allocate")
    def programme_allocate(self, request):
        self.check_permissions(request)
        try:
            allocation = programme_allocation.confirm(
                **self._plan_inputs(request.data), user=request.user,
                crop_season=parse_crop_season(request.data.get("crop_season")),
            )
        except ValueError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        return Response(self.get_serializer(allocation).data, status=201)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        allocation = self.get_object()
        try:
            allocation = programme_allocation.cancel(allocation=allocation, reason=request.data.get("reason"), user=request.user)
        except ValueError as error:
            raise ValidationError({"detail": [str(error)]}) from error
        return Response(self.get_serializer(allocation).data)


def _in_scope(farmer, user):
    from apps.accounts.scoping import scope_farmers

    return scope_farmers(Farmer.objects.filter(pk=farmer.pk), user).exists()
