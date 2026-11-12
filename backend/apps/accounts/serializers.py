from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AuditLog
from .roles import capabilities

User = get_user_model()

SCOPED_ROLE_FIELDS = {
    User.ROLE_LEAD_FARMER: ("assigned_cluster", "Choose the cluster this lead farmer manages."),
    User.ROLE_DISTRICT_COORDINATOR: ("district", "Choose the district this coordinator manages."),
    User.ROLE_PROVINCIAL_COORDINATOR: ("province", "Choose the province this coordinator manages."),
}


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
        scoped = SCOPED_ROLE_FIELDS.get(role)
        if scoped:
            field, message = scoped
            value = attrs.get(field, getattr(instance, field, None) if instance else None)
            if value is None:
                raise serializers.ValidationError({field: [message]})
        request = self.context.get("request")
        if instance and request and instance.pk == request.user.pk:
            if attrs.get("is_active") is False:
                raise serializers.ValidationError({"is_active": ["You cannot deactivate your own account."]})
            if "role" in attrs and attrs["role"] != instance.role:
                raise serializers.ValidationError({"role": ["You cannot change your own role."]})
        if not instance and not attrs.get("password"):
            raise serializers.ValidationError({"password": ["Set a starting password for the new account."]})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        if not validated_data.get("username"):
            validated_data["username"] = validated_data["email"]
        user = User(**validated_data)
        user.set_password(password)
        user.must_change_password = True
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for name, value in validated_data.items():
            setattr(instance, name, value)
        if password:
            instance.set_password(password)
            instance.must_change_password = True
        instance.save()
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
