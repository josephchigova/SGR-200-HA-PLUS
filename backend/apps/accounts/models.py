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

    ROLE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (ROLE_SUPER_ADMIN, "Super Administrator"),
        (ROLE_SGR_EXECUTIVE, "SGR Executive / Management"),
        (ROLE_VERIFICATION_OFFICER, "Membership / Verification Officer"),
        (ROLE_FINANCE_OFFICER, "Finance Officer"),
        (ROLE_PROGRAMME_OFFICER, "Programme Officer"),
        (ROLE_RECOVERY_OFFICER, "Recovery Officer"),
        (ROLE_PROVINCIAL_COORDINATOR, "Provincial Coordinator"),
        (ROLE_DISTRICT_COORDINATOR, "District Coordinator"),
        (ROLE_LEAD_FARMER, "Lead Farmer / Cluster Leader"),
        (ROLE_AUDITOR, "Auditor / Viewer"),
        (ROLE_VIEWER, "Viewer"),
    ]

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=32, blank=True, default="")
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    province = models.ForeignKey("geography.Province", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
    district = models.ForeignKey("geography.District", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
    assigned_cluster = models.ForeignKey("clusters.Cluster", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_users")
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
