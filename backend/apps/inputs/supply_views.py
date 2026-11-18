"""HTTP API for lead-farmer input submissions and Admin hectare decisions."""

from django.db.models import Q
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import ProgrammePermission
from apps.programmes.period import parse_crop_season

from .models import InputSupplyRequest
from .supply import (
    SupplyError,
    approve,
    consolidated,
    options_for,
    present,
    reject,
    return_for_corrections,
    reverse,
    save_draft,
    set_hectares,
    submit,
)


class SupplyPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def _fail(error):
    raise ValidationError({"detail": str(error)}) from error


class InputSupplyPermission(permissions.BasePermission):
    """Lead farmers draft and submit. Administrators set hectare limits and confirm the distribution."""

    DECISIONS = {"approve", "reject", "return_for_corrections", "reverse", "set_hectares"}
    LEAD_ONLY = {"create", "destroy", "submit", "catalogue"}

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        writer = user.is_superuser or user.role in ProgrammePermission.allowed_roles
        auditor = user.role == User.ROLE_AUDITOR
        lead = user.role == User.ROLE_LEAD_FARMER
        action = getattr(view, "action", None)
        if action in self.DECISIONS:
            return writer
        if action == "consolidated":
            return writer or auditor
        if action in self.LEAD_ONLY:
            return lead
        if action in {"list", "retrieve"}:
            return lead or writer or auditor
        return False


def _supply_queryset():
    return InputSupplyRequest.objects.select_related(
        "lead_farmer", "programme", "season", "crop", "reviewed_by",
    ).prefetch_related(
        "farmers__farmer",
        "farmers__farm",
        "farmers__lines__requirement__input_product",
        "limits__requirement__input_product",
        "limits__updated_by",
        "events",
    )


class _ReadOnlySerializer(serializers.Serializer):
    """Responses are built in the supply service. This only satisfies the viewset contract."""


class InputSupplyRequestViewSet(viewsets.ModelViewSet):
    queryset = _supply_queryset()
    serializer_class = _ReadOnlySerializer
    permission_classes = [permissions.IsAuthenticated, InputSupplyPermission]
    pagination_class = SupplyPagination
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset()
        if user.role == User.ROLE_LEAD_FARMER:
            queryset = queryset.filter(lead_farmer=user)
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=str(params["status"]).strip().upper())
        if params.get("programme"):
            queryset = queryset.filter(programme_id=params["programme"])
        if params.get("season"):
            queryset = queryset.filter(season_id=params["season"])
        if params.get("crop"):
            queryset = queryset.filter(crop_id=params["crop"])
        if params.get("lead_farmer") and user.role != User.ROLE_LEAD_FARMER:
            queryset = queryset.filter(lead_farmer_id=params["lead_farmer"])
        crop_season = parse_crop_season(params.get("crop_season"))
        if crop_season:
            queryset = queryset.filter(crop__category=crop_season)
        term = (params.get("search") or "").strip()
        if term:
            queryset = queryset.filter(
                Q(reference__icontains=term)
                | Q(lead_farmer__first_name__icontains=term)
                | Q(lead_farmer__last_name__icontains=term)
                | Q(programme__name__icontains=term)
                | Q(crop__name__icontains=term)
            )
        return queryset

    def _loaded(self, pk):
        try:
            return self.get_queryset().get(pk=pk)
        except InputSupplyRequest.DoesNotExist as error:
            raise NotFound() from error

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response([present(row) for row in page])

    def retrieve(self, request, *args, **kwargs):
        return Response(present(self.get_object()))

    def create(self, request, *args, **kwargs):
        try:
            supply, created = save_draft(
                lead=request.user,
                programme_id=request.data.get("programme"),
                season_id=request.data.get("season"),
                crop_id=request.data.get("crop"),
                farmers=request.data.get("farmers") or [],
                crop_season=request.data.get("crop_season") or None,
            )
        except SupplyError as error:
            _fail(error)
        return Response(present(self._loaded(supply.pk)), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        supply = self.get_object()
        if supply.lead_farmer_id != request.user.id or supply.status != InputSupplyRequest.STATUS_DRAFT:
            _fail(SupplyError("Only a draft you own can be deleted."))
        supply.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _act(self, request, function, **extra):
        supply = self.get_object()
        try:
            updated = function(request_id=supply.pk, user=request.user, **extra)
        except SupplyError as error:
            _fail(error)
        except InputSupplyRequest.DoesNotExist as error:
            raise NotFound() from error
        return Response(present(self._loaded(updated.pk)))

    @action(detail=False, methods=["get"])
    def catalogue(self, request):
        season = request.query_params.get("season")
        if not season:
            _fail(SupplyError("Select the agricultural year."))
        try:
            payload = options_for(
                lead=request.user,
                season_id=season,
                crop_season=parse_crop_season(request.query_params.get("crop_season")),
            )
        except SupplyError as error:
            _fail(error)
        return Response(payload)

    @action(detail=False, methods=["get"])
    def consolidated(self, request):
        season = request.query_params.get("season")
        if not season:
            _fail(SupplyError("Select the agricultural year."))
        try:
            payload = consolidated(season_id=season, crop_season=parse_crop_season(request.query_params.get("crop_season")))
        except SupplyError as error:
            _fail(error)
        return Response(payload)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._act(request, submit)

    @action(detail=True, methods=["post"], url_path="set-hectares")
    def set_hectares(self, request, pk=None):
        return self._act(
            request,
            set_hectares,
            mode=request.data.get("mode"),
            limits=request.data.get("limits") or [],
            remarks=request.data.get("remarks") or "",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._act(request, approve, remarks=request.data.get("remarks") or "")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._act(request, reject, remarks=request.data.get("remarks") or "")

    @action(detail=True, methods=["post"], url_path="return-for-corrections")
    def return_for_corrections(self, request, pk=None):
        return self._act(request, return_for_corrections, remarks=request.data.get("remarks") or "")

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        return self._act(request, reverse, remarks=request.data.get("remarks") or "")
