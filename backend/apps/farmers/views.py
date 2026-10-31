from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import filters, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import FarmerWorkflowPermission, ProgrammePermission
from apps.arda_requests.models import ARDARequestBatch
from apps.inputs.models import InputAllocation
from apps.production.models import FarmerProduction, GMBDelivery
from apps.recovery.models import InputDebt

from .models import Farmer, Farm, FarmerDocument
from .serializers import EligibleFarmerSerializer, FarmerDocumentSerializer, FarmerSerializer, FarmSerializer
from .services import FarmerApprovalEligibilityService


class FarmerSearchPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class FarmerViewSet(viewsets.ModelViewSet):
    queryset = Farmer.objects.select_related("province", "district", "ward", "verified_by").prefetch_related("farms").all()
    serializer_class = FarmerSerializer
    pagination_class = FarmerSearchPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "id", "first_name", "middle_name", "surname", "full_name", "national_id", "membership_number",
        "phone_primary", "phone_secondary", "email",
    ]
    ordering_fields = ["registration_date", "full_name", "verification_status", "membership_status"]
    ordering = ["-registration_date"]
    permission_classes = [permissions.IsAuthenticated, FarmerWorkflowPermission]
    eligible_search_fields = (
        "full_name",
        "first_name",
        "middle_name",
        "surname",
        "national_id",
        "membership_number",
        "phone_primary",
        "phone_secondary",
    )

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            pass
        elif user.role == user.ROLE_DISTRICT_COORDINATOR:
            queryset = queryset.filter(district_id=user.district_id)
        elif user.role == user.ROLE_PROVINCIAL_COORDINATOR:
            queryset = queryset.filter(province_id=user.province_id)
        elif user.role == user.ROLE_LEAD_FARMER:
            queryset = queryset.filter(cluster_id=user.assigned_cluster_id)
        province_id = self.request.query_params.get("province")
        district_id = self.request.query_params.get("district")
        ward_id = self.request.query_params.get("ward")
        verification_statuses = []
        for raw_value in self.request.query_params.getlist("verification_status"):
            verification_statuses.extend(
                [value.strip() for value in str(raw_value).split(",") if value.strip()]
            )
        membership_status = self.request.query_params.get("membership_status")
        if province_id:
            queryset = queryset.filter(province_id=province_id)
        if district_id:
            queryset = queryset.filter(district_id=district_id)
        if ward_id:
            queryset = queryset.filter(ward_id=ward_id)
        if verification_statuses:
            queryset = queryset.filter(verification_status__in=verification_statuses)
        if membership_status:
            queryset = queryset.filter(membership_status=membership_status)
        # Farmer identity is permanent and stays visible for every year and season.
        return queryset

    @action(
        detail=False,
        methods=["get"],
        url_path="eligible",
        permission_classes=[permissions.IsAuthenticated, ProgrammePermission],
    )
    def eligible(self, request):
        season = request.query_params.get("season")
        if season and season.isdecimal():
            from apps.programmes.models import Season

            season = Season.objects.filter(pk=int(season)).values_list("name", flat=True).first() or season
        elif not season:
            season = request.query_params.get("season_name")

        search_term = (request.query_params.get("search") or "").strip()
        eligible_farmers = FarmerApprovalEligibilityService.eligible_queryset_for_arda(self.get_queryset(), season)
        if search_term:
            search_filter = Q()
            for field in self.eligible_search_fields:
                search_filter |= Q(**{f"{field}__icontains": search_term})
            eligible_farmers = eligible_farmers.filter(search_filter)

        page = self.paginate_queryset(eligible_farmers)
        serializer = EligibleFarmerSerializer(page if page is not None else eligible_farmers, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="dashboard-summary", url_name="dashboard-summary")
    def dashboard_summary(self, request):
        from apps.programmes.period import (
            filter_allocations_by_crop_season,
            filter_by_agricultural_year,
            filter_by_crop_name,
            filter_debts_by_crop_season,
            parse_crop_season,
        )

        crop_season = parse_crop_season(request.query_params.get("crop_season"))
        season = request.query_params.get("season")
        season_name = request.query_params.get("season_name")
        queryset = self.get_queryset()
        accessible_farmers = queryset.values("id")
        summary = {
            "registered_farmers": queryset.count(),
            "verified_farmers": queryset.filter(verification_status=Farmer.STATUS_VERIFIED).count(),
            "pending_verifications": queryset.filter(verification_status__in=[Farmer.STATUS_SUBMITTED, Farmer.STATUS_UNDER_REVIEW]).count(),
            "rejected_farmers": queryset.filter(verification_status=Farmer.STATUS_REJECTED).count(),
            "active_memberships": queryset.filter(membership_status=Farmer.MEMBERSHIP_ACTIVE).count(),
            "total_hectares": Farm.objects.filter(farmer_id__in=accessible_farmers).aggregate(total=Sum("total_hectares"))["total"] or 0,
        }

        # Requested hectares come from the saved request batch. A batch with no farmer
        # lines is still a request. Recording a request means ARDA has already approved it,
        # so the dashboard does not keep a second approval total.
        request_batches = ARDARequestBatch.objects.exclude(status=ARDARequestBatch.STATUS_REJECTED)
        request_batches = filter_by_agricultural_year(request_batches, season, season_name, relation="season")
        if crop_season:
            request_batches = filter_by_crop_name(request_batches, crop_season, "crop")
        allocations = InputAllocation.objects.exclude(status=InputAllocation.STATUS_CANCELLED).filter(farmer_id__in=accessible_farmers)
        allocations = filter_by_agricultural_year(allocations, season, season_name, relation="programme__season")
        if crop_season:
            allocations = filter_allocations_by_crop_season(allocations, crop_season)
        productions = FarmerProduction.objects.filter(farmer_id__in=accessible_farmers)
        productions = filter_by_agricultural_year(productions, season, season_name, relation="season")
        if crop_season:
            productions = filter_by_crop_name(productions, crop_season, "crop")
        deliveries = GMBDelivery.objects.filter(farmer_id__in=accessible_farmers)
        deliveries = filter_by_agricultural_year(deliveries, season, season_name, relation="season")
        if crop_season:
            deliveries = filter_by_crop_name(deliveries, crop_season, "crop")
        debts = InputDebt.objects.filter(farmer_id__in=accessible_farmers)
        debts = filter_by_agricultural_year(debts, season, season_name, relation="programme__season")
        if crop_season:
            debts = filter_debts_by_crop_season(debts, crop_season)

        summary.update(
            {
                "arda_requested_hectares": request_batches.aggregate(total=Sum("requested_hectares"))["total"] or 0,
                "arda_request_count": request_batches.count(),
                "input_allocated_hectares": allocations.aggregate(total=Sum("hectares"))["total"] or 0,
                "production": productions.aggregate(total=Sum("actual_production"))["total"] or 0,
                "grain_delivered_tonnes": deliveries.aggregate(total=Sum("tonnes"))["total"] or 0,
                "outstanding_recovery_tonnes": debts.aggregate(total=Sum("outstanding_tonnes"))["total"] or 0,
            }
        )
        required_recovery = debts.aggregate(total=Sum("required_recovery_tonnes"))["total"] or 0
        recovered = debts.aggregate(total=Sum("recovered_tonnes"))["total"] or 0
        summary["recovery_percentage"] = round(float(recovered / required_recovery * 100), 2) if required_recovery else 0
        from apps.farmers.dashboard_charts import build_dashboard_charts
        from apps.programmes.models import Season

        season_record = Season.objects.filter(pk=season).first() if str(season or "").isdigit() else None
        summary["charts"] = build_dashboard_charts(
            farmers=queryset,
            season_name=season_name or getattr(season_record, "name", ""),
            season_start=getattr(season_record, "start_date", None),
            season_end=getattr(season_record, "end_date", None),
            allocations=allocations,
            productions=productions,
            deliveries=deliveries,
            debts=debts,
            requested=summary["arda_requested_hectares"],
            allocated=summary["input_allocated_hectares"],
        )
        return Response(summary)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        farmer = self.get_object()
        verification_status = request.data.get("verification_status")

        valid_statuses = {code for code, _ in Farmer.VERIFICATION_CHOICES}
        if verification_status not in valid_statuses:
            return Response({"verification_status": ["Select a valid verification status."]}, status=400)

        rejection_reason = request.data.get("rejection_reason", "").strip()
        if verification_status == Farmer.STATUS_REJECTED and not rejection_reason:
            return Response({"rejection_reason": ["A rejection reason is required."]}, status=400)

        farmer.verification_status = verification_status
        farmer.verified_by = request.user
        farmer.verification_date = timezone.now()
        farmer.rejection_reason = rejection_reason if verification_status == Farmer.STATUS_REJECTED else ""
        farmer.save(update_fields=["verification_status", "verified_by", "verification_date", "rejection_reason", "updated_at"])
        if verification_status == Farmer.STATUS_VERIFIED:
            farmer.farms.update(
                verification_status="VERIFIED",
                verified_by=request.user,
                verification_date=timezone.now(),
            )

        serializer = self.get_serializer(farmer)
        return Response(serializer.data)


class FarmViewSet(viewsets.ModelViewSet):
    queryset = Farm.objects.select_related("farmer", "province", "district", "ward", "cluster", "verified_by").all()
    serializer_class = FarmSerializer
    permission_classes = [permissions.IsAuthenticated, FarmerWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            pass
        elif user.role == user.ROLE_DISTRICT_COORDINATOR:
            queryset = queryset.filter(district_id=user.district_id)
        elif user.role == user.ROLE_PROVINCIAL_COORDINATOR:
            queryset = queryset.filter(province_id=user.province_id)
        elif user.role == user.ROLE_LEAD_FARMER:
            queryset = queryset.filter(farmer__cluster_id=user.assigned_cluster_id)
        farmer_id = self.request.query_params.get("farmer")
        if farmer_id:
            queryset = queryset.filter(farmer_id=farmer_id)
        if self.request.query_params.get("include_inactive") != "1":
            queryset = queryset.filter(is_active=True)
        return queryset


class FarmerDocumentViewSet(viewsets.ModelViewSet):
    queryset = FarmerDocument.objects.select_related("farmer", "farm", "uploaded_by", "verified_by").all()
    serializer_class = FarmerDocumentSerializer
    permission_classes = [permissions.IsAuthenticated, FarmerWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return queryset
        if user.role == user.ROLE_DISTRICT_COORDINATOR:
            return queryset.filter(Q(farmer__district_id=user.district_id) | Q(farmer__isnull=True, farm__district_id=user.district_id))
        if user.role == user.ROLE_PROVINCIAL_COORDINATOR:
            return queryset.filter(Q(farmer__province_id=user.province_id) | Q(farmer__isnull=True, farm__province_id=user.province_id))
        if user.role == user.ROLE_LEAD_FARMER:
            return queryset.filter(farmer__cluster_id=user.assigned_cluster_id)
        return queryset
