from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import ProgrammeWorkflowPermission
from apps.accounts.scoping import scope_by_farmer
from apps.programmes.period import filter_by_agricultural_year, filter_by_crop_name, parse_crop_season

from apps.accounts.roles import can

from .models import ARDAFarmerRequest, ARDARequest, ARDARequestBatch
from .serializers import ARDAFarmerRequestSerializer, ARDARequestBatchSerializer, ARDARequestSerializer
from .services import RequestWorkflowError, approve_request, reject_request, submit_request


class ARDARequestViewSet(viewsets.ModelViewSet):
    queryset = ARDARequest.objects.select_related("farmer").all()
    serializer_class = ARDARequestSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        return scope_by_farmer(super().get_queryset(), self.request.user)


class ARDARequestBatchViewSet(viewsets.ModelViewSet):
    queryset = ARDARequestBatch.objects.select_related("programme", "season", "approved_by", "created_by").all()
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

    def _decide(self, request, change, action_name="approve"):
        if not can(request.user, "arda", action_name):
            return Response({"detail": "You do not have permission to do this."}, status=403)
        batch = self.get_object()
        try:
            batch = change(batch)
        except RequestWorkflowError as error:
            return Response({"detail": str(error)}, status=400)
        return Response(self.get_serializer(batch).data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        return self._decide(request, lambda batch: submit_request(batch, user=request.user), "create")

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decide(request, lambda batch: approve_request(
            batch, hectares=request.data.get("approved_hectares"), notes=request.data.get("notes", ""), user=request.user,
        ))

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, lambda batch: reject_request(batch, notes=request.data.get("notes", ""), user=request.user))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_destroy(self, instance):
        from apps.programmes.models import Season

        season = instance.season
        if season is None or season.status != Season.STATUS_ACTIVE:
            raise ValidationError({"non_field_errors": ["Past-season ARDA requests are read-only and cannot be modified."]})
        if instance.farmer_requests.exists():
            raise ValidationError({
                "detail": ["This request has farmer lines. Reject it instead of deleting the history."],
            })
        from .services import batch_allocations

        if batch_allocations(instance).exists():
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
