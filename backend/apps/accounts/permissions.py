from rest_framework import permissions

from .models import User


class RolePermission(permissions.BasePermission):
    allowed_roles = ()

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles


class ManagementPermission(RolePermission):
    allowed_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_AUDITOR,
    }


class ProgrammePermission(RolePermission):
    allowed_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_PROGRAMME_OFFICER,
    }


class ProgrammeWorkflowPermission(permissions.BasePermission):
    read_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_VERIFICATION_OFFICER,
        User.ROLE_FINANCE_OFFICER,
        User.ROLE_PROGRAMME_OFFICER,
        User.ROLE_RECOVERY_OFFICER,
        User.ROLE_PROVINCIAL_COORDINATOR,
        User.ROLE_DISTRICT_COORDINATOR,
        User.ROLE_LEAD_FARMER,
        User.ROLE_AUDITOR,
        User.ROLE_VIEWER,
    }
    write_roles = ProgrammePermission.allowed_roles

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in self.read_roles
        return user.role in self.write_roles


class RecoveryPermission(RolePermission):
    allowed_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_RECOVERY_OFFICER,
    }


class RecoveryWorkflowPermission(permissions.BasePermission):
    read_roles = ProgrammeWorkflowPermission.read_roles
    write_roles = RecoveryPermission.allowed_roles

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in self.read_roles
        return user.role in self.write_roles


class FinancePermission(RolePermission):
    allowed_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_FINANCE_OFFICER,
    }


class FinanceAccessPermission(permissions.BasePermission):
    """Finance officers maintain the ledger. Auditors may read it. Payroll stays in this set."""

    read_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_FINANCE_OFFICER,
        User.ROLE_AUDITOR,
    }
    write_roles = FinancePermission.allowed_roles

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in self.read_roles
        return user.role in self.write_roles


class SubscriptionWorkflowPermission(permissions.BasePermission):
    read_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_VERIFICATION_OFFICER,
        User.ROLE_FINANCE_OFFICER,
        User.ROLE_PROGRAMME_OFFICER,
        User.ROLE_RECOVERY_OFFICER,
        User.ROLE_PROVINCIAL_COORDINATOR,
        User.ROLE_DISTRICT_COORDINATOR,
        User.ROLE_LEAD_FARMER,
        User.ROLE_AUDITOR,
        User.ROLE_VIEWER,
    }
    write_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_FINANCE_OFFICER,
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in self.read_roles
        return user.role in self.write_roles


class VerificationPermission(RolePermission):
    allowed_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_VERIFICATION_OFFICER,
    }


class FarmerWorkflowPermission(permissions.BasePermission):
    read_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_VERIFICATION_OFFICER,
        User.ROLE_FINANCE_OFFICER,
        User.ROLE_PROGRAMME_OFFICER,
        User.ROLE_RECOVERY_OFFICER,
        User.ROLE_PROVINCIAL_COORDINATOR,
        User.ROLE_DISTRICT_COORDINATOR,
        User.ROLE_LEAD_FARMER,
        User.ROLE_AUDITOR,
        User.ROLE_VIEWER,
    }
    write_roles = {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_VERIFICATION_OFFICER,
        User.ROLE_DISTRICT_COORDINATOR,
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return user.role in self.read_roles
        if getattr(view, "action", None) == "verify":
            return user.role in VerificationPermission.allowed_roles
        return user.role in self.write_roles

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser:
            return True
        if user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_AUDITOR, User.ROLE_VIEWER}:
            return True
        if user.role == User.ROLE_DISTRICT_COORDINATOR:
            return user.district_id == getattr(obj, "district_id", None)
        if user.role == User.ROLE_PROVINCIAL_COORDINATOR:
            return user.province_id == getattr(obj, "province_id", None)
        if user.role == User.ROLE_LEAD_FARMER:
            return user.assigned_cluster_id == getattr(obj, "cluster_id", None)
        return True


class DistrictScopedPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_AUDITOR, User.ROLE_VIEWER}:
            return True
        if user.role == User.ROLE_DISTRICT_COORDINATOR:
            district = getattr(obj, "district_id", None)
            if district is None and hasattr(obj, "farmer"):
                district = getattr(obj.farmer, "district_id", None)
            return user.district_id == district
        return True


class ProvinceScopedPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_AUDITOR, User.ROLE_VIEWER}:
            return True
        if user.role == User.ROLE_PROVINCIAL_COORDINATOR:
            province = getattr(obj, "province_id", None)
            if province is None and hasattr(obj, "farmer"):
                province = getattr(obj.farmer, "province_id", None)
            return user.province_id == province
        return True


class ClusterScopedPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_AUDITOR, User.ROLE_VIEWER}:
            return True
        if user.role == User.ROLE_LEAD_FARMER:
            cluster = getattr(obj, "cluster_id", None)
            if cluster is None and hasattr(obj, "farmer"):
                cluster = getattr(obj.farmer, "cluster_id", None)
            return user.assigned_cluster_id == cluster
        return True
