from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import ProgrammeWorkflowPermission
from apps.accounts.scoping import scope_by_farmer
from apps.programmes.period import filter_by_agricultural_year, filter_by_crop_name, parse_crop_season

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch
from .serializers import ARDAFarmerRequestSerializer, ARDARequestBatchSerializer, ARDARequestSerializer


class ARDARequestViewSet(viewsets.ModelViewSet):
    queryset = ARDARequest.objects.select_related("farmer").all()
    serializer_class = ARDARequestSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        return scope_by_farmer(super().get_queryset(), self.request.user)


class ARDARequestBatchViewSet(viewsets.ModelViewSet):
    queryset = ARDARequestBatch.objects.select_related("programme", "season", "approved_by", "created_by").prefetch_related("lines").all()
    serializer_class = ARDARequestBatchSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    # Request batches are organisation-wide submissions to ARDA.
    denied_roles = {User.ROLE_LEAD_FARMER}

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        params = self.request.query_params
        if params.get("programme"):
            queryset = queryset.filter(programme_id=params["programme"])
        if params.get("crop"):
            queryset = queryset.filter(crop__iexact=params["crop"].strip())
        if params.get("status"):
            queryset = queryset.filter(status=params["status"].upper())
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        """Delete a request. Refused while farmers hold allocations from it.

        Cancelled allocations keep their own copy of the products and prices and are only
        unlinked from the request. Its farmer lines and products go with it.
        """
        from django.db import transaction

        from apps.inputs.models import InputAllocation, InputAllocationLine
        from apps.programmes.models import Season

        from .models import BatchStockMovement, RequestBatchInput
        from .services import batch_allocations

        season = instance.season
        if season is None or season.status != Season.STATUS_ACTIVE:
            raise ValidationError({"non_field_errors": ["Past-season input requests are read-only and cannot be modified."]})
        live = batch_allocations(instance)
        if live.exists():
            raise ValidationError({
                "detail": [f"{live.count()} allocation(s) were made from {instance.request_number}. Cancel them before deleting the request."],
            })
        with transaction.atomic():
            InputAllocationLine.objects.filter(request_line__batch=instance).update(request_line=None)
            InputAllocation.objects.filter(request_batch=instance).update(request_batch=None)
            BatchStockMovement.objects.filter(batch_input__batch=instance).delete()
            RequestBatchInput.objects.filter(batch=instance).delete()
            instance.delete()


class ARDAFarmerRequestViewSet(viewsets.ModelViewSet):
    queryset = ARDAFarmerRequest.objects.select_related("request_batch", "farmer", "farm").all()
    serializer_class = ARDAFarmerRequestSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
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
                if programme.announced_hectares > 0 and programme.total_allocated_hectares + approved_hectares > programme.announced_hectares:
                    return Response({"approved_hectares": ["Approval exceeds remaining programme capacity."]}, status=400)
                request_line.approved_hectares = approved_hectares
                request_line.status = ARDAFarmerRequest.STATUS_APPROVED
                request_line.save(update_fields=["approved_hectares", "status"])
                programme.total_allocated_hectares += approved_hectares
                programme.save(update_fields=["total_allocated_hectares", "updated_at"])
        except (InvalidOperation, ValueError):
            return Response({"approved_hectares": ["Enter a valid decimal amount."]}, status=400)
        return Response(self.get_serializer(request_line).data)
