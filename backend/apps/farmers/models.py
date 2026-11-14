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
    STATUS_CORRECTIONS = "CORRECTIONS_REQUESTED"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_ARCHIVED = "ARCHIVED"

    MEMBERSHIP_ACTIVE = "ACTIVE"
    MEMBERSHIP_INACTIVE = "INACTIVE"
    MEMBERSHIP_ARCHIVED = "ARCHIVED"

    TYPE_NEW = "NEW"
    TYPE_EXISTING = "EXISTING"
    FARMER_TYPE_CHOICES = [
        (TYPE_NEW, "New farmer"),
        (TYPE_EXISTING, "Existing farmer"),
    ]

    VERIFICATION_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CORRECTIONS, "Corrections requested"),
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
    # The reviewer's latest remarks, shown to the person who registered the farmer.
    review_remarks = models.TextField(blank=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="registered_farmers")
    submitted_at = models.DateTimeField(null=True, blank=True)
    farmer_type = models.CharField(max_length=20, choices=FARMER_TYPE_CHOICES, default=TYPE_EXISTING)
    is_lead = models.BooleanField(default=False)
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
        self.full_name = " ".join(part for part in (self.first_name, self.middle_name, self.surname) if part).strip()
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
    IRRIGATION_NONE = "NONE"
    IRRIGATION_RAINFED = "RAINFED"
    IRRIGATION_CENTRE_PIVOT = "CENTRE_PIVOT"
    IRRIGATION_DRIP = "DRIP"
    IRRIGATION_SPRINKLER = "SPRINKLER"
    IRRIGATION_FLOOD = "FLOOD"
    IRRIGATION_OTHER = "OTHER"
    IRRIGATION_CHOICES = [
        (IRRIGATION_NONE, "Not recorded"),
        (IRRIGATION_RAINFED, "Rainfed"),
        (IRRIGATION_CENTRE_PIVOT, "Centre pivot"),
        (IRRIGATION_DRIP, "Drip"),
        (IRRIGATION_SPRINKLER, "Sprinkler"),
        (IRRIGATION_FLOOD, "Flood"),
        (IRRIGATION_OTHER, "Other"),
    ]
    irrigation_type = models.CharField(max_length=30, choices=IRRIGATION_CHOICES, default=IRRIGATION_NONE)
    cluster = models.ForeignKey(
        "clusters.Cluster",
        on_delete=models.SET_NULL,
        related_name="farms",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
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
    REVIEW_PENDING = "PENDING"
    REVIEW_VERIFIED = "VERIFIED"
    REVIEW_REJECTED = "REJECTED"
    REVIEW_CHOICES = [
        (REVIEW_PENDING, "Awaiting review"),
        (REVIEW_VERIFIED, "Verified"),
        (REVIEW_REJECTED, "Rejected"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="documents", null=True, blank=True)
    document_type = models.CharField(max_length=120)
    file = models.FileField(upload_to="farmer_documents/")
    reference_number = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_documents")
    upload_date = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_documents")
    review_status = models.CharField(max_length=12, choices=REVIEW_CHOICES, default=REVIEW_PENDING)
    review_remarks = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-upload_date"]

    def __str__(self):
        return f"{self.document_type} - {self.farmer or self.farm}"


class FarmerReviewEvent(models.Model):
    """The history of one registration: each submission, decision and document check."""

    SUBMITTED = "SUBMITTED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CORRECTIONS = "CORRECTIONS_REQUESTED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    UPDATED = "UPDATED"
    REASSIGNED = "REASSIGNED"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    CHANGE_APPROVED = "CHANGE_APPROVED"
    CHANGE_REJECTED = "CHANGE_REJECTED"
    ACTION_CHOICES = [
        (SUBMITTED, "Submitted for approval"),
        (RESUBMITTED, "Resubmitted after changes"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (CORRECTIONS, "Corrections requested"),
        (DOCUMENT_UPLOADED, "Document uploaded"),
        (DOCUMENT_VERIFIED, "Document verified"),
        (DOCUMENT_REJECTED, "Document rejected"),
        (UPDATED, "Details changed"),
        (REASSIGNED, "Moved to another lead farmer"),
        (CHANGE_REQUESTED, "Change requested"),
        (CHANGE_APPROVED, "Change approved"),
        (CHANGE_REJECTED, "Change rejected"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="review_events")
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    remarks = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="farmer_review_events")
    actor_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.farmer_id} {self.action}"


class RegistrationCropAllocation(models.Model):
    """Crops the registrar captured for this farmer. Approval copies them into production."""

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="crop_allocations")
    crop = models.ForeignKey("programmes.Crop", on_delete=models.PROTECT, related_name="registration_allocations")
    season = models.ForeignKey("programmes.Season", on_delete=models.PROTECT, related_name="registration_allocations")
    hectares = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["season_id", "crop__name"]
        constraints = [
            models.UniqueConstraint(fields=["farmer", "crop", "season"], name="unique_registration_crop_season"),
        ]

    def __str__(self):
        return f"{self.farmer_id} {self.crop_id} {self.hectares}"


class FarmerChangeRequest(models.Model):
    """Changes a lead farmer asks for on a record administration already holds.

    Nothing changes on the farmer until an administrator approves the request.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STATUS_CHOICES = [(PENDING, "Awaiting approval"), (APPROVED, "Approved"), (REJECTED, "Rejected")]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="change_requests")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="farmer_change_requests")
    changes = models.JSONField(default=dict)
    previous = models.JSONField(default=dict)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    remarks = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_farmer_changes")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["farmer"], condition=models.Q(status="PENDING"), name="one_pending_change_per_farmer"),
        ]

    def __str__(self):
        return f"{self.farmer_id} {self.status}"
