from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import ProgrammeWorkflowPermission
from apps.programmes.period import filter_by_agricultural_year, filter_by_crop_name, parse_crop_season

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch
from .serializers import ARDAFarmerRequestSerializer, ARDARequestBatchSerializer, ARDARequestSerializer


class ARDARequestViewSet(viewsets.ModelViewSet):
    queryset = ARDARequest.objects.select_related("farmer").all()
    serializer_class = ARDARequestSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]


class ARDARequestBatchViewSet(viewsets.ModelViewSet):
    queryset = ARDARequestBatch.objects.select_related("programme", "season").all()
    serializer_class = ARDARequestBatchSerializer
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

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        from apps.inputs.models import InputAllocation
        from apps.programmes.models import Season

        season = instance.season
        if season is None or season.status != Season.STATUS_ACTIVE:
            raise ValidationError({"non_field_errors": ["Past-season ARDA requests are read-only and cannot be modified."]})
        if instance.farmer_requests.exists():
            raise ValidationError({
                "detail": ["This request has farmer lines. Reject it instead of deleting the history."],
            })
        allocations = InputAllocation.objects.filter(programme=instance.programme).exclude(status=InputAllocation.STATUS_CANCELLED)
        if instance.crop:
            allocations = allocations.filter(crop__iexact=instance.crop)
        if allocations.exists():
            raise ValidationError({
                "detail": ["This request already has input allocations. Reject or close it instead of deleting it."],
            })
        if instance.status == instance.STATUS_APPROVED:
            raise ValidationError({
                "detail": ["An approved request cannot be deleted. Reject it if it should no longer be used."],
            })
        super().perform_destroy(instance)


class ARDAFarmerRequestViewSet(viewsets.ModelViewSet):
    queryset = ARDAFarmerRequest.objects.select_related("request_batch", "farmer", "farm").all()
    serializer_class = ARDAFarmerRequestSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="request_batch__season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "request_batch__crop")
        return queryset

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        request_line = self.get_object()
        if request_line.status != ARDAFarmerRequest.STATUS_PENDING:
            return Response({"detail": "Only pending requests can be approved."}, status=400)
        try:
            from decimal import Decimal, InvalidOperation
            from django.db import transaction
            from apps.programmes.models import Programme

            approved_hectares = Decimal(str(request.data.get("approved_hectares", request_line.requested_hectares)))
            if approved_hectares <= 0 or approved_hectares > request_line.requested_hectares:
                return Response({"approved_hectares": ["Must be positive and no greater than requested hectares."]}, status=400)
            with transaction.atomic():
                programme = Programme.objects.select_for_update().get(pk=request_line.request_batch.programme_id)
                if programme.total_allocated_hectares + approved_hectares > programme.announced_hectares:
                    return Response({"approved_hectares": ["Approval exceeds remaining programme capacity."]}, status=400)
                request_line.approved_hectares = approved_hectares
                request_line.status = ARDAFarmerRequest.STATUS_APPROVED
                request_line.save(update_fields=["approved_hectares", "status"])
                programme.total_allocated_hectares += approved_hectares
                programme.save(update_fields=["total_allocated_hectares", "updated_at"])
        except (InvalidOperation, ValueError):
            return Response({"approved_hectares": ["Enter a valid decimal amount."]}, status=400)
        return Response(self.get_serializer(request_line).data)
