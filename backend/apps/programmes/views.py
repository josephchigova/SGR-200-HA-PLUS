from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import ProgrammeWorkflowPermission

from .calendar import APRIL_CONVENTION, crop_season_for_date, crop_season_label, ensure_current_agricultural_year, today
from .models import Programme, ProgrammeAllocation, Season
from .period import filter_by_agricultural_year, filter_by_crop_name, parse_crop_season
from .serializers import ProgrammeAllocationSerializer, ProgrammeSerializer, SeasonSerializer


class ProgrammeViewSet(viewsets.ModelViewSet):
    queryset = Programme.objects.all()
    serializer_class = ProgrammeSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        from django.db.models import Q

        queryset = super().get_queryset().select_related("season").prefetch_related("programme_crops__crop")
        params = self.request.query_params
        season = params.get("season")
        season_name = params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(params.get("crop_season"))
        if crop_season:
            # A programme shows in a season when any crop it supports grows in that season.
            by_link = Q(programme_crops__active=True, programme_crops__crop__category=crop_season)
            legacy = filter_by_crop_name(queryset, crop_season, "crop").filter(programme_crops__isnull=True).values("pk")
            queryset = queryset.filter(by_link | Q(pk__in=legacy)).distinct()
        if params.get("crop"):
            queryset = queryset.filter(programme_crops__crop_id=params["crop"], programme_crops__active=True).distinct()
        status = (params.get("capacity_status") or "").upper()
        if status in {"ACTIVE", "INACTIVE"}:
            queryset = queryset.filter(is_active=status == "ACTIVE")
        if params.get("input_category"):
            category = params["input_category"].upper()
            queryset = queryset.filter(pk__in=[programme.pk for programme in queryset if category in (programme.input_categories or [])])
        if params.get("search"):
            queryset = queryset.filter(name__icontains=params["search"].strip())
        return queryset

    @action(detail=True, methods=["get"], url_path="figures")
    def figures(self, request, pk=None):
        from .figures import programme_figures

        return Response(programme_figures(self.get_object()))

    def perform_destroy(self, instance):
        from apps.finance.models import ExpenseClaim, JournalEntry, RecognizedReceipt, TradeReceivable
        from apps.recovery.models import InputDebt

        blockers = []
        if instance.request_batches.exists():
            blockers.append("ARDA requests")
        if instance.input_allocations.exists():
            blockers.append("input allocations")
        if instance.allocations.exists():
            blockers.append("programme allocations")
        if InputDebt.objects.filter(programme=instance).exists():
            blockers.append("recovery records")
        if JournalEntry.objects.filter(programme=instance).exists():
            blockers.append("journal entries")
        if RecognizedReceipt.objects.filter(programme=instance).exists():
            blockers.append("recognized receipts")
        if ExpenseClaim.objects.filter(programme=instance).exists():
            blockers.append("expense claims")
        if TradeReceivable.objects.filter(programme=instance).exists():
            blockers.append("receivables")
        if blockers:
            raise ValidationError({
                "detail": [
                    "This programme cannot be deleted because it is used by "
                    + ", ".join(blockers)
                    + ". Close or archive it instead."
                ],
            })
        instance.delete()


class SeasonViewSet(viewsets.ModelViewSet):
    queryset = Season.objects.all()
    serializer_class = SeasonSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        if season:
            queryset = queryset.filter(id=season) if season.isdigit() else queryset.filter(name__iexact=season)
        if season_name:
            queryset = queryset.filter(name__iexact=season_name)
        return queryset

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        on_date = today()
        season = ensure_current_agricultural_year(on_date)
        crop_season = crop_season_for_date(on_date)
        return Response(
            {
                "date": on_date.isoformat(),
                "agricultural_year": SeasonSerializer(season).data,
                "crop_season": crop_season,
                "crop_season_label": crop_season_label(crop_season),
                "april_convention": APRIL_CONVENTION,
            }
        )


class ProgrammeAllocationViewSet(viewsets.ModelViewSet):
    queryset = ProgrammeAllocation.objects.select_related("programme", "farmer").all()
    serializer_class = ProgrammeAllocationSerializer
    permission_classes = [permissions.IsAuthenticated, ProgrammeWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        # Programme allocations have no crop category, so only the agricultural year applies.
        return filter_by_agricultural_year(queryset, season, season_name, relation="programme__season")
