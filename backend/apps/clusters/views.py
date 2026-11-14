from django.db.models import Count, Q
from rest_framework import viewsets

from apps.accounts.permissions import LocationReferencePermission

from .models import Cluster
from .serializers import ClusterSerializer


class ClusterViewSet(viewsets.ModelViewSet):
    """Read-only. A cluster is created, named and changed only through its lead farmer (/api/lead-farmers/)."""

    serializer_class = ClusterSerializer
    permission_classes = [LocationReferencePermission]
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        queryset = Cluster.objects.select_related(
            "province", "district", "lead_member", "lead_farmer"
        ).annotate(member_count=Count("farmers", distinct=True))
        user = self.request.user
        if user.is_authenticated and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER:
            queryset = queryset.filter(pk=user.assigned_cluster_id)

        province_id = self.request.query_params.get("province")
        district_id = self.request.query_params.get("district")
        if province_id and district_id:
            queryset = queryset.filter(province_id=province_id).filter(
                Q(district_id=district_id) | Q(district__isnull=True)
            )
        elif province_id:
            queryset = queryset.filter(province_id=province_id)
        elif district_id:
            queryset = queryset.filter(Q(district_id=district_id) | Q(district__isnull=True))

        active = self.request.query_params.get("active")
        include_inactive = self.request.query_params.get("include_inactive")
        if active in {"true", "false", "1", "0"}:
            queryset = queryset.filter(active=active in {"true", "1"})
        elif include_inactive not in {"1", "true", "yes"}:
            queryset = queryset.filter(active=True)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(lead_member__full_name__icontains=search)
                | Q(lead_member__national_id__icontains=search)
                | Q(province__name__icontains=search)
            )
        return queryset
