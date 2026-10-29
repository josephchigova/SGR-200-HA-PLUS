from decimal import Decimal
from typing import ClassVar

from django.db import models

from apps.farmers.models import Farmer
from apps.programmes.models import Programme
from apps.programmes.models import Crop


class Input(models.Model):
    CATEGORY_SEED = "SEED"
    CATEGORY_FERTILIZER = "FERTILIZER"
    CATEGORY_PESTICIDE = "PESTICIDE"
    CATEGORY_TOOLKIT = "TOOLKIT"
    CATEGORY_OTHER = "OTHER"

    CATEGORY_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (CATEGORY_SEED, "Seed"),
        (CATEGORY_FERTILIZER, "Fertilizer"),
        (CATEGORY_PESTICIDE, "Pesticide"),
        (CATEGORY_TOOLKIT, "Toolkit"),
        (CATEGORY_OTHER, "Other"),
    ]

    name = models.CharField(max_length=160, unique=True)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default=CATEGORY_SEED)
    unit = models.CharField(max_length=40, default="bags")
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InputIssue(models.Model):
    STATUS_ISSUED = "ISSUED"
    STATUS_PENDING = "PENDING"
    STATUS_COLLECTED = "COLLECTED"
    STATUS_RETURNED = "RETURNED"

    STATUS_CHOICES = [
        (STATUS_ISSUED, "Issued"),
        (STATUS_PENDING, "Pending"),
        (STATUS_COLLECTED, "Collected"),
        (STATUS_RETURNED, "Returned"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="input_issues")
    input_name = models.CharField(max_length=180)
    batch_number = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, default="bags")
    issue_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    issue_date = models.DateTimeField(auto_now_add=True)
    collected_date = models.DateTimeField(null=True, blank=True)
    issued_by = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"{self.input_name} - {self.farmer.full_name}"


class InputAllocation(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_COLLECTED = "COLLECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COLLECTED, "Collected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="input_allocations")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="input_allocations", null=True, blank=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="input_allocations")
    crop_reference = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="input_allocations", null=True, blank=True)
    input = models.ForeignKey(Input, on_delete=models.PROTECT, related_name="allocations", null=True, blank=True)
    crop = models.CharField(max_length=80, blank=True)
    hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    unit = models.CharField(max_length=40, default="", blank=True)
    calculated_input_cost_per_hectare = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_input_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    allocation_date = models.DateField(auto_now_add=True)
    allocation_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    collection_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-allocation_date"]

    def __str__(self):
        return f"{self.crop or (self.crop_reference.name if self.crop_reference_id else 'Allocation')} - {self.farmer.full_name}"


class InputAllocationLine(models.Model):
    allocation = models.ForeignKey(InputAllocation, on_delete=models.CASCADE, related_name="calculation_lines")
    source_requirement = models.ForeignKey("programmes.CropInputRequirement", on_delete=models.SET_NULL, null=True, blank=True, related_name="allocation_lines")
    group_name = models.CharField(max_length=140)
    item_name = models.CharField(max_length=180)
    unit = models.CharField(max_length=40, blank=True, default="")
    rate_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    cost_per_unit = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    cost_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    required_quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0.0000"))
    calculated_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    included_in_total = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["allocation_id", "id"]

    def __str__(self):
        return f"{self.item_name} ({self.allocation_id})"
