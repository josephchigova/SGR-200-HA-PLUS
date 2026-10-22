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
        queryset = super().get_queryset()
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_by_crop_name(queryset, crop_season, "crop")
        return queryset

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
