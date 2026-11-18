"""HTTP API for lead-farmer input allocations and Admin's input approvals."""

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
    SupplyConflict,
    SupplyError,
    add_allocation,
    approve,
    consolidated,
    delete_allocation,
    options_for,
    present,
    programme_progress,
    redistribute,
    reject,
    return_for_corrections,
    reverse,
    set_hectares,
    submit,
    supply_queryset,
    update_allocation,
)


class SupplyPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


class InputSupplyPermission(permissions.BasePermission):
    """Lead farmers allocate and submit. Administrators issue limits and give the final approval."""

    DECISIONS = {"approve", "reject", "return_for_corrections", "reverse", "set_hectares"}
    LEAD_ONLY = {"allocations", "allocation", "submit", "catalogue", "destroy", "redistribute"}

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        writer = user.is_superuser or user.role in ProgrammePermission.allowed_roles
        auditor = user.role == User.ROLE_AUDITOR
        lead = user.role == User.ROLE_LEAD_FARMER
        name = getattr(view, "action", None)
        if name in self.DECISIONS:
            return writer
        if name in {"consolidated", "progress"}:
            return writer or auditor
        if name in self.LEAD_ONLY:
            return lead
        if name in {"list", "retrieve"}:
            return lead or writer or auditor
        return False


class _ReadOnlySerializer(serializers.Serializer):
    """Responses are built in the supply service. This only satisfies the viewset contract."""


class InputSupplyRequestViewSet(viewsets.ModelViewSet):
    serializer_class = _ReadOnlySerializer
    permission_classes = [permissions.IsAuthenticated, InputSupplyPermission]
    pagination_class = SupplyPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = supply_queryset()
        if user.role == User.ROLE_LEAD_FARMER:
            queryset = queryset.filter(lead_farmer=user)
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=[part.strip().upper() for part in params["status"].split(",") if part.strip()])
        for name, field in (("programme", "programme_id"), ("season", "season_id")):
            if str(params.get(name) or "").isdigit():
                queryset = queryset.filter(**{field: params[name]})
        if str(params.get("lead_farmer") or "").isdigit() and user.role != User.ROLE_LEAD_FARMER:
            queryset = queryset.filter(lead_farmer_id=params["lead_farmer"])
        crop_season = parse_crop_season(params.get("crop_season"))
        if crop_season:
            queryset = queryset.filter(Q(crop_season=crop_season) | Q(crop__category=crop_season))
        term = (params.get("search") or "").strip()
        if term:
            queryset = queryset.filter(
                Q(reference__icontains=term) | Q(lead_farmer__first_name__icontains=term) | Q(lead_farmer__last_name__icontains=term)
                | Q(programme__name__icontains=term)
            )
        return queryset.order_by("-updated_at", "-id")

    def _fresh(self, pk):
        """The submission as saved, read back from the database."""
        try:
            return present(self.get_queryset().get(pk=pk))
        except InputSupplyRequest.DoesNotExist as error:
            raise NotFound() from error

    def _error(self, error):
        if isinstance(error, SupplyConflict):
            return Response({"detail": str(error), "conflict": True}, status=status.HTTP_409_CONFLICT)
        raise ValidationError({"detail": str(error)}) from error

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response([present(row) for row in page])

    def retrieve(self, request, *args, **kwargs):
        return Response(present(self.get_object()))

    def create(self, request, *args, **kwargs):
        raise ValidationError({"detail": "Add allocations one at a time with /input-supply-requests/allocations/."})

    def destroy(self, request, *args, **kwargs):
        supply = self.get_object()
        if supply.lead_farmer_id != request.user.id or supply.status != InputSupplyRequest.STATUS_DRAFT:
            raise ValidationError({"detail": "Only a draft you own can be deleted."})
        supply.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def catalogue(self, request):
        try:
            return Response(options_for(lead=request.user, season_id=request.query_params.get("season"), crop_season=request.query_params.get("crop_season")))
        except SupplyError as error:
            return self._error(error)

    @action(detail=False, methods=["get"])
    def progress(self, request):
        """A programme's requested, approved, distributed and finally approved hectares, by lead farmer."""
        params = request.query_params
        try:
            return Response(programme_progress(
                programme_id=params.get("programme"), crop_season=parse_crop_season(params.get("crop_season")),
                crop_id=params.get("crop"), category=params.get("input_category"),
                requirement_id=params.get("requirement"), lead_id=params.get("lead_farmer"),
            ))
        except SupplyError as error:
            return self._error(error)

    @action(detail=True, methods=["post"])
    def redistribute(self, request, pk=None):
        """Save new hectares for several of the submission's allocations together."""
        try:
            supply = redistribute(user=request.user, request_id=pk, changes=request.data.get("changes"))
        except SupplyError as error:
            return self._error(error)
        return Response(self._fresh(supply.pk))

    @action(detail=False, methods=["get"])
    def consolidated(self, request):
        season = request.query_params.get("season")
        if not str(season or "").isdigit():
            raise ValidationError({"detail": "Select the agricultural year."})
        return Response(consolidated(
            season_id=season, crop_season=parse_crop_season(request.query_params.get("crop_season")),
            programme_id=request.query_params.get("programme") if str(request.query_params.get("programme") or "").isdigit() else None,
        ))

    @action(detail=False, methods=["post"])
    def allocations(self, request):
        """Add one farmer's crop allocation. Returns the whole submission as saved."""
        data = request.data
        try:
            supply, _entry = add_allocation(
                user=request.user, programme_id=data.get("programme"), season_id=data.get("season"), crop_season=data.get("crop_season"),
                farmer_id=data.get("farmer"), crop_id=data.get("crop"), lines=data.get("lines"), farm_id=data.get("farm") or None,
                request_id=data.get("submission") or None,
            )
        except SupplyError as error:
            return self._error(error)
        return Response(self._fresh(supply.pk), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["patch", "delete"], url_path=r"allocations/(?P<entry_id>[0-9]+)")
    def allocation(self, request, entry_id=None):
        """Change or remove one allocation. The version must match what the screen loaded."""
        try:
            if request.method == "DELETE":
                version = request.query_params.get("version") or request.data.get("version")
                supply = delete_allocation(user=request.user, entry_id=entry_id, version=version)
                if supply is None:
                    return Response({"deleted": True, "submission": None})
                return Response({"deleted": True, "submission": self._fresh(supply.pk)})
            supply, _entry = update_allocation(
                user=request.user, entry_id=entry_id, lines=request.data.get("lines"), version=request.data.get("version"),
                farm_id=request.data.get("farm") or None,
            )
        except SupplyError as error:
            return self._error(error)
        return Response(self._fresh(supply.pk))

    def _act(self, request, function, **extra):
        supply = self.get_object()
        try:
            updated = function(request_id=supply.pk, user=request.user, **extra)
        except SupplyError as error:
            return self._error(error)
        return Response(self._fresh(updated.pk))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._act(request, submit)

    @action(detail=True, methods=["post"], url_path="set-hectares")
    def set_hectares(self, request, pk=None):
        return self._act(request, set_hectares, mode=request.data.get("mode"), limits=request.data.get("limits") or [], remarks=request.data.get("remarks") or "")

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
