"""Change requests: a lead farmer proposes, administration approves, then the record changes."""

import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import VerificationPermission
from apps.accounts.scoping import scope_by_farmer

from .kyc import record_event
from .models import Farm, Farmer, FarmerChangeRequest, FarmerReviewEvent

PERSON_FIELDS = {
    "first_name": "First name",
    "middle_name": "Middle name",
    "surname": "Surname",
    "phone_primary": "Phone",
    "email": "Email",
    "gender": "Gender",
}
FARM_FIELDS = {
    "farm_name": "Farm name",
    "total_hectares": "Total farm size (ha)",
    "arable_hectares": "Arable land (ha)",
    "irrigated_hectares": "Irrigated land (ha)",
    "irrigation_type": "Irrigation type",
    "latitude": "Latitude",
    "longitude": "Longitude",
}
LOCATION_FIELDS = {"ward_number": "Ward number"}
LABELS = {**PERSON_FIELDS, **FARM_FIELDS, **LOCATION_FIELDS}
NAME = re.compile(r"^[^\W\d_]+(?:[ '-][^\W\d_]+)*$")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def current_values(farmer):
    farm = farmer.farms.order_by("id").first()
    values = {name: _text(getattr(farmer, name)) for name in PERSON_FIELDS}
    for name in FARM_FIELDS:
        values[name] = _text(getattr(farm, name)) if farm is not None else ""
    found = re.search(r"\d+", farmer.ward.name) if farmer.ward_id else None
    values["ward_number"] = str(int(found.group())) if found else ""
    return values


class ChangeRequestInputSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, max_length=100)
    middle_name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    surname = serializers.CharField(required=False, max_length=120)
    phone_primary = serializers.RegexField(r"^\d{9,12}$", required=False, error_messages={"invalid": "Enter 9 to 12 digits."})
    email = serializers.EmailField(required=False, allow_blank=True)
    gender = serializers.ChoiceField(choices=["", "MALE", "FEMALE", "OTHER"], required=False)
    farm_name = serializers.CharField(required=False, max_length=180)
    total_hectares = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01"))
    arable_hectares = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0"))
    irrigated_hectares = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0"))
    irrigation_type = serializers.ChoiceField(choices=[code for code, _ in Farm.IRRIGATION_CHOICES], required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True, min_value=Decimal("-90"), max_value=Decimal("90"))
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True, min_value=Decimal("-180"), max_value=Decimal("180"))
    ward_number = serializers.IntegerField(required=False, min_value=1, max_value=999)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        farmer = self.context["farmer"]
        for name in ("first_name", "middle_name", "surname", "farm_name"):
            if name in attrs:
                attrs[name] = " ".join(str(attrs[name]).upper().split())
                if name != "farm_name" and attrs[name] and not NAME.fullmatch(attrs[name]):
                    raise serializers.ValidationError({name: ["Use letters, spaces, apostrophes or hyphens only."]})
        for name in ("first_name", "surname", "farm_name"):
            if name in attrs and not attrs[name]:
                raise serializers.ValidationError({name: ["This cannot be empty."]})
        before = current_values(farmer)
        after = dict(before)
        changes = {}
        for name in LABELS:
            if name in attrs:
                value = _text(attrs[name])
                if value != before[name]:
                    changes[name] = value
                    after[name] = value
        try:
            total = Decimal(after["total_hectares"] or "0")
            arable = Decimal(after["arable_hectares"] or "0")
            irrigated = Decimal(after["irrigated_hectares"] or "0")
        except InvalidOperation:
            total = arable = irrigated = Decimal("0")
        if arable > total:
            raise serializers.ValidationError({"arable_hectares": ["Arable land cannot be more than the farm size."]})
        if irrigated > arable:
            raise serializers.ValidationError({"irrigated_hectares": ["Irrigated land cannot be more than the arable land."]})
        if bool(after["latitude"]) != bool(after["longitude"]):
            raise serializers.ValidationError({"latitude": ["Enter both latitude and longitude, or leave both empty."]})
        if not changes:
            raise serializers.ValidationError({"detail": ["Nothing has changed. Edit at least one detail."]})
        attrs["changes"] = changes
        attrs["previous"] = {name: before[name] for name in changes}
        return attrs


def rows_for(change):
    return [
        {"field": name, "label": LABELS.get(name, name), "old": change.previous.get(name, ""), "new": value}
        for name, value in change.changes.items()
    ]


class ChangeRequestSerializer(serializers.ModelSerializer):
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True)
    membership_number = serializers.CharField(source="farmer.membership_number", read_only=True)
    cluster_name = serializers.CharField(source="farmer.cluster.name", read_only=True, default="")
    requested_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    rows = serializers.SerializerMethodField()

    class Meta:
        model = FarmerChangeRequest
        fields = [
            "id", "farmer", "farmer_name", "membership_number", "cluster_name", "requested_by_name", "note", "rows",
            "status", "status_label", "remarks", "reviewed_by_name", "created_at", "reviewed_at",
        ]

    @staticmethod
    def _name(user):
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""

    def get_requested_by_name(self, obj):
        return self._name(obj.requested_by)

    def get_reviewed_by_name(self, obj):
        return self._name(obj.reviewed_by)

    def get_rows(self, obj):
        return rows_for(obj)


def submit_change_request(farmer, user, data):
    serializer = ChangeRequestInputSerializer(data=data, context={"farmer": farmer})
    serializer.is_valid(raise_exception=True)
    changes = serializer.validated_data["changes"]
    previous = serializer.validated_data["previous"]
    note = serializer.validated_data.get("note", "")
    with transaction.atomic():
        pending = FarmerChangeRequest.objects.select_for_update().filter(farmer=farmer, status=FarmerChangeRequest.PENDING).first()
        if pending is not None:
            # A newer request replaces the one still waiting, so administration sees one clear proposal.
            pending.changes, pending.previous, pending.note, pending.requested_by = changes, previous, note, user
            pending.save(update_fields=["changes", "previous", "note", "requested_by", "updated_at"])
            change = pending
        else:
            try:
                change = FarmerChangeRequest.objects.create(farmer=farmer, requested_by=user, changes=changes, previous=previous, note=note)
            except IntegrityError as error:
                raise serializers.ValidationError({"detail": ["A change request was sent a moment ago. Refresh the page."]}) from error
        summary = ", ".join(LABELS[name] for name in changes)
        record_event(farmer, FarmerReviewEvent.CHANGE_REQUESTED, user, summary + (f". Note: {note}" if note else ""))
    return change


def apply_change_request(change, user):
    """Write the approved values onto the farmer and their first farm."""
    from apps.geography.wards import ward_for_number

    from .serializers import _follow_lead_name

    farmer = change.farmer
    values = change.changes
    with transaction.atomic():
        for name in PERSON_FIELDS:
            if name in values:
                setattr(farmer, name, values[name])
        ward = None
        if "ward_number" in values and farmer.district_id:
            ward = ward_for_number(farmer.district, int(values["ward_number"]))
            farmer.ward = ward
        farmer.save()
        farm_values = {name: values[name] for name in FARM_FIELDS if name in values}
        if farm_values or ward is not None:
            farm = farmer.farms.order_by("id").first()
            if farm is None:
                farm = Farm(farmer=farmer, cluster=farmer.cluster, province=farmer.province, district=farmer.district, farm_name=f"{farmer.full_name} Farm")
            for name, value in farm_values.items():
                if name in {"latitude", "longitude"}:
                    value = Decimal(value) if value else None
                elif name.endswith("hectares"):
                    value = Decimal(value or "0")
                setattr(farm, name, value)
            if ward is not None:
                farm.ward = ward
            farm.save()
        if farmer.is_lead:
            _follow_lead_name(farmer)
        change.status = FarmerChangeRequest.APPROVED
        change.reviewed_by = user
        change.reviewed_at = timezone.now()
        change.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        record_event(farmer, FarmerReviewEvent.CHANGE_APPROVED, user, ", ".join(LABELS[name] for name in values))
    return change


class ChangeReviewPermission(permissions.BasePermission):
    """Administration reviews change requests. Auditors may read them."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in VerificationPermission.allowed_roles | {User.ROLE_AUDITOR}
        return user.role in VerificationPermission.allowed_roles


class FarmerChangeRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ChangeRequestSerializer
    permission_classes = [ChangeReviewPermission]

    def get_queryset(self):
        queryset = scope_by_farmer(
            FarmerChangeRequest.objects.select_related("farmer__cluster", "requested_by", "reviewed_by"), self.request.user,
        )
        state = self.request.query_params.get("status")
        if state:
            queryset = queryset.filter(status=state)
        return queryset

    def _pending(self):
        change = self.get_object()
        if change.status != FarmerChangeRequest.PENDING:
            raise serializers.ValidationError({"detail": ["This request has already been decided."]})
        return change

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        change = apply_change_request(self._pending(), request.user)
        return Response(self.get_serializer(change).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        change = self._pending()
        remarks = str(request.data.get("remarks") or "").strip()
        if not remarks:
            return Response({"remarks": ["Say why the change is rejected."]}, status=400)
        change.status = FarmerChangeRequest.REJECTED
        change.remarks = remarks
        change.reviewed_by = request.user
        change.reviewed_at = timezone.now()
        change.save(update_fields=["status", "remarks", "reviewed_by", "reviewed_at", "updated_at"])
        record_event(change.farmer, FarmerReviewEvent.CHANGE_REJECTED, request.user, remarks)
        return Response(self.get_serializer(change).data)
