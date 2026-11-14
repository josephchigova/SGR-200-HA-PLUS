from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import filters, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.accounts.permissions import FarmerWorkflowPermission, ProgrammePermission
from apps.accounts.scoping import is_scoped, scope_by_farmer, scope_farmers
from apps.arda_requests.models import ARDARequestBatch
from apps.inputs.models import InputAllocation
from apps.production.models import FarmerProduction, GMBDelivery
from apps.recovery.models import InputDebt

from . import kyc
from .models import Farmer, Farm, FarmerDocument, FarmerReviewEvent
from .serializers import EligibleFarmerSerializer, FarmerDocumentSerializer, FarmerSerializer, FarmSerializer
from .services import FarmerApprovalEligibilityService


def _truthy(value):
    return str(value).lower() in {"1", "true", "yes"}


def _registers_leads(user):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.role in {
        user.ROLE_SUPER_ADMIN, user.ROLE_SGR_EXECUTIVE, user.ROLE_MEMBERSHIP_OFFICER,
    }


def _may_register(request):
    """Lead farmers register members. Administrators register lead farmers only."""
    user = request.user
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.role == user.ROLE_SUPER_ADMIN:
        return True
    if _truthy(request.data.get("as_lead")):
        return user.role in {user.ROLE_SGR_EXECUTIVE, user.ROLE_MEMBERSHIP_OFFICER}
    if user.role == user.ROLE_LEAD_FARMER:
        return True
    # A verification officer can still capture a record while checking the register.
    return user.role == user.ROLE_VERIFICATION_OFFICER


class FarmerSearchPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class FarmerViewSet(viewsets.ModelViewSet):
    queryset = Farmer.objects.select_related(
        "province", "district", "ward", "cluster", "cluster__lead_member", "cluster__lead_farmer", "verified_by", "registered_by",
    ).prefetch_related("farms", "documents", "crop_allocations__crop", "crop_allocations__season").all()
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
    restrict_delete = True
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
        queryset = scope_farmers(queryset, self.request.user)
        province_id = self.request.query_params.get("province")
        district_id = self.request.query_params.get("district")
        ward_id = self.request.query_params.get("ward")
        cluster_id = self.request.query_params.get("cluster")
        unassigned = self.request.query_params.get("unassigned")
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
        if cluster_id:
            queryset = queryset.filter(cluster_id=cluster_id)
        lead_member = (self.request.query_params.get("lead_member") or "").strip()
        if lead_member == "none":
            queryset = queryset.filter(
                Q(cluster__isnull=True) | Q(cluster__lead_member__isnull=True, cluster__lead_farmer__isnull=True)
            )
        elif lead_member.isdecimal():
            queryset = queryset.filter(cluster__lead_member_id=lead_member)
        if unassigned in {"1", "true", "yes"}:
            queryset = queryset.filter(cluster__isnull=True)
        if verification_statuses:
            queryset = queryset.filter(verification_status__in=verification_statuses)
        if membership_status:
            queryset = queryset.filter(membership_status=membership_status)
        if self.request.query_params.get("submitted_only") in {"1", "true"}:
            # The approval queue leaves out registrations a lead farmer has not finished yet.
            queryset = queryset.exclude(verification_status=Farmer.STATUS_DRAFT, registered_by__isnull=False)
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
        if is_scoped(request.user):
            # Request batches are organisation-wide, so a scoped user gets no total.
            request_batches = request_batches.none()
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
            restrict_to_farmers=is_scoped(request.user),
        )
        from apps.accounts.roles import can

        summary["scope"] = _dashboard_scope(request.user)
        if not can(request.user, "finance"):
            # Organisation spending belongs to the finance roles only.
            summary["charts"].pop("expenses_by_category", None)
            summary["charts"].pop("expenses_by_month", None)
        from apps.accounts.privacy import hides_money

        if hides_money(request.user):
            # A lead farmer sees how many farmers have paid, never how much.
            for key in ("receivables", "subscription_receipts", "subscription_receipts_undated"):
                summary["charts"].pop(key, None)
            summary["charts"]["recent"] = [row for row in summary["charts"].get("recent", []) if row.get("kind") != "Subscription payment"]
        return Response(summary)

    @action(detail=True, methods=["post"], url_path="verify")
    def verify(self, request, pk=None):
        """The reviewer's decision: approve, reject, or send back for corrections."""
        farmer = self.get_object()
        verification_status = request.data.get("verification_status")

        valid_statuses = {code for code, _ in Farmer.VERIFICATION_CHOICES}
        if verification_status not in valid_statuses:
            return Response({"verification_status": ["Select a valid verification status."]}, status=400)

        remarks = str(request.data.get("remarks") or request.data.get("rejection_reason") or "").strip()
        if verification_status == Farmer.STATUS_REJECTED and not remarks:
            return Response({"rejection_reason": ["A rejection reason is required."]}, status=400)
        if verification_status == Farmer.STATUS_CORRECTIONS and not remarks:
            return Response({"remarks": ["Say what must be corrected."]}, status=400)
        if verification_status in kyc.APPROVED_STATES:
            # A draft from the registration wizard still lacks its documents.
            if farmer.verification_status == Farmer.STATUS_DRAFT and farmer.registered_by_id:
                return Response({"detail": "This registration has not been submitted yet."}, status=400)
            pending = kyc.unverified_documents(farmer)
            if pending:
                return Response({"detail": "Verify every uploaded document before approving. Still to check: " + ", ".join(pending) + "."}, status=400)

        farmer.verification_status = verification_status
        farmer.verified_by = request.user
        farmer.verification_date = timezone.now()
        farmer.rejection_reason = remarks if verification_status == Farmer.STATUS_REJECTED else ""
        farmer.review_remarks = remarks
        if verification_status in kyc.APPROVED_STATES:
            # Only an approved registration becomes an active member.
            farmer.membership_status = Farmer.MEMBERSHIP_ACTIVE
            from .services import publish_registration_crops

            publish_registration_crops(farmer)
        elif verification_status in {Farmer.STATUS_REJECTED, Farmer.STATUS_CORRECTIONS}:
            farmer.membership_status = Farmer.MEMBERSHIP_INACTIVE
        farmer.save(update_fields=["verification_status", "verified_by", "verification_date", "rejection_reason", "review_remarks", "membership_status", "updated_at"])
        if verification_status == Farmer.STATUS_VERIFIED:
            farmer.farms.update(
                verification_status="VERIFIED",
                verified_by=request.user,
                verification_date=timezone.now(),
            )
        event = {
            Farmer.STATUS_VERIFIED: FarmerReviewEvent.APPROVED,
            Farmer.STATUS_APPROVED: FarmerReviewEvent.APPROVED,
            Farmer.STATUS_REJECTED: FarmerReviewEvent.REJECTED,
            Farmer.STATUS_CORRECTIONS: FarmerReviewEvent.CORRECTIONS,
        }.get(verification_status)
        if event:
            kyc.record_event(farmer, event, request.user, remarks)

        serializer = self.get_serializer(farmer)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        """Send a draft or corrected registration to the approval queue."""
        farmer = self.get_object()
        if farmer.verification_status not in kyc.EDITABLE_BY_REGISTRAR:
            return Response({"detail": "This registration is already with the administrator."}, status=400)
        missing = kyc.missing_required_documents(farmer)
        if missing:
            return Response({"detail": "Upload the required documents first: " + ", ".join(missing) + "."}, status=400)
        if not farmer.farms.exists():
            return Response({"detail": "Add the farm details before submitting."}, status=400)
        kyc.submit_registration(farmer, request.user)
        return Response(self.get_serializer(farmer).data)

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        farmer = self.get_object()
        return Response([
            {
                "id": event.id,
                "action": event.action,
                "label": event.get_action_display(),
                "remarks": event.remarks,
                "actor": event.actor_name or "System",
                "created_at": event.created_at,
            }
            for event in farmer.review_events.all()[:100]
        ])

    def create(self, request, *args, **kwargs):
        if not _may_register(request):
            return Response(
                {"detail": "Administrators register lead farmers. A lead farmer registers the farmers in their own cluster."},
                status=403,
            )
        return super().create(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="registration-context")
    def registration_context(self, request):
        """Where this user may register farmers. A lead farmer is fixed to the assigned cluster."""
        user = request.user
        data = {"locked": False, "cluster": None, "province": None, "district": None, "documents": kyc.DOCUMENT_TYPES,
                "max_upload_mb": kyc.MAX_UPLOAD_BYTES // (1024 * 1024), "national_id_pattern": kyc.NATIONAL_ID_PATTERN.pattern,
                "registers": "lead" if _registers_leads(request.user) and request.user.role != request.user.ROLE_LEAD_FARMER else "farmer"}
        if not user.is_superuser and user.role == user.ROLE_LEAD_FARMER:
            cluster = user.assigned_cluster
            data["locked"] = True
            if cluster is not None:
                data["cluster"] = {"id": cluster.id, "name": cluster.name}
                data["province"] = {"id": cluster.province_id, "name": cluster.province.name}
                if cluster.district_id:
                    data["district"] = {"id": cluster.district_id, "name": cluster.district.name}
        return Response(data)

    @action(detail=False, methods=["get"], url_path="cluster-overview")
    def cluster_overview(self, request):
        from .cluster_overview import build_cluster_overview

        queryset = scope_farmers(Farmer.objects.all(), request.user)
        cluster_id = request.query_params.get("cluster")
        if cluster_id and str(cluster_id).isdigit():
            queryset = queryset.filter(cluster_id=int(cluster_id))
        season_name = request.query_params.get("season_name") or ""
        return Response(build_cluster_overview(queryset, request.user, season_name))

    @action(detail=False, methods=["get"], url_path="cluster-performance")
    def cluster_performance(self, request):
        from .performance import build_cluster_performance

        queryset = scope_farmers(Farmer.objects.all(), request.user)
        return Response(build_cluster_performance(queryset, request))


class FarmViewSet(viewsets.ModelViewSet):
    queryset = Farm.objects.select_related("farmer", "province", "district", "ward", "cluster", "verified_by").all()
    serializer_class = FarmSerializer
    permission_classes = [permissions.IsAuthenticated, FarmerWorkflowPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = scope_by_farmer(queryset, self.request.user)
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
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        farmer_id = self.request.query_params.get("farmer")
        if farmer_id and str(farmer_id).isdigit():
            queryset = queryset.filter(farmer_id=int(farmer_id))
        user = self.request.user
        if user.is_superuser:
            return queryset
        if user.role == user.ROLE_DISTRICT_COORDINATOR:
            return queryset.filter(Q(farmer__district_id=user.district_id) | Q(farmer__isnull=True, farm__district_id=user.district_id))
        if user.role == user.ROLE_PROVINCIAL_COORDINATOR:
            return queryset.filter(Q(farmer__province_id=user.province_id) | Q(farmer__isnull=True, farm__province_id=user.province_id))
        if user.role == user.ROLE_LEAD_FARMER:
            if not user.assigned_cluster_id:
                return queryset.none()
            return queryset.filter(farmer__cluster_id=user.assigned_cluster_id)
        return queryset

    def perform_create(self, serializer):
        farmer = serializer.validated_data.get("farmer")
        document_type = serializer.validated_data.get("document_type")
        upload = serializer.validated_data.get("file")
        # A new upload of the same document replaces the earlier copy.
        replaced = list(FarmerDocument.objects.filter(farmer=farmer, document_type=document_type)) if farmer else []
        document = serializer.save(uploaded_by=self.request.user, original_name=(getattr(upload, "name", "") or "")[:255],
                                   verified=False, verified_by=None, review_status=FarmerDocument.REVIEW_PENDING)
        for old in replaced:
            old.file.delete(save=False)
            old.delete()
        if farmer:
            kyc.record_event(farmer, FarmerReviewEvent.DOCUMENT_UPLOADED, self.request.user, kyc.DOCUMENT_LABELS.get(document.document_type, document.document_type))

    def perform_destroy(self, instance):
        instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Documents are only served here, to a signed-in user allowed to see the farmer."""
        import mimetypes

        from django.http import FileResponse, Http404

        document = self.get_object()
        try:
            handle = document.file.open("rb")
        except (FileNotFoundError, ValueError) as error:
            raise Http404("The file is no longer stored.") from error
        name = document.original_name or document.file.name.rsplit("/", 1)[-1]
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        response = FileResponse(handle, content_type=content_type)
        disposition = "attachment" if request.query_params.get("save") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{name.replace(chr(34), "")}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        document = self.get_object()
        decision = request.data.get("review_status")
        remarks = str(request.data.get("remarks") or "").strip()
        if decision not in {FarmerDocument.REVIEW_VERIFIED, FarmerDocument.REVIEW_REJECTED, FarmerDocument.REVIEW_PENDING}:
            return Response({"review_status": ["Choose verified or rejected."]}, status=400)
        if decision == FarmerDocument.REVIEW_REJECTED and not remarks:
            return Response({"remarks": ["Say why the document is rejected."]}, status=400)
        document.review_status = decision
        document.review_remarks = remarks[:255]
        document.verified = decision == FarmerDocument.REVIEW_VERIFIED
        document.verified_by = request.user
        document.reviewed_at = timezone.now()
        document.save(update_fields=["review_status", "review_remarks", "verified", "verified_by", "reviewed_at"])
        if document.farmer_id and decision != FarmerDocument.REVIEW_PENDING:
            label = kyc.DOCUMENT_LABELS.get(document.document_type, document.document_type)
            kyc.record_event(
                document.farmer,
                FarmerReviewEvent.DOCUMENT_VERIFIED if document.verified else FarmerReviewEvent.DOCUMENT_REJECTED,
                request.user,
                f"{label}{': ' + remarks if remarks else ''}",
            )
        return Response(self.get_serializer(document).data)


def _dashboard_scope(user):
    if user.is_superuser:
        return {"kind": "all", "label": "All farmers"}
    if user.role == user.ROLE_LEAD_FARMER:
        return {"kind": "cluster", "label": getattr(user.assigned_cluster, "name", "") or "No cluster assigned"}
    if user.role == user.ROLE_DISTRICT_COORDINATOR:
        return {"kind": "district", "label": getattr(user.district, "name", "") or "No district assigned"}
    if user.role == user.ROLE_PROVINCIAL_COORDINATOR:
        return {"kind": "province", "label": getattr(user.province, "name", "") or "No province assigned"}
    return {"kind": "all", "label": "All farmers"}
