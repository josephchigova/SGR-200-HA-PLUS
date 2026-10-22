from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.accounts.permissions import ProgrammeWorkflowPermission
from apps.farmers.models import Farmer
from apps.programmes.models import Crop, Programme
from apps.programmes.period import filter_allocations_by_crop_season, filter_by_agricultural_year, parse_crop_season

from .models import Input, InputAllocation, InputIssue
from .serializers import InputAllocationSerializer, InputIssueSerializer, InputSerializer
from .services import InputAllocationService


class InputIssueViewSet(viewsets.ModelViewSet):
    queryset = InputIssue.objects.select_related("farmer").all()
    serializer_class = InputIssueSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]


class InputViewSet(viewsets.ModelViewSet):
    queryset = Input.objects.filter(active=True)
    serializer_class = InputSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]


class InputAllocationViewSet(viewsets.ModelViewSet):
    queryset = InputAllocation.objects.select_related("farmer", "farm", "programme", "crop_reference", "input").prefetch_related("calculation_lines").all()
    serializer_class = InputAllocationSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="programme__season")
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
