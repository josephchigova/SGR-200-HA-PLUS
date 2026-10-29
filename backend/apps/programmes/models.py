from decimal import Decimal
from typing import ClassVar

from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Lower, Trim

from apps.farmers.models import Farmer


class Season(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_CLOSED, "Closed"),
    ]

    name = models.CharField(max_length=80, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name


class Crop(models.Model):
    CATEGORY_SUMMER = "SUMMER"
    CATEGORY_WINTER = "WINTER"
    CATEGORY_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (CATEGORY_SUMMER, "Summer"),
        (CATEGORY_WINTER, "Winter"),
    ]

    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                name="unique_crop_name_case_insensitive",
            ),
        ]

    def save(self, *args, **kwargs):
        normalized_name = " ".join((self.name or "").split())
        canonical = {
            "maize": "Maize",
            "sorghum": "Sorghum",
            "wheat": "Wheat",
        }
        self.name = canonical.get(normalized_name.lower(), normalized_name.title())
        super().save(*args, **kwargs)

    @property
    def total_input_cost_per_hectare(self):
        return self.input_requirements.filter(
            active=True,
            include_in_input_cost=True,
        ).aggregate(total=Sum("cost_per_hectare"))["total"] or Decimal("0.00")

    @property
    def active_input_count(self):
        return self.input_requirements.filter(active=True, include_in_input_cost=True).count()

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class CropInputRequirement(models.Model):
    COST_TYPE_INPUT = "AGRICULTURAL_INPUT"
    COST_TYPE_MACHINERY = "MACHINERY_HIRING"
    COST_TYPE_LABOUR = "LABOUR"
    COST_TYPE_OPERATIONAL = "OTHER_OPERATIONAL"

    COST_TYPE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (COST_TYPE_INPUT, "Agricultural input"),
        (COST_TYPE_MACHINERY, "Machinery / hiring"),
        (COST_TYPE_LABOUR, "Labour"),
        (COST_TYPE_OPERATIONAL, "Other operational"),
    ]

    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="input_requirements")
    group_name = models.CharField(max_length=140)
    item_name = models.CharField(max_length=180)
    rate_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    unit = models.CharField(max_length=40, blank=True, default="")
    cost_per_unit = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    cost_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    cost_type = models.CharField(max_length=30, choices=COST_TYPE_CHOICES, default=COST_TYPE_INPUT)
    include_in_input_cost = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["crop__name", "group_name", "item_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["crop", "group_name", "item_name", "cost_type"],
                name="unique_crop_input_requirement",
            ),
        ]

    def save(self, *args, **kwargs):
        rate = Decimal(str(self.rate_per_hectare or 0))
        cost_per_hectare = Decimal(str(self.cost_per_hectare or 0))

        if self.cost_per_unit is not None and rate > 0:
            cost_per_unit = Decimal(str(self.cost_per_unit))
            self.cost_per_hectare = (rate * cost_per_unit).quantize(Decimal("0.0001"))
        elif self.cost_per_unit is None and rate > 0 and cost_per_hectare > 0:
            self.cost_per_unit = (cost_per_hectare / rate).quantize(Decimal("0.0001"))

        if self.cost_type != self.COST_TYPE_INPUT:
            self.include_in_input_cost = False

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.crop.name} - {self.item_name}"


class CropSellingPrice(models.Model):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="selling_prices")
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True, related_name="crop_selling_prices")
    price_per_tonne = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["crop__name", "-effective_from", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price_per_tonne__gt=0),
                name="crop_selling_price_positive",
            ),
            models.UniqueConstraint(
                fields=["crop", "season"],
                condition=Q(active=True),
                name="unique_active_crop_year_selling_price",
            ),
        ]

    def __str__(self):
        season_name = self.season.name if self.season_id else "All seasons"
        return f"{self.crop.name} @ {self.price_per_tonne} ({season_name})"


class Programme(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_OPEN = "OPEN"
    STATUS_CLOSED = "CLOSED"
    STATUS_ARCHIVED = "ARCHIVED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True, related_name="programmes")
    crop = models.CharField(max_length=80, blank=True, default="Maize")
    institution = models.CharField(max_length=120, blank=True, default="ARDA")
    announced_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    application_open_date = models.DateField(null=True, blank=True)
    application_deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    total_allocated_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    @property
    def remaining_capacity(self):
        return max(self.announced_hectares - self.total_allocated_hectares, Decimal("0.00"))

    def __str__(self):
        return self.name


class ProgrammeAllocation(models.Model):
    INPUT_SEED = "SEED"
    INPUT_FERTILIZER = "FERTILIZER"
    INPUT_PESTICIDE = "PESTICIDE"
    INPUT_TOOLKIT = "TOOLKIT"
    INPUT_OTHER = "OTHER"

    INPUT_CHOICES = [
        (INPUT_SEED, "Seed"),
        (INPUT_FERTILIZER, "Fertilizer"),
        (INPUT_PESTICIDE, "Pesticide"),
        (INPUT_TOOLKIT, "Toolkit"),
        (INPUT_OTHER, "Other"),
    ]

    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name="allocations")
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="programme_allocations")
    input_type = models.CharField(max_length=40, choices=INPUT_CHOICES, default=INPUT_SEED)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, default="bags")
    allocated_by = models.CharField(max_length=120, blank=True)
    allocation_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-allocation_date"]

    def __str__(self):
        return f"{self.programme.name} - {self.farmer.full_name}"
