"""Lead farmer management.

A lead farmer is the cluster. Registering a lead farmer creates three things at once:
their record on the farmer register, the cluster named after them, and their login.
There is no other way to create a cluster.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import LeadFarmerPermission
from apps.accounts.serializers import check_password_strength
from apps.farmers import kyc
from apps.farmers.kyc import NATIONAL_ID_PATTERN, record_event
from apps.farmers.models import Farmer, FarmerReviewEvent
from apps.farmers.services import (
    duplicate_message,
    find_registered_farmer,
    open_lead_cluster,
    reassign_farmer,
    sync_cluster_name,
)
from apps.geography.models import District, Province, Ward

from .models import Cluster

User = get_user_model()
NAME_PATTERN = r"^[^\W\d_]+(?:[ '-][^\W\d_]+)*$"


def _clean_name(value):
    return " ".join(str(value or "").upper().split())


class _LocationMixin:
    def _check_location(self, attrs, instance=None):
        province = attrs.get("province", getattr(instance, "province", None))
        district = attrs.get("district", getattr(instance, "district", None))
        ward = attrs.get("ward", getattr(instance, "ward", None))
        if district is not None and province is not None and district.province_id != province.pk:
            raise serializers.ValidationError({"district": ["District does not belong to the selected province."]})
        if ward is not None and district is not None and ward.district_id != district.pk:
            raise serializers.ValidationError({"ward": ["Ward does not belong to the selected district."]})


class LeadFarmerCreateSerializer(_LocationMixin, serializers.Serializer):
    first_name = serializers.RegexField(NAME_PATTERN, max_length=100, error_messages={"invalid": "Use letters, spaces, apostrophes or hyphens only."})
    middle_name = serializers.RegexField(NAME_PATTERN, max_length=100, required=False, allow_blank=True, error_messages={"invalid": "Use letters, spaces, apostrophes or hyphens only."})
    surname = serializers.RegexField(NAME_PATTERN, max_length=120, error_messages={"invalid": "Use letters, spaces, apostrophes or hyphens only."})
    national_id = serializers.CharField(max_length=30)
    phone_primary = serializers.RegexField(r"^\d{9,12}$", error_messages={"invalid": "Enter 9 to 12 digits."})
    email = serializers.EmailField()
    province = serializers.PrimaryKeyRelatedField(queryset=Province.objects.filter(active=True))
    district = serializers.PrimaryKeyRelatedField(queryset=District.objects.filter(active=True))
    ward = serializers.PrimaryKeyRelatedField(queryset=Ward.objects.filter(active=True))
    password = serializers.CharField(min_length=8, write_only=True)

    def validate_national_id(self, value):
        value = value.strip().upper()
        if not NATIONAL_ID_PATTERN.fullmatch(value):
            raise serializers.ValidationError("Enter the national ID as 63-2330173E58.")
        existing = find_registered_farmer(value)
        if existing is not None:
            raise serializers.ValidationError(duplicate_message(existing))
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        return check_password_strength(value)

    def validate(self, attrs):
        self._check_location(attrs)
        for field in ("first_name", "middle_name", "surname"):
            attrs[field] = _clean_name(attrs.get(field))
        return attrs


class LeadFarmerUpdateSerializer(_LocationMixin, serializers.Serializer):
    first_name = serializers.RegexField(NAME_PATTERN, max_length=100, required=False)
    middle_name = serializers.RegexField(NAME_PATTERN, max_length=100, required=False, allow_blank=True)
    surname = serializers.RegexField(NAME_PATTERN, max_length=120, required=False)
    phone_primary = serializers.RegexField(r"^\d{9,12}$", required=False, error_messages={"invalid": "Enter 9 to 12 digits."})
    email = serializers.EmailField(required=False)
    province = serializers.PrimaryKeyRelatedField(queryset=Province.objects.filter(active=True), required=False)
    district = serializers.PrimaryKeyRelatedField(queryset=District.objects.filter(active=True), required=False)
    ward = serializers.PrimaryKeyRelatedField(queryset=Ward.objects.filter(active=True), required=False)

    def validate(self, attrs):
        lead = self.context["lead"]
        self._check_location(attrs, lead)
        for field in ("first_name", "middle_name", "surname"):
            if field in attrs:
                attrs[field] = _clean_name(attrs[field])
        if "email" in attrs:
            attrs["email"] = attrs["email"].strip().lower()
            taken = User.objects.filter(email__iexact=attrs["email"])
            account = self.context.get("account")
            if account is not None:
                taken = taken.exclude(pk=account.pk)
            if taken.exists():
                raise serializers.ValidationError({"email": ["An account with this email already exists."]})
        province = attrs.get("province")
        if province is not None and province.pk != lead.province_id:
            members = self.context["cluster"].farmers.exclude(pk=lead.pk)
            if members.exclude(province=province).exists():
                raise serializers.ValidationError({"province": ["This lead farmer already has farmers in another province. Move those farmers first."]})
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        return check_password_strength(value)


def _account_for(cluster):
    account = cluster.lead_farmer
    if account is None and cluster.lead_member_id:
        account = User.objects.filter(farmer_id=cluster.lead_member_id, role=User.ROLE_LEAD_FARMER).first()
    return account


def _place(item):
    return {"id": item.pk, "name": item.name} if item is not None else None


def _lead_summary(cluster, stats, performance):
    lead = cluster.lead_member
    account = _account_for(cluster)
    counts = stats.get(cluster.pk, {})
    figures = performance.get(cluster.pk, {})
    if account is None:
        state = "NO_LOGIN"
    elif not account.is_active:
        state = "INACTIVE"
    else:
        state = "ACTIVE"
    return {
        "cluster_id": cluster.pk,
        "cluster": cluster.name,
        "farmer_id": lead.pk,
        "lead_farmer": lead.full_name,
        "first_name": lead.first_name,
        "middle_name": lead.middle_name,
        "surname": lead.surname,
        "national_id": lead.national_id,
        "phone": lead.phone_primary,
        "email": account.email if account else (lead.email or ""),
        "province": _place(lead.province) or _place(cluster.province),
        "district": _place(lead.district),
        "ward": _place(lead.ward),
        "own_record_status": lead.verification_status,
        "account": {
            "id": account.pk,
            "email": account.email,
            "is_active": account.is_active,
            "last_login": account.last_login,
            "must_change_password": account.must_change_password,
        } if account else None,
        "status": state,
        "farmers": counts.get("total", 0),
        "approved": counts.get("approved", 0),
        "pending": counts.get("pending", 0),
        "rejected": counts.get("rejected", 0),
        "incomplete": counts.get("incomplete", 0),
        "corrections": counts.get("corrections", 0),
        "subscription_compliance": figures.get("subscription_compliance", 0),
        "agricultural_participation": figures.get("agricultural_participation", 0),
    }


def _member_stats(cluster_ids):
    members = Farmer.objects.filter(cluster_id__in=cluster_ids, is_lead=False)
    rows = members.values("cluster_id").annotate(
        total=Count("id"),
        approved=Count("id", filter=Q(verification_status__in=kyc.APPROVED_STATES)),
        pending=Count("id", filter=Q(verification_status__in=kyc.AWAITING_REVIEW)),
        rejected=Count("id", filter=Q(verification_status=Farmer.STATUS_REJECTED)),
        incomplete=Count("id", filter=Q(verification_status=Farmer.STATUS_DRAFT)),
        corrections=Count("id", filter=Q(verification_status=Farmer.STATUS_CORRECTIONS)),
    )
    return {row["cluster_id"]: row for row in rows}


class _Params:
    def __init__(self, season_name):
        self.query_params = {"season_name": season_name} if season_name else {}


class LeadFarmerViewSet(viewsets.ViewSet):
    """`pk` is the cluster's id. Each lead farmer has exactly one cluster."""

    permission_classes = [LeadFarmerPermission]

    def _clusters(self):
        return Cluster.objects.filter(lead_member__isnull=False).select_related(
            "province", "lead_farmer", "lead_member__province", "lead_member__district", "lead_member__ward",
        )

    def _get(self, pk):
        cluster = self._clusters().filter(pk=pk).first()
        if cluster is None:
            from django.http import Http404

            raise Http404("No such lead farmer.")
        return cluster

    def list(self, request):
        from apps.farmers.performance import build_cluster_performance

        clusters = list(self._clusters().order_by("name"))
        search = (request.query_params.get("search") or "").strip().lower()
        province = request.query_params.get("province")
        district = request.query_params.get("district")
        ids = [cluster.pk for cluster in clusters]
        stats = _member_stats(ids)
        season = request.query_params.get("season_name") or ""
        performance = {
            row["cluster_id"]: row
            for row in build_cluster_performance(Farmer.objects.filter(cluster_id__in=ids), _Params(season))["clusters"]
            if row.get("cluster_id")
        }
        rows = [_lead_summary(cluster, stats, performance) for cluster in clusters]
        overview_rows = list(rows)
        if search:
            rows = [row for row in rows if search in f"{row['lead_farmer']} {row['national_id']} {row['email']}".lower()]
        if province and str(province).isdigit():
            rows = [row for row in rows if row["province"] and row["province"]["id"] == int(province)]
        if district and str(district).isdigit():
            rows = [row for row in rows if row["district"] and row["district"]["id"] == int(district)]
        state = request.query_params.get("status")
        if state:
            rows = [row for row in rows if row["status"] == state]

        sizes = [(row["farmers"], row["lead_farmer"]) for row in overview_rows]
        unassigned = Farmer.objects.filter(is_lead=False).filter(Q(cluster__isnull=True) | Q(cluster__lead_member__isnull=True))
        overview = {
            "lead_farmers": len(overview_rows),
            "clusters": len(overview_rows),
            "active_logins": sum(1 for row in overview_rows if row["status"] == "ACTIVE"),
            "farmers": sum(size for size, _ in sizes),
            "average_cluster_size": round(sum(size for size, _ in sizes) / len(sizes), 1) if sizes else 0,
            "largest_cluster": {"lead_farmer": max(sizes)[1], "farmers": max(sizes)[0]} if sizes else None,
            "smallest_cluster": {"lead_farmer": min(sizes)[1], "farmers": min(sizes)[0]} if sizes else None,
            "approved": sum(row["approved"] for row in overview_rows),
            "pending": sum(row["pending"] for row in overview_rows),
            "rejected": sum(row["rejected"] for row in overview_rows),
            "incomplete": sum(row["incomplete"] + row["corrections"] for row in overview_rows),
            # Records that predate lead-farmer clusters. They are listed for the administrator, never assigned automatically.
            "farmers_without_lead": unassigned.count(),
            "clusters_without_lead": Cluster.objects.filter(lead_member__isnull=True).count(),
        }
        return Response({"overview": overview, "results": rows, "count": len(rows)})

    def retrieve(self, request, pk=None):
        from apps.farmers.cluster_overview import build_cluster_overview

        cluster = self._get(pk)
        stats = _member_stats([cluster.pk])
        season = request.query_params.get("season_name") or ""
        overview = build_cluster_overview(Farmer.objects.filter(cluster=cluster), request.user, season, cluster=cluster)
        summary = _lead_summary(cluster, stats, {cluster.pk: {
            "subscription_compliance": overview["performance"]["subscription_compliance"],
            "agricultural_participation": overview["performance"]["participation"],
        }})
        return Response({**summary, "overview": overview})

    @transaction.atomic
    def create(self, request):
        serializer = LeadFarmerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                farmer = Farmer.objects.create(
                    first_name=data["first_name"], middle_name=data.get("middle_name", ""), surname=data["surname"],
                    national_id=data["national_id"], phone_primary=data["phone_primary"], email=data["email"],
                    province=data["province"], district=data["district"], ward=data["ward"],
                    registered_by=request.user, verification_status=Farmer.STATUS_DRAFT,
                    membership_status=Farmer.MEMBERSHIP_INACTIVE,
                )
                cluster = open_lead_cluster(farmer)
                account = User(
                    email=data["email"], username=data["email"], first_name=farmer.first_name, last_name=farmer.surname,
                    phone_number=farmer.phone_primary, role=User.ROLE_LEAD_FARMER, farmer=farmer, assigned_cluster=cluster,
                    province=farmer.province, district=farmer.district, must_change_password=True,
                )
                account.set_password(data["password"])
                account.save()
                cluster.lead_farmer = account
                cluster.save(update_fields=["lead_farmer", "updated_at"])
                record_event(farmer, FarmerReviewEvent.UPDATED, request.user, "Registered as a lead farmer. Cluster and login created.")
        except IntegrityError:
            # Two administrators saved the same person at the same moment.
            return Response({"national_id": ["This person was registered a moment ago. Refresh the list."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.retrieve(request, cluster.pk).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        cluster = self._get(pk)
        lead = cluster.lead_member
        account = _account_for(cluster)
        serializer = LeadFarmerUpdateSerializer(data=request.data, context={"lead": lead, "account": account, "cluster": cluster})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            for field in ("first_name", "middle_name", "surname", "phone_primary", "email", "province", "district", "ward"):
                if field in data:
                    setattr(lead, field, data[field])
            lead.save()
            if account is not None:
                account.first_name = lead.first_name
                account.last_name = lead.surname
                account.phone_number = lead.phone_primary
                account.province = lead.province
                account.district = lead.district
                if "email" in data:
                    account.email = data["email"]
                    account.username = data["email"]
                account.save()
            if "province" in data and cluster.province_id != lead.province_id:
                cluster.province = lead.province
                cluster.save(update_fields=["province", "updated_at"])
            sync_cluster_name(cluster)
            record_event(lead, FarmerReviewEvent.UPDATED, request.user, "Lead farmer details changed: " + ", ".join(sorted(data)))
        return Response(self.retrieve(request, cluster.pk).data)

    @action(detail=True, methods=["post"], url_path="login")
    def create_login(self, request, pk=None):
        """A lead farmer registered before logins were created together gets one here."""
        cluster = self._get(pk)
        if _account_for(cluster) is not None:
            return Response({"detail": "This lead farmer already has a login."}, status=400)
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = cluster.lead_member
        account = User(
            email=serializer.validated_data["email"], username=serializer.validated_data["email"],
            first_name=lead.first_name, last_name=lead.surname, phone_number=lead.phone_primary,
            role=User.ROLE_LEAD_FARMER, farmer=lead, assigned_cluster=cluster, province=lead.province, district=lead.district,
            must_change_password=True,
        )
        account.set_password(serializer.validated_data["password"])
        try:
            with transaction.atomic():
                account.save()
                cluster.lead_farmer = account
                cluster.save(update_fields=["lead_farmer", "updated_at"])
        except IntegrityError:
            return Response({"detail": "This lead farmer already has a login."}, status=400)
        return Response(self.retrieve(request, cluster.pk).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        cluster = self._get(pk)
        account = _account_for(cluster)
        if account is None:
            return Response({"detail": "This lead farmer has no login yet."}, status=400)
        active = str(request.data.get("is_active")).lower() in {"1", "true", "yes"}
        account.is_active = active
        account.save(update_fields=["is_active", "updated_at"])
        record_event(cluster.lead_member, FarmerReviewEvent.UPDATED, request.user, "Login activated." if active else "Login deactivated. The cluster and its farmers are kept.")
        return Response(self.retrieve(request, cluster.pk).data)

    @action(detail=False, methods=["post"], url_path="reassign")
    def reassign(self, request):
        """Move one farmer to another lead farmer. Recorded in the farmer's history and the audit log."""
        farmer = Farmer.objects.select_related("cluster__lead_member").filter(pk=request.data.get("farmer")).first()
        target = self._clusters().filter(pk=request.data.get("cluster")).first()
        if farmer is None:
            return Response({"farmer": ["Choose the farmer to move."]}, status=400)
        try:
            reassign_farmer(farmer, target, request.user, request.data.get("reason"))
        except ValueError as error:
            return Response({"detail": str(error)}, status=400)
        return Response({"detail": f"{farmer.full_name} now belongs to {target.lead_member.full_name}.", "cluster": target.pk})
