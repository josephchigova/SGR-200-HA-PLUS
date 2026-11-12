from rest_framework import permissions, viewsets

from apps.accounts.permissions import RecoveryWorkflowPermission
from apps.accounts.scoping import scope_by_farmer
from apps.programmes.period import filter_by_agricultural_year, filter_debts_by_crop_season, parse_crop_season

from .models import InputDebt, RecoveryRecord
from .serializers import InputDebtSerializer, RecoveryRecordSerializer


class RecoveryRecordViewSet(viewsets.ModelViewSet):
    queryset = RecoveryRecord.objects.select_related("farmer").all()
    serializer_class = RecoveryRecordSerializer
    permission_classes = [permissions.IsAuthenticated, RecoveryWorkflowPermission]

    def get_queryset(self):
        return scope_by_farmer(super().get_queryset(), self.request.user)


class InputDebtViewSet(viewsets.ModelViewSet):
    queryset = InputDebt.objects.select_related("input_allocation", "farmer", "farm", "province", "district", "programme").all()
    serializer_class = InputDebtSerializer
    permission_classes = [permissions.IsAuthenticated, RecoveryWorkflowPermission]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = scope_by_farmer(super().get_queryset(), self.request.user)
        season = self.request.query_params.get("season")
        season_name = self.request.query_params.get("season_name")
        queryset = filter_by_agricultural_year(queryset, season, season_name, relation="programme__season")
        crop_season = parse_crop_season(self.request.query_params.get("crop_season"))
        if crop_season:
            queryset = filter_debts_by_crop_season(queryset, crop_season)
        return queryset
