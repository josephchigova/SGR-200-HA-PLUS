from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.farmers.models import Farmer
from apps.programmes.models import Crop, Season


class ProductionPlan(models.Model):
    crop = models.CharField(max_length=80)
    season = models.CharField(max_length=80)
    target_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    actual_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    variance_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    achievement = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    remaining_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["season", "crop"]
        constraints = [
            models.UniqueConstraint(fields=["crop", "season"], name="unique_production_plan")
        ]

    def __str__(self):
        return f"{self.season} - {self.crop}"


class SeasonalPlantingPlan(models.Model):
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="seasonal_planting_plans")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="seasonal_planting_plans")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="planting_plans")
    summer_crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="summer_planting_plans", null=True, blank=True)
    winter_crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="winter_planting_plans", null=True, blank=True)
    summer_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    winter_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-season__start_date", "farmer__surname"]
        constraints = [
            models.UniqueConstraint(fields=["farmer", "farm", "season"], name="unique_farmer_farm_season_plan"),
        ]

    @property
    def total_planted_hectares(self):
        return self.summer_hectares + self.winter_hectares

    def __str__(self):
        return f"{self.farmer.full_name} - {self.season.name}"


class FarmerProduction(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_PLANTED = "PLANTED"
    STATUS_HARVESTED = "HARVESTED"
    STATUS_COMPLETED = "COMPLETED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PLANTED, "Planted"),
        (STATUS_HARVESTED, "Harvested"),
        (STATUS_COMPLETED, "Completed"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="productions")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="productions", null=True, blank=True)
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="productions")
    crop = models.CharField(max_length=80)
    contracted_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    planted_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    planting_date = models.DateField(null=True, blank=True)
    crop_stage = models.CharField(max_length=80, blank=True)
    expected_yield = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    estimated_production = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    actual_production = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    harvest_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.crop}"


class GMBDelivery(models.Model):
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="gmb_deliveries")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="gmb_deliveries", null=True, blank=True)
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="deliveries")
    crop = models.CharField(max_length=80)
    delivery_date = models.DateField()
    gmb_depot = models.CharField(max_length=180, blank=True)
    delivery_reference = models.CharField(max_length=120, blank=True)
    ticket_number = models.CharField(max_length=120, blank=True)
    tonnes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    recovery_tonnes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_recovered = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    farmer_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    document = models.FileField(upload_to="gmb_delivery_documents/", blank=True, null=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recorded_deliveries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-delivery_date"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.ticket_number or self.delivery_reference or self.crop}"
