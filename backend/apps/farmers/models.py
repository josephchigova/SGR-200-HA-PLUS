from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.geography.models import District, Province, Ward


class Farmer(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_PENDING = "PENDING"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_UNDER_REVIEW = "UNDER_REVIEW"
    STATUS_VERIFIED = "VERIFIED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_ARCHIVED = "ARCHIVED"

    MEMBERSHIP_ACTIVE = "ACTIVE"
    MEMBERSHIP_INACTIVE = "INACTIVE"
    MEMBERSHIP_ARCHIVED = "ARCHIVED"

    VERIFICATION_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    MEMBERSHIP_CHOICES = [
        (MEMBERSHIP_ACTIVE, "Active"),
        (MEMBERSHIP_INACTIVE, "Inactive"),
        (MEMBERSHIP_ARCHIVED, "Archived"),
    ]

    membership_number = models.CharField(max_length=50, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    surname = models.CharField(max_length=120)
    full_name = models.CharField(max_length=255, blank=True)
    national_id = models.CharField(max_length=30, unique=True, blank=True)
    phone_primary = models.CharField(max_length=30, blank=True)
    phone_secondary = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True, default="")
    gender = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name="farmers", null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="farmers", null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.PROTECT, related_name="farmers", null=True, blank=True)
    cluster = models.ForeignKey(
        "clusters.Cluster",
        on_delete=models.SET_NULL,
        related_name="farmers",
        null=True,
        blank=True,
    )
    registration_date = models.DateField(auto_now_add=True)
    membership_status = models.CharField(max_length=30, choices=MEMBERSHIP_CHOICES, default=MEMBERSHIP_ACTIVE)
    verification_status = models.CharField(max_length=30, choices=VERIFICATION_CHOICES, default=STATUS_DRAFT)
    verification_date = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_farmers")
    rejection_reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["surname", "first_name"]
        indexes = [
            models.Index(fields=["full_name"], name="farmer_full_name_idx"),
            models.Index(fields=["surname", "first_name"], name="farmer_name_pair_idx"),
        ]

    def save(self, *args, **kwargs):
        self.full_name = f"{self.first_name} {self.middle_name} {self.surname}".strip()
        if not self.membership_number:
            self.membership_number = self._generate_membership_number()
        super().save(*args, **kwargs)

    def _generate_membership_number(self):
        province_code = (self.province.code if self.province else "GEN").upper()
        last = Farmer.objects.filter(membership_number__startswith=f"SGR-{province_code}-").count() + 1
        return f"SGR-{province_code}-{last:06d}"

    def __str__(self):
        return self.full_name or f"{self.first_name} {self.surname}".strip()


class Farm(models.Model):
    OWNERSHIP_OWNED = "OWNED"
    OWNERSHIP_LEASED = "LEASED"
    OWNERSHIP_COMMUNAL = "COMMUNAL"
    OWNERSHIP_TRADITIONAL = "TRADITIONAL"
    OWNERSHIP_OTHER = "OTHER"

    OWNERSHIP_CHOICES = [
        (OWNERSHIP_OWNED, "Owned"),
        (OWNERSHIP_LEASED, "Leased"),
        (OWNERSHIP_COMMUNAL, "Communal"),
        (OWNERSHIP_TRADITIONAL, "Traditional"),
        (OWNERSHIP_OTHER, "Other"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="farms")
    farm_name = models.CharField(max_length=180)
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name="farms", null=True, blank=True)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="farms", null=True, blank=True)
    ward = models.ForeignKey(Ward, on_delete=models.PROTECT, related_name="farms", null=True, blank=True)
    physical_location = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    total_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    arable_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    irrigated_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    ownership_type = models.CharField(max_length=30, choices=OWNERSHIP_CHOICES, default=OWNERSHIP_OWNED)
    farm_registration_reference = models.CharField(max_length=80, blank=True)
    verification_status = models.CharField(max_length=30, default="PENDING")
    verification_notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_farms")
    verification_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["farm_name"]

    def __str__(self):
        return self.farm_name


class FarmerDocument(models.Model):
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    document_type = models.CharField(max_length=120)
    file = models.FileField(upload_to="farmer_documents/")
    reference_number = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_documents")
    upload_date = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_documents")

    class Meta:
        ordering = ["-upload_date"]

    def __str__(self):
        return f"{self.document_type} - {self.farmer or self.farm}"
