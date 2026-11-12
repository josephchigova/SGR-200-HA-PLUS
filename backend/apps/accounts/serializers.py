from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.clusters.models import Cluster

from .models import AuditLog
from .roles import capabilities

User = get_user_model()

SCOPED_ROLE_FIELDS = {
    User.ROLE_DISTRICT_COORDINATOR: ("district", "Choose the district this coordinator manages."),
    User.ROLE_PROVINCIAL_COORDINATOR: ("province", "Choose the province this coordinator manages."),
}


def registered_province_ids(farmer):
    """Provinces where this farmer is registered, on the profile or on a farm."""
    ids = set()
    if farmer.province_id:
        ids.add(farmer.province_id)
    ids.update(farmer.farms.exclude(province_id=None).values_list("province_id", flat=True))
    return ids


def check_password_strength(password, user=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as error:
        raise serializers.ValidationError(list(error.messages)) from error
    return password


class UserSerializer(serializers.ModelSerializer):
    """The signed-in user's own profile, with the permissions the interface needs."""

    role_label = serializers.CharField(source="get_role_display", read_only=True)
    permissions = serializers.SerializerMethodField()
    cluster_name = serializers.CharField(source="assigned_cluster.name", read_only=True, default="")
    district_name = serializers.CharField(source="district.name", read_only=True, default="")
    province_name = serializers.CharField(source="province.name", read_only=True, default="")

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "role_label",
            "is_active",
            "is_superuser",
            "date_joined",
            "assigned_cluster",
            "cluster_name",
            "district",
            "district_name",
            "province",
            "province_name",
            "must_change_password",
            "permissions",
        )
        read_only_fields = tuple(name for name in fields if name not in {"first_name", "last_name", "phone_number"})

    def get_permissions(self, user):
        return capabilities(user)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = (
            "email",
            "username",
            "first_name",
            "last_name",
            "phone_number",
            "password",
        )

    def validate_password(self, value):
        return check_password_strength(value)

    def create(self, validated_data):
        password = validated_data.pop("password")
        # A self-registered account cannot sign in until an administrator
        # assigns its role and activates it.
        user = User(**validated_data, role=User.ROLE_VIEWER, is_active=False)
        user.set_password(password)
        user.save()
        return user


class ManagedUserSerializer(serializers.ModelSerializer):
    """Accounts as the Super Administrator manages them."""

    role_label = serializers.CharField(source="get_role_display", read_only=True)
    cluster_name = serializers.CharField(source="assigned_cluster.name", read_only=True, default="")
    district_name = serializers.CharField(source="district.name", read_only=True, default="")
    province_name = serializers.CharField(source="province.name", read_only=True, default="")
    farmer_name = serializers.CharField(source="farmer.full_name", read_only=True, default="")
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, min_length=8)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "phone_number",
            "role",
            "role_label",
            "is_active",
            "province",
            "province_name",
            "district",
            "district_name",
            "assigned_cluster",
            "cluster_name",
            "farmer",
            "farmer_name",
            "must_change_password",
            "last_login",
            "date_joined",
            "password",
        )
        read_only_fields = ("id", "last_login", "date_joined", "must_change_password")
        extra_kwargs = {"username": {"required": False}}

    def validate_password(self, value):
        return check_password_strength(value)

    def validate(self, attrs):
        instance = self.instance
        role = attrs.get("role", getattr(instance, "role", User.ROLE_VIEWER))
        if role == User.ROLE_LEAD_FARMER:
            self._validate_lead_farmer(attrs, instance)
        else:
            scoped = SCOPED_ROLE_FIELDS.get(role)
            if scoped:
                field, message = scoped
                value = attrs.get(field, getattr(instance, field, None) if instance else None)
                if value is None:
                    raise serializers.ValidationError({field: [message]})
            attrs["farmer"] = None
            if instance and instance.role == User.ROLE_LEAD_FARMER:
                attrs["assigned_cluster"] = None
                attrs["province"] = None
        request = self.context.get("request")
        if instance and request and instance.pk == request.user.pk:
            if attrs.get("is_active") is False:
                raise serializers.ValidationError({"is_active": ["You cannot deactivate your own account."]})
            if "role" in attrs and attrs["role"] != instance.role:
                raise serializers.ValidationError({"role": ["You cannot change your own role."]})
        if not instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": ["Set a starting password for the new account."]})
        return attrs

    def _validate_lead_farmer(self, attrs, instance):
        # Switching a lead farmer on or off does not re-check the register.
        # Choosing the person or the cluster does.
        if instance is not None and not any(key in attrs for key in ("farmer", "assigned_cluster", "role")):
            return
        farmer = attrs["farmer"] if "farmer" in attrs else getattr(instance, "farmer", None)
        cluster = attrs["assigned_cluster"] if "assigned_cluster" in attrs else getattr(instance, "assigned_cluster", None)
        errors = {}
        if farmer is None:
            errors["farmer"] = ["Choose a registered farmer. A lead farmer account is only for someone already on the register."]
        if cluster is None:
            errors["assigned_cluster"] = ["Choose the cluster this lead farmer manages."]
        if farmer is not None and cluster is not None:
            province_ids = registered_province_ids(farmer)
            if not province_ids:
                errors["farmer"] = ["This farmer has no province on the register, so they cannot lead a cluster."]
            elif cluster.province_id not in province_ids:
                errors["assigned_cluster"] = ["A lead farmer cannot lead a cluster that is outside their province."]
            else:
                already = User.objects.filter(farmer=farmer)
                if instance is not None:
                    already = already.exclude(pk=instance.pk)
                if already.exists():
                    errors["farmer"] = ["This farmer already has an account."]
                leaders = User.objects.filter(role=User.ROLE_LEAD_FARMER, assigned_cluster=cluster)
                if instance is not None:
                    leaders = leaders.exclude(pk=instance.pk)
                if leaders.exists() or (cluster.lead_farmer_id and (instance is None or cluster.lead_farmer_id != instance.pk)):
                    errors["assigned_cluster"] = ["This cluster already has a lead farmer account."]
        if errors:
            raise serializers.ValidationError(errors)
        attrs["first_name"] = farmer.first_name
        attrs["last_name"] = farmer.surname
        current_phone = attrs["phone_number"] if "phone_number" in attrs else getattr(instance, "phone_number", "")
        if not str(current_phone or "").strip():
            attrs["phone_number"] = farmer.phone_primary or ""
        attrs["province"] = cluster.province

    def _sync_cluster_lead(self, user, previous_cluster_id):
        if previous_cluster_id and previous_cluster_id != user.assigned_cluster_id:
            Cluster.objects.filter(pk=previous_cluster_id, lead_farmer_id=user.pk).update(lead_farmer=None)
        if user.role == User.ROLE_LEAD_FARMER and user.assigned_cluster_id and user.farmer_id:
            Cluster.objects.filter(lead_farmer_id=user.pk).exclude(pk=user.assigned_cluster_id).update(lead_farmer=None)
            Cluster.objects.filter(pk=user.assigned_cluster_id).update(lead_farmer=user)
        else:
            Cluster.objects.filter(lead_farmer_id=user.pk).update(lead_farmer=None)

    def create(self, validated_data):
        password = validated_data.pop("password")
        if not validated_data.get("username"):
            validated_data["username"] = validated_data["email"]
        user = User(**validated_data)
        user.set_password(password)
        user.must_change_password = True
        user.save()
        self._sync_cluster_lead(user, None)
        return user

    def update(self, instance, validated_data):
        previous_cluster_id = instance.assigned_cluster_id
        password = validated_data.pop("password", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        if password:
            instance.set_password(password)
            instance.must_change_password = True
        instance.save()
        self._sync_cluster_lead(instance, previous_cluster_id)
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("The current password is incorrect.")
        return value

    def validate_new_password(self, value):
        return check_password_strength(value, self.context["request"].user)


class AuditLogSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = (
            "id", "created_at", "user", "user_email", "user_role", "action", "action_label",
            "module", "object_id", "summary", "method", "path", "status_code", "changed_fields", "ip_address",
        )
