from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_SUPER_ADMIN = "super_admin"
    ROLE_SGR_EXECUTIVE = "sgr_executive"
    ROLE_VERIFICATION_OFFICER = "verification_officer"
    ROLE_FINANCE_OFFICER = "finance_officer"
    ROLE_PROGRAMME_OFFICER = "programme_officer"
    ROLE_RECOVERY_OFFICER = "recovery_officer"
    ROLE_PROVINCIAL_COORDINATOR = "provincial_coordinator"
    ROLE_DISTRICT_COORDINATOR = "district_coordinator"
    ROLE_LEAD_FARMER = "lead_farmer"
    ROLE_AUDITOR = "auditor"
    ROLE_VIEWER = "viewer"
    ROLE_MEMBERSHIP_OFFICER = "membership_officer"
    ROLE_PROCUREMENT_OFFICER = "procurement_officer"
    ROLE_STORES_OFFICER = "stores_officer"

    ROLE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (ROLE_SUPER_ADMIN, "Super Administrator"),
        (ROLE_SGR_EXECUTIVE, "SGR Executive / Management"),
        (ROLE_MEMBERSHIP_OFFICER, "Membership Officer"),
        (ROLE_VERIFICATION_OFFICER, "Verification Officer"),
        (ROLE_FINANCE_OFFICER, "Finance Officer"),
        (ROLE_PROGRAMME_OFFICER, "Agricultural / Programme Officer"),
        (ROLE_PROCUREMENT_OFFICER, "Procurement Officer"),
        (ROLE_STORES_OFFICER, "Stores Officer"),
        (ROLE_RECOVERY_OFFICER, "Recovery Officer"),
        (ROLE_PROVINCIAL_COORDINATOR, "Provincial Coordinator"),
        (ROLE_DISTRICT_COORDINATOR, "District Coordinator"),
        (ROLE_LEAD_FARMER, "Lead Farmer / Cluster Leader"),
        (ROLE_AUDITOR, "Auditor"),
        (ROLE_VIEWER, "Viewer"),
    ]

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=32, blank=True, default="")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    province = models.ForeignKey("geography.Province", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
    district = models.ForeignKey("geography.District", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
    assigned_cluster = models.ForeignKey("clusters.Cluster", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
    farmer = models.OneToOneField("farmers.Farmer", on_delete=models.SET_NULL, null=True, blank=True, related_name="user_account")
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        ordering = ["email"]

    def __str__(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name} ({self.email})"
        return self.email

    @property
    def is_management(self):
        return self.role in {
            self.ROLE_SUPER_ADMIN,
            self.ROLE_SGR_EXECUTIVE,
            self.ROLE_AUDITOR,
        }

    def has_role(self, *roles):
        return self.role in roles

    def can_access_district(self, district_id):
        if self.role in {self.ROLE_SUPER_ADMIN, self.ROLE_SGR_EXECUTIVE, self.ROLE_AUDITOR, self.ROLE_VIEWER}:
            return True
        if self.role == self.ROLE_DISTRICT_COORDINATOR:
            return self.district_id == district_id
        if self.role == self.ROLE_PROVINCIAL_COORDINATOR:
            return self.province_id == district_id
        return True

    def can_access_province(self, province_id):
        if self.role in {self.ROLE_SUPER_ADMIN, self.ROLE_SGR_EXECUTIVE, self.ROLE_AUDITOR, self.ROLE_VIEWER}:
            return True
        if self.role == self.ROLE_PROVINCIAL_COORDINATOR:
            return self.province_id == province_id
        if self.role == self.ROLE_DISTRICT_COORDINATOR:
            return self.district_id and self.district.province_id == province_id
        return True

    def can_access_cluster(self, cluster_id):
        if self.role in {self.ROLE_SUPER_ADMIN, self.ROLE_SGR_EXECUTIVE, self.ROLE_AUDITOR, self.ROLE_VIEWER}:
            return True
        if self.role == self.ROLE_LEAD_FARMER:
            return self.assigned_cluster_id == cluster_id
        return True


class AuditLog(models.Model):
    """One row for every change made through the API, and for sign-in events."""

    ACTION_CREATE = "CREATE"
    ACTION_UPDATE = "UPDATE"
    ACTION_DELETE = "DELETE"
    ACTION_LOGIN = "LOGIN"
    ACTION_LOGIN_FAILED = "LOGIN_FAILED"
    ACTION_PASSWORD = "PASSWORD"
    ACTION_EXPORT = "EXPORT"
    ACTION_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (ACTION_CREATE, "Created"),
        (ACTION_UPDATE, "Updated"),
        (ACTION_DELETE, "Deleted"),
        (ACTION_LOGIN, "Signed in"),
        (ACTION_LOGIN_FAILED, "Failed sign-in"),
        (ACTION_PASSWORD, "Password change"),
        (ACTION_EXPORT, "Exported"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    user_email = models.CharField(max_length=254, blank=True, default="")
    user_role = models.CharField(max_length=32, blank=True, default="")
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    module = models.CharField(max_length=60, blank=True, default="")
    object_id = models.CharField(max_length=60, blank=True, default="")
    summary = models.CharField(max_length=255, blank=True, default="")
    method = models.CharField(max_length=8, blank=True, default="")
    path = models.CharField(max_length=255, blank=True, default="")
    status_code = models.PositiveSmallIntegerField(default=0)
    changed_fields = models.JSONField(default=list, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["module", "created_at"], name="audit_module_created_idx")]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_email} {self.action} {self.module}"
