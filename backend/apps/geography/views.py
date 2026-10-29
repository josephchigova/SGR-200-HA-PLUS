from rest_framework import viewsets

from apps.accounts.permissions import LocationReferencePermission

from .models import District, Province, Ward
from .serializers import DistrictSerializer, ProvinceSerializer, WardSerializer


class ProvinceViewSet(viewsets.ModelViewSet):
    queryset = Province.objects.all()
    serializer_class = ProvinceSerializer
    permission_classes = [LocationReferencePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("official") in {"1", "true", "True"}:
            queryset = queryset.filter(official=True, active=True)
        return queryset


class DistrictViewSet(viewsets.ModelViewSet):
    queryset = District.objects.select_related("province").filter(active=True)
    serializer_class = DistrictSerializer
    permission_classes = [LocationReferencePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        province_id = self.request.query_params.get("province")
        if province_id:
            queryset = queryset.filter(province_id=province_id)
        return queryset


class WardViewSet(viewsets.ModelViewSet):
    queryset = Ward.objects.select_related("district__province").filter(active=True)
    serializer_class = WardSerializer
    permission_classes = [LocationReferencePermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        district_id = self.request.query_params.get("district")
        if district_id:
            queryset = queryset.filter(district_id=district_id)
        return queryset
