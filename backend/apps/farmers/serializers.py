from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import serializers

from .coordinates import clean_coordinate_pair
from .models import Farmer, Farm, FarmerDocument
from .services import FarmerRegistrationService


class OptionalCoordinateField(serializers.DecimalField):
    def to_internal_value(self, data):
        if data is None or data == "":
            return None
        return super().to_internal_value(data)


def _registered_ward(district, typed):
    """Find the ward the user meant: "Ward 5", "5" or "ward 05" all mean ward 5."""
    import re as _re

    from apps.geography.models import Ward

    wards = list(Ward.objects.filter(district=district, active=True))
    wanted = " ".join(typed.split()).casefold()
    for ward in wards:
        if ward.name.casefold() == wanted:
            return ward
    number = _re.search(r"\d+", typed)
    if number:
        for ward in wards:
            found = _re.search(r"\d+", ward.name)
            if found and int(found.group()) == int(number.group()):
                return ward
    raise serializers.ValidationError({"ward": [f"{typed} is not a ward of {district.name} on the official register. Choose a ward from the list."]})


def _follow_lead_name(farmer):
    """A lead farmer's cluster and login carry the lead farmer's current name."""
    from apps.accounts.models import User
    from apps.clusters.models import Cluster

    from .services import sync_cluster_name

    for cluster in Cluster.objects.filter(lead_member=farmer):
        sync_cluster_name(cluster)
    User.objects.filter(farmer=farmer).update(first_name=farmer.first_name, last_name=farmer.surname)


def validate_geographic_scope(serializer, *, province=None, district=None, cluster=None):
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_superuser:
        return
    if user.role == user.ROLE_DISTRICT_COORDINATOR and getattr(district, "pk", None) != user.district_id:
        raise serializers.ValidationError({"district": ["You can only manage records in your assigned district."]})
    if user.role == user.ROLE_PROVINCIAL_COORDINATOR and getattr(province, "pk", None) != user.province_id:
        raise serializers.ValidationError({"province": ["You can only manage records in your assigned province."]})
    if user.role == user.ROLE_LEAD_FARMER and getattr(cluster, "pk", None) != user.assigned_cluster_id:
        raise serializers.ValidationError({"cluster": ["You can only manage records in your assigned cluster."]})


class FarmerDocumentSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    required = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FarmerDocument
        fields = [
            "id",
            "farmer",
            "farm",
            "document_type",
            "label",
            "required",
            "file",
            "file_name",
            "download_url",
            "reference_number",
            "uploaded_by",
            "uploaded_by_name",
            "upload_date",
            "verified",
            "verified_by",
            "review_status",
            "review_remarks",
            "reviewed_at",
        ]
        # Only the review action changes the verification fields.
        read_only_fields = ["uploaded_by", "verified", "verified_by", "review_status", "review_remarks", "reviewed_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_label(self, obj):
        from .kyc import DOCUMENT_LABELS

        return DOCUMENT_LABELS.get(obj.document_type, obj.document_type)

    def get_required(self, obj):
        from .kyc import REQUIRED_CODES, required_codes_for

        if obj.farmer_id:
            return obj.document_type in required_codes_for(obj.farmer)
        return obj.document_type in REQUIRED_CODES

    def get_download_url(self, obj):
        # Files are never linked directly. This path checks the user on every request.
        return f"/farmer-documents/{obj.pk}/download/"

    def get_file_name(self, obj):
        return obj.original_name or obj.file.name.rsplit("/", 1)[-1]

    def get_uploaded_by_name(self, obj):
        user = obj.uploaded_by
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""

    def validate_file(self, upload):
        from .kyc import validate_upload

        problem = validate_upload(upload)
        if problem:
            raise serializers.ValidationError(problem)
        return upload

    def validate(self, attrs):
        from .kyc import AWAITING_REVIEW, DOCUMENT_CODES

        instance = self.instance
        farmer = attrs.get("farmer", getattr(instance, "farmer", None))
        farm = attrs.get("farm", getattr(instance, "farm", None))
        if farmer and farm and farm.farmer_id != farmer.pk:
            raise serializers.ValidationError({"farm": ["Farm must belong to the selected farmer."]})
        subject = farmer or getattr(farm, "farmer", None)
        if subject is None:
            raise serializers.ValidationError({"farmer": ["Choose the farmer this document belongs to."]})
        if attrs.get("document_type") not in DOCUMENT_CODES:
            raise serializers.ValidationError({"document_type": ["Choose one of the listed document types."]})
        validate_geographic_scope(
            self,
            province=subject.province,
            district=subject.district,
            cluster=subject.cluster,
        )
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER:
            if subject.verification_status in AWAITING_REVIEW or subject.verification_status in {Farmer.STATUS_VERIFIED, Farmer.STATUS_APPROVED}:
                raise serializers.ValidationError({"detail": ["Documents cannot be changed while the registration is with the administrator or after approval."]})
        return attrs


class FarmSerializer(serializers.ModelSerializer):
    province_name = serializers.SerializerMethodField()
    district_name = serializers.SerializerMethodField()
    ward_name = serializers.SerializerMethodField()
    cluster_name = serializers.SerializerMethodField()

    class Meta:
        model = Farm
        fields = [
            "id",
            "farmer",
            "farm_name",
            "province_name",
            "district_name",
            "ward_name",
            "cluster_name",
            "province",
            "district",
            "ward",
            "physical_location",
            "latitude",
            "longitude",
            "total_hectares",
            "arable_hectares",
            "irrigated_hectares",
            "irrigation_type",
            "cluster",
            "is_active",
            "ownership_type",
            "farm_registration_reference",
            "verification_status",
            "verification_notes",
            "verified_by",
            "verification_date",
        ]

    def get_province_name(self, obj):
        return obj.province.name if obj.province_id else ""

    def get_district_name(self, obj):
        return obj.district.name if obj.district_id else ""

    def get_ward_name(self, obj):
        return obj.ward.name if obj.ward_id else ""

    def get_cluster_name(self, obj):
        return obj.cluster.name if obj.cluster_id else ""

    def validate(self, attrs):
        instance = self.instance
        total = attrs.get("total_hectares", getattr(instance, "total_hectares", Decimal("0.00")))
        arable = attrs.get("arable_hectares", getattr(instance, "arable_hectares", Decimal("0.00")))
        irrigated = attrs.get("irrigated_hectares", getattr(instance, "irrigated_hectares", Decimal("0.00")))
        request = self.context.get("request")
        user = getattr(request, "user", None)
        owner = attrs.get("farmer", getattr(instance, "farmer", None))
        if user is not None and user.is_authenticated and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER and owner is not None:
            from .kyc import EDITABLE_BY_REGISTRAR

            if owner.verification_status not in EDITABLE_BY_REGISTRAR:
                raise serializers.ValidationError({"detail": ["Farm details can be changed only while the registration is a draft or corrections are requested."]})
        if total <= 0:
            raise serializers.ValidationError({"total_hectares": ["Total hectares must be greater than zero."]})
        if arable < 0 or irrigated < 0:
            raise serializers.ValidationError({"arable_hectares": ["Farm area values cannot be negative."]})
        if arable > total:
            raise serializers.ValidationError({"arable_hectares": ["Arable hectares cannot exceed total hectares."]})
        if irrigated > arable:
            raise serializers.ValidationError({"irrigated_hectares": ["Irrigated hectares cannot exceed arable hectares."]})
        province = attrs.get("province", getattr(instance, "province", None))
        district = attrs.get("district", getattr(instance, "district", None))
        ward = attrs.get("ward", getattr(instance, "ward", None))
        if owner is not None:
            # A farm belongs to its farmer's lead farmer. It is never moved to another cluster on its own.
            attrs["cluster"] = owner.cluster
        cluster = attrs.get("cluster", getattr(instance, "cluster", None))
        if district and province and district.province_id != province.pk:
            raise serializers.ValidationError({"district": ["District does not belong to the selected province."]})
        if ward and district and ward.district_id != district.pk:
            raise serializers.ValidationError({"ward": ["Ward does not belong to the selected district."]})
        if cluster and province and cluster.province_id != province.pk:
            raise serializers.ValidationError({"cluster": ["Cluster must belong to the selected province."]})
        if cluster and cluster.district_id and district and cluster.district_id != district.pk:
            raise serializers.ValidationError({"cluster": ["Cluster must belong to the selected district."]})
        if "latitude" in attrs or "longitude" in attrs:
            latitude = attrs["latitude"] if "latitude" in attrs else getattr(instance, "latitude", None)
            longitude = attrs["longitude"] if "longitude" in attrs else getattr(instance, "longitude", None)
            try:
                latitude, longitude = clean_coordinate_pair(latitude, longitude)
            except ValueError as exc:
                raise serializers.ValidationError({"latitude": [str(exc)]}) from exc
            attrs["latitude"] = latitude
            attrs["longitude"] = longitude
        validate_geographic_scope(
            self,
            province=province,
            district=district,
            cluster=cluster,
        )
        return attrs


class FarmerSerializer(serializers.ModelSerializer):
    farm_count = serializers.SerializerMethodField()
    farm_hectares = serializers.SerializerMethodField()
    total_arable_hectares = serializers.SerializerMethodField()
    total_irrigated_hectares = serializers.SerializerMethodField()
    additional_farms = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)
    province_name = serializers.CharField(source="province.name", read_only=True)
    registered_province_ids = serializers.SerializerMethodField()
    district_name = serializers.CharField(source="district.name", read_only=True)
    cluster_name = serializers.CharField(source="cluster.name", read_only=True)
    lead_member = serializers.SerializerMethodField()
    lead_farmer_name = serializers.SerializerMethodField()
    total_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), write_only=True
    )
    arable_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), write_only=True, required=False
    )
    irrigated_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), write_only=True, required=False
    )
    irrigation_type = serializers.ChoiceField(choices=Farm.IRRIGATION_CHOICES, write_only=True, required=False)
    farm_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=180,
        trim_whitespace=True,
    )
    latitude = OptionalCoordinateField(max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True)
    longitude = OptionalCoordinateField(max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True)
    # Set by the registration wizard: the farmer is saved as a draft until the KYC documents are in.
    as_draft = serializers.BooleanField(write_only=True, required=False, default=False)
    registered_by_name = serializers.SerializerMethodField()
    documents_summary = serializers.SerializerMethodField()
    kyc_upload_required = serializers.SerializerMethodField()
    primary_farm = serializers.SerializerMethodField()
    ward_name = serializers.CharField(source="ward.name", read_only=True, default="")
    ward_text = serializers.CharField(write_only=True, required=False, allow_blank=True)
    as_lead = serializers.BooleanField(write_only=True, required=False, default=False)
    crop_allocations = serializers.ListField(child=serializers.DictField(), write_only=True, required=False)

    class Meta:
        model = Farmer
        fields = [
            "id",
            "membership_number",
            "first_name",
            "middle_name",
            "surname",
            "full_name",
            "national_id",
            "phone_primary",
            "phone_secondary",
            "email",
            "gender",
            "date_of_birth",
            "address",
            "province",
            "province_name",
            "registered_province_ids",
            "district",
            "district_name",
            "ward",
            "ward_name",
            "ward_text",
            "farmer_type",
            "is_lead",
            "as_lead",
            "crop_allocations",
            "cluster",
            "cluster_name",
            "lead_member",
            "lead_farmer_name",
            "total_hectares",
            "arable_hectares",
            "irrigated_hectares",
            "irrigation_type",
            "farm_hectares",
            "total_arable_hectares",
            "total_irrigated_hectares",
            "farms",
            "farm_name",
            "additional_farms",
            "latitude",
            "longitude",
            "registration_date",
            "membership_status",
            "verification_status",
            "verification_date",
            "verified_by",
            "rejection_reason",
            "review_remarks",
            "registered_by",
            "registered_by_name",
            "submitted_at",
            "as_draft",
            "documents_summary",
            "kyc_upload_required",
            "primary_farm",
            "is_active",
            "farm_count",
        ]
        read_only_fields = [
            "membership_number",
            "full_name",
            "registration_date",
            "verification_date",
            "verification_status",
            "verified_by",
            "review_remarks",
            "registered_by",
            "submitted_at",
            "membership_status",
            "farm_hectares",
            "total_arable_hectares",
            "total_irrigated_hectares",
            "farms",
            "is_lead",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        national_id = self.fields.get("national_id")
        if national_id is not None:
            national_id.validators = [
                validator for validator in national_id.validators
                if validator.__class__.__name__ != "UniqueValidator"
            ]

    def _registrar(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return user if user is not None and user.is_authenticated else None

    def _is_lead_farmer(self):
        user = self._registrar()
        return bool(user and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER)

    def validate(self, attrs):
        from .kyc import EDITABLE_BY_REGISTRAR, NATIONAL_ID_PATTERN

        lead = self._is_lead_farmer()
        if lead:
            user = self._registrar()
            cluster = user.assigned_cluster
            if cluster is None:
                raise serializers.ValidationError({"cluster": ["Your account has no cluster yet. Ask an administrator to assign one."]})
            # The cluster is never taken from the request. It is always the lead farmer's own.
            attrs["cluster"] = cluster
            province = attrs.get("province", getattr(self.instance, "province", None))
            district = attrs.get("district", getattr(self.instance, "district", None))
            if province is not None and province.pk != cluster.province_id:
                raise serializers.ValidationError({"province": [f"You can only register farmers in {cluster.province.name}."]})
            if cluster.district_id and district is not None and district.pk != cluster.district_id:
                raise serializers.ValidationError({"district": [f"You can only register farmers in {cluster.district.name}."]})
            if self.instance is not None and self.instance.verification_status not in EDITABLE_BY_REGISTRAR:
                raise serializers.ValidationError({"detail": ["This registration is with the administrator. It can be changed only if corrections are requested."]})
        else:
            # Nobody else picks a cluster. A farmer joins a cluster when its lead farmer registers them,
            # and moves only through the administrator's audited reassignment.
            attrs.pop("cluster", None)
        strict = attrs.get("as_draft") or lead
        if strict:
            # New registrations use capital letters and the national ID format 63-2330173E58.
            for field in ("first_name", "middle_name", "surname", "farm_name", "national_id"):
                if isinstance(attrs.get(field), str):
                    attrs[field] = " ".join(attrs[field].upper().split())
            national_id = attrs.get("national_id")
            if national_id is not None and (self.instance is None or national_id != self.instance.national_id):
                if not NATIONAL_ID_PATTERN.fullmatch(national_id):
                    raise serializers.ValidationError({"national_id": ["Enter the national ID as 63-2330173E58: two digits, a hyphen, seven digits, a letter and two digits."]})
            typed_ward = str(attrs.pop("ward_text", "") or "").strip()
            district = attrs.get("district", getattr(self.instance, "district", None))
            if typed_ward:
                if district is None:
                    raise serializers.ValidationError({"ward_text": ["Choose the district before the ward."]})
                # Wards come from the official register only. A typed value must match one of them.
                attrs["ward"] = _registered_ward(district, typed_ward)
            else:
                attrs.pop("ward_text", None)
            ward = attrs.get("ward", getattr(self.instance, "ward", None))
            if self.instance is None and ward is None:
                raise serializers.ValidationError({"ward": ["Enter the ward."]})
        source = dict(self.initial_data)
        for field in ("first_name", "middle_name", "surname", "national_id", "farm_name"):
            if field in attrs and field in source:
                source[field] = attrs[field]
        if self.instance:
            for field in ("first_name", "surname", "national_id", "phone_primary", "province", "district", "ward"):
                if field not in source:
                    current = getattr(self.instance, f"{field}_id", None) if field in {"province", "district", "ward"} else getattr(self.instance, field)
                    source[field] = current
        errors = FarmerRegistrationService.validate(source, farmer_id=getattr(self.instance, "pk", None))
        if errors["errors"]:
            raise serializers.ValidationError(errors["errors"])
        cluster = attrs.get("cluster")
        district = attrs.get("district", getattr(self.instance, "district", None))
        province = attrs.get("province", getattr(self.instance, "province", None))
        if district and province and district.province_id != province.pk:
            raise serializers.ValidationError({"district": ["District does not belong to the selected province."]})
        if cluster and province and cluster.province_id != province.pk:
            raise serializers.ValidationError({"cluster": ["Cluster must belong to the selected province."]})
        if cluster and cluster.district_id and getattr(district, "pk", None) != cluster.district_id:
            raise serializers.ValidationError({"cluster": ["Cluster must belong to the selected district."]})
        total_hectares = attrs.get("total_hectares", Decimal("0.00"))
        arable_hectares = attrs.get("arable_hectares", total_hectares)
        irrigated_hectares = attrs.get("irrigated_hectares", Decimal("0.00"))
        if arable_hectares > total_hectares:
            raise serializers.ValidationError({"arable_hectares": ["Arable hectares cannot exceed total hectares."]})
        if irrigated_hectares > arable_hectares:
            raise serializers.ValidationError({"irrigated_hectares": ["Irrigated hectares cannot exceed arable hectares."]})
        extra_errors = []
        for index, farm in enumerate(attrs.get("additional_farms") or []):
            name = str(farm.get("farm_name") or "").strip()
            try:
                total = Decimal(str(farm.get("total_hectares") or "0"))
                arable = Decimal(str(farm.get("arable_hectares") or "0"))
                irrigated = Decimal(str(farm.get("irrigated_hectares") or "0"))
            except (InvalidOperation, ValueError):
                extra_errors.append(f"Farm {index + 2} has an invalid hectare value.")
                continue
            if not name:
                extra_errors.append(f"Farm {index + 2} needs a farm name.")
            if total <= 0:
                extra_errors.append(f"Farm {index + 2} must have total hectares greater than zero.")
            if arable > total or irrigated > arable or arable < 0 or irrigated < 0:
                extra_errors.append(f"Farm {index + 2} has hectares that do not fit inside each other.")
        if extra_errors:
            raise serializers.ValidationError({"additional_farms": extra_errors})
        if "latitude" in attrs or "longitude" in attrs:
            farm = self.instance.farms.order_by("id").first() if self.instance else None
            latitude = attrs["latitude"] if "latitude" in attrs else getattr(farm, "latitude", None)
            longitude = attrs["longitude"] if "longitude" in attrs else getattr(farm, "longitude", None)
            try:
                latitude, longitude = clean_coordinate_pair(latitude, longitude)
            except ValueError as exc:
                raise serializers.ValidationError({"latitude": [str(exc)]}) from exc
            attrs["latitude"] = latitude
            attrs["longitude"] = longitude
        validate_geographic_scope(self, province=province, district=district, cluster=cluster or getattr(self.instance, "cluster", None))
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        hectares = validated_data.pop("total_hectares")
        arable_hectares = validated_data.pop("arable_hectares", hectares)
        irrigated_hectares = validated_data.pop("irrigated_hectares", Decimal("0.00"))
        irrigation_type = validated_data.pop("irrigation_type", Farm.IRRIGATION_NONE)
        farm_name = validated_data.pop("farm_name", "")
        latitude = validated_data.pop("latitude", None)
        longitude = validated_data.pop("longitude", None)
        additional_farms = validated_data.pop("additional_farms", [])
        as_lead = validated_data.pop("as_lead", False)
        crop_rows = validated_data.pop("crop_allocations", None)
        validated_data.pop("ward_text", None)
        as_draft = validated_data.pop("as_draft", False) or self._is_lead_farmer() or as_lead
        # A draft waits for its KYC documents. Nothing is a member until an administrator approves it.
        validated_data["verification_status"] = Farmer.STATUS_DRAFT if as_draft else Farmer.STATUS_SUBMITTED
        validated_data["membership_status"] = Farmer.MEMBERSHIP_INACTIVE
        validated_data["registered_by"] = self._registrar()
        if not as_draft:
            from django.utils import timezone

            validated_data["submitted_at"] = timezone.now()
        farmer = Farmer.objects.create(**validated_data)
        if not as_draft:
            from .kyc import record_event
            from .models import FarmerReviewEvent

            record_event(farmer, FarmerReviewEvent.SUBMITTED, self._registrar())
        Farm.objects.create(
            farmer=farmer,
            farm_name=farm_name.strip() or f"{farmer.full_name} Farm",
            province=farmer.province,
            district=farmer.district,
            ward=farmer.ward,
            cluster=farmer.cluster,
            latitude=latitude,
            longitude=longitude,
            total_hectares=hectares,
            arable_hectares=arable_hectares,
            irrigated_hectares=irrigated_hectares,
            irrigation_type=irrigation_type,
        )
        for extra in additional_farms:
            Farm.objects.create(
                farmer=farmer,
                farm_name=str(extra.get("farm_name") or "").strip(),
                province_id=extra.get("province") or farmer.province_id,
                district_id=extra.get("district") or farmer.district_id,
                ward_id=extra.get("ward") or farmer.ward_id,
                cluster=farmer.cluster,
                total_hectares=extra.get("total_hectares") or "0",
                arable_hectares=extra.get("arable_hectares") or "0",
                irrigated_hectares=extra.get("irrigated_hectares") or "0",
                irrigation_type=extra.get("irrigation_type") or Farm.IRRIGATION_NONE,
            )
        if as_lead:
            from .services import open_lead_cluster

            cluster = open_lead_cluster(farmer)
            farmer.farms.update(cluster=cluster)
        if crop_rows is not None:
            self._save_crops(farmer, crop_rows)
        return farmer

    def update(self, instance, validated_data):
        validated_data.pop("additional_farms", None)
        validated_data.pop("as_draft", None)
        as_lead = validated_data.pop("as_lead", False)
        crop_rows = validated_data.pop("crop_allocations", None)
        validated_data.pop("ward_text", None)
        farm_changes = {
            name: validated_data.pop(name)
            for name in ("total_hectares", "arable_hectares", "irrigated_hectares", "irrigation_type", "farm_name")
            if name in validated_data
        }
        coordinates_sent = "latitude" in validated_data or "longitude" in validated_data
        latitude = validated_data.pop("latitude", None)
        longitude = validated_data.pop("longitude", None)
        farmer = super().update(instance, validated_data)
        from .kyc import EDITABLE_BY_REGISTRAR

        if farm_changes and farmer.verification_status in EDITABLE_BY_REGISTRAR:
            # While a registration is still being prepared, its first farm follows the form.
            farm = farmer.farms.order_by("id").first()
            if farm is None and "total_hectares" in farm_changes:
                # A lead farmer registered on the Lead farmers page has no farm until this form adds it.
                farm = Farm(farmer=farmer, cluster=farmer.cluster)
                farm_changes.setdefault("farm_name", f"{farmer.full_name} Farm")
            if farm is not None:
                for name, value in farm_changes.items():
                    setattr(farm, name, value)
                farm.province, farm.district, farm.ward = farmer.province, farmer.district, farmer.ward
                farm.save()
        if coordinates_sent:
            farm = farmer.farms.order_by("id").first()
            if farm is not None:
                farm.latitude = latitude
                farm.longitude = longitude
                farm.save(update_fields=["latitude", "longitude", "updated_at"])
        if as_lead:
            from .services import open_lead_cluster

            open_lead_cluster(farmer)
        if farmer.is_lead:
            _follow_lead_name(farmer)
        if crop_rows is not None:
            self._save_crops(farmer, crop_rows)
        return farmer

    def _save_crops(self, farmer, rows):
        from .services import replace_crop_allocations

        try:
            replace_crop_allocations(farmer, rows)
        except ValueError as exc:
            raise serializers.ValidationError({"crop_allocations": [str(exc)]}) from exc

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["crop_allocations"] = [
            {
                "id": row.pk,
                "crop": row.crop_id,
                "crop_name": row.crop.name,
                "season": row.season_id,
                "season_name": row.season.name,
                "hectares": str(row.hectares),
            }
            for row in instance.crop_allocations.select_related("crop", "season")
        ]
        return data

    def get_lead_member(self, obj):
        cluster = obj.cluster
        return cluster.lead_member_id if cluster is not None and cluster.lead_member_id else None

    def get_lead_farmer_name(self, obj):
        cluster = obj.cluster
        if cluster is None:
            return ""
        if cluster.lead_member_id:
            return cluster.lead_member.full_name
        user = cluster.lead_farmer
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.email

    def get_registered_by_name(self, obj):
        user = obj.registered_by
        return (f"{user.first_name} {user.last_name}".strip() or user.email) if user else ""

    def get_primary_farm(self, obj):
        farms = sorted(obj.farms.all(), key=lambda farm: farm.pk)
        if not farms:
            return None
        farm = farms[0]
        return {
            "id": farm.pk,
            "farm_name": farm.farm_name,
            "total_hectares": str(farm.total_hectares),
            "arable_hectares": str(farm.arable_hectares),
            "irrigated_hectares": str(farm.irrigated_hectares),
            "irrigation_type": farm.irrigation_type,
            "latitude": str(farm.latitude) if farm.latitude is not None else None,
            "longitude": str(farm.longitude) if farm.longitude is not None else None,
        }

    def get_kyc_upload_required(self, obj):
        from .kyc import kyc_upload_required

        return kyc_upload_required(obj)

    def get_documents_summary(self, obj):
        from .kyc import required_codes_for

        documents = list(obj.documents.all())
        present = {document.document_type for document in documents}
        required = required_codes_for(obj)
        return {
            "required": len(required),
            "uploaded_required": sum(1 for code in required if code in present),
            "uploaded": len(documents),
            "verified": sum(1 for document in documents if document.review_status == "VERIFIED"),
            "rejected": sum(1 for document in documents if document.review_status == "REJECTED"),
        }

    def _active_farms(self, obj):
        return [farm for farm in obj.farms.all() if farm.is_active]

    def get_registered_province_ids(self, obj):
        ids = {obj.province_id} if obj.province_id else set()
        ids.update(farm.province_id for farm in obj.farms.all() if farm.province_id)
        return sorted(ids)

    def get_farm_count(self, obj):
        return len(self._active_farms(obj))

    def get_farm_hectares(self, obj):
        return sum((farm.total_hectares for farm in self._active_farms(obj)), Decimal("0.00"))

    def get_total_arable_hectares(self, obj):
        return sum((farm.arable_hectares for farm in self._active_farms(obj)), Decimal("0.00"))

    def get_total_irrigated_hectares(self, obj):
        return sum((farm.irrigated_hectares for farm in self._active_farms(obj)), Decimal("0.00"))


class EligibleFarmerSerializer(FarmerSerializer):
    subscription_status = serializers.CharField(source="subscription_payment_status", read_only=True)

    class Meta(FarmerSerializer.Meta):
        fields = [*FarmerSerializer.Meta.fields, "subscription_status"]
