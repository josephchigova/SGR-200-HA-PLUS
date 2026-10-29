from rest_framework import viewsets

from .models import Cluster
from .serializers import ClusterSerializer


class ClusterViewSet(viewsets.ModelViewSet):
    queryset = Cluster.objects.select_related("province", "district", "lead_farmer").filter(active=True)
    serializer_class = ClusterSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        province_id = self.request.query_params.get("province")
        district_id = self.request.query_params.get("district")
        if province_id:
            queryset = queryset.filter(province_id=province_id)
        if district_id:
            queryset = queryset.filter(district_id=district_id)
        return queryset
