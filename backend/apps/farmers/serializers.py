from decimal import Decimal

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
    class Meta:
        model = FarmerDocument
        fields = [
            "id",
            "farmer",
            "farm",
            "document_type",
            "file",
            "reference_number",
            "uploaded_by",
            "upload_date",
            "verified",
            "verified_by",
        ]

    def validate(self, attrs):
        instance = self.instance
        farmer = attrs.get("farmer", getattr(instance, "farmer", None))
        farm = attrs.get("farm", getattr(instance, "farm", None))
        if farmer and farm and farm.farmer_id != farmer.pk:
            raise serializers.ValidationError({"farm": ["Farm must belong to the selected farmer."]})
        subject = farmer or getattr(farm, "farmer", None)
        if subject:
            validate_geographic_scope(
                self,
                province=subject.province,
                district=subject.district,
                cluster=subject.cluster,
            )
        return attrs


class FarmSerializer(serializers.ModelSerializer):
    class Meta:
        model = Farm
        fields = [
            "id",
            "farmer",
            "farm_name",
            "province",
            "district",
            "ward",
            "physical_location",
            "latitude",
            "longitude",
            "total_hectares",
            "arable_hectares",
            "irrigated_hectares",
            "ownership_type",
            "farm_registration_reference",
            "verification_status",
            "verification_notes",
            "verified_by",
            "verification_date",
        ]

    def validate(self, attrs):
        instance = self.instance
        total = attrs.get("total_hectares", getattr(instance, "total_hectares", Decimal("0.00")))
        arable = attrs.get("arable_hectares", getattr(instance, "arable_hectares", Decimal("0.00")))
        irrigated = attrs.get("irrigated_hectares", getattr(instance, "irrigated_hectares", Decimal("0.00")))
        if total <= 0:
            raise serializers.ValidationError({"total_hectares": ["Total hectares must be greater than zero."]})
        if arable < 0 or irrigated < 0:
            raise serializers.ValidationError({"arable_hectares": ["Farm area values cannot be negative."]})
        if arable > total:
            raise serializers.ValidationError({"arable_hectares": ["Arable hectares cannot exceed total hectares."]})
        if irrigated > arable:
            raise serializers.ValidationError({"irrigated_hectares": ["Irrigated hectares cannot exceed arable hectares."]})
        farmer = attrs.get("farmer", getattr(instance, "farmer", None))
        province = attrs.get("province", getattr(instance, "province", None))
        district = attrs.get("district", getattr(instance, "district", None))
        ward = attrs.get("ward", getattr(instance, "ward", None))
        if farmer and province and farmer.province_id and farmer.province_id != province.pk:
            raise serializers.ValidationError({"province": ["Farm province must match the farmer's province."]})
        if farmer and district and farmer.district_id and farmer.district_id != district.pk:
            raise serializers.ValidationError({"district": ["Farm district must match the farmer's district."]})
        if district and province and district.province_id != province.pk:
            raise serializers.ValidationError({"district": ["District does not belong to the selected province."]})
        if ward and district and ward.district_id != district.pk:
            raise serializers.ValidationError({"ward": ["Ward does not belong to the selected district."]})
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
            cluster=getattr(farmer, "cluster", None),
        )
        return attrs


class FarmerSerializer(serializers.ModelSerializer):
    farm_count = serializers.SerializerMethodField()
    farm_hectares = serializers.SerializerMethodField()
    province_name = serializers.CharField(source="province.name", read_only=True)
    district_name = serializers.CharField(source="district.name", read_only=True)
    cluster_name = serializers.CharField(source="cluster.name", read_only=True)
    total_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01"), write_only=True
    )
    arable_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), write_only=True, required=False
    )
    irrigated_hectares = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.00"), write_only=True, required=False
    )
    farm_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=180,
        trim_whitespace=True,
    )
    latitude = OptionalCoordinateField(max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True)
    longitude = OptionalCoordinateField(max_digits=9, decimal_places=6, required=False, allow_null=True, write_only=True)

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
            "district",
            "district_name",
            "ward",
            "cluster",
            "cluster_name",
            "total_hectares",
            "arable_hectares",
            "irrigated_hectares",
            "farm_hectares",
            "farms",
            "farm_name",
            "latitude",
            "longitude",
            "registration_date",
            "membership_status",
            "verification_status",
            "verification_date",
            "verified_by",
            "rejection_reason",
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
            "farm_hectares",
            "farms",
        ]

    def validate(self, attrs):
        source = dict(self.initial_data)
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
        if cluster and (cluster.district_id != getattr(district, "pk", None) or cluster.province_id != getattr(province, "pk", None)):
            raise serializers.ValidationError({"cluster": ["Cluster must belong to the selected province and district."]})
        total_hectares = attrs.get("total_hectares", Decimal("0.00"))
        arable_hectares = attrs.get("arable_hectares", total_hectares)
        irrigated_hectares = attrs.get("irrigated_hectares", Decimal("0.00"))
        if arable_hectares > total_hectares:
            raise serializers.ValidationError({"arable_hectares": ["Arable hectares cannot exceed total hectares."]})
        if irrigated_hectares > arable_hectares:
            raise serializers.ValidationError({"irrigated_hectares": ["Irrigated hectares cannot exceed arable hectares."]})
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
        farm_name = validated_data.pop("farm_name", "")
        latitude = validated_data.pop("latitude", None)
        longitude = validated_data.pop("longitude", None)
        validated_data["verification_status"] = Farmer.STATUS_SUBMITTED
        farmer = Farmer.objects.create(**validated_data)
        Farm.objects.create(
            farmer=farmer,
            farm_name=farm_name.strip() or f"{farmer.full_name} Farm",
            province=farmer.province,
            district=farmer.district,
            ward=farmer.ward,
            latitude=latitude,
            longitude=longitude,
            total_hectares=hectares,
            arable_hectares=arable_hectares,
            irrigated_hectares=irrigated_hectares,
        )
        return farmer

    def update(self, instance, validated_data):
        validated_data.pop("total_hectares", None)
        validated_data.pop("farm_name", None)
        coordinates_sent = "latitude" in validated_data or "longitude" in validated_data
        latitude = validated_data.pop("latitude", None)
        longitude = validated_data.pop("longitude", None)
        farmer = super().update(instance, validated_data)
        if coordinates_sent:
            farm = farmer.farms.order_by("id").first()
            if farm is not None:
                farm.latitude = latitude
                farm.longitude = longitude
                farm.save(update_fields=["latitude", "longitude", "updated_at"])
        return farmer

    def get_farm_count(self, obj):
        return obj.farms.count()

    def get_farm_hectares(self, obj):
        return sum((farm.total_hectares for farm in obj.farms.all()), Decimal("0.00"))


class EligibleFarmerSerializer(FarmerSerializer):
    subscription_status = serializers.CharField(source="subscription_payment_status", read_only=True)

    class Meta(FarmerSerializer.Meta):
        fields = [*FarmerSerializer.Meta.fields, "subscription_status"]
