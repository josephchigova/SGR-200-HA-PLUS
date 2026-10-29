from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.farmers.models import Farmer
from apps.programmes.models import Programme, Season


class ARDARequestBatch(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    request_number = models.CharField(max_length=80, unique=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="request_batches")
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True, related_name="request_batches")
    crop = models.CharField(max_length=80, blank=True)
    requested_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    date_created = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(null=True, blank=True)
    total_farmers = models.PositiveIntegerField(default=0)
    total_requested_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_arda_batches")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_arda_batches")
    submission_reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_created"]

    def __str__(self):
        return self.request_number


class ARDARequestNumberSequence(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_number = models.PositiveIntegerField(default=1000)


class ARDAFarmerRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    request_batch = models.ForeignKey(ARDARequestBatch, on_delete=models.CASCADE, related_name="farmer_requests")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="arda_farmer_requests")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="arda_requests", null=True, blank=True)
    requested_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    approved_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.request_batch.request_number}"


class ARDARequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_IN_PROGRESS, "In Progress"),
    ]

    REQUEST_FERTILIZER = "FERTILIZER"
    REQUEST_SEED = "SEED"
    REQUEST_PESTICIDE = "PESTICIDE"
    REQUEST_SPRAYER = "SPRAYER"
    REQUEST_OTHER = "OTHER"

    REQUEST_TYPE_CHOICES = [
        (REQUEST_FERTILIZER, "Fertilizer"),
        (REQUEST_SEED, "Seed"),
        (REQUEST_PESTICIDE, "Pesticide"),
        (REQUEST_SPRAYER, "Sprayer"),
        (REQUEST_OTHER, "Other"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="arda_requests")
    request_type = models.CharField(max_length=40, choices=REQUEST_TYPE_CHOICES, default=REQUEST_SEED)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, default="bags")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.get_request_type_display()}"
