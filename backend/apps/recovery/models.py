from decimal import Decimal
from typing import ClassVar

from django.db import models

from apps.farmers.models import Farmer


class InputDebt(models.Model):
    STATUS_NOT_RECOVERED = "NOT_RECOVERED"
    STATUS_PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    STATUS_FULLY_RECOVERED = "FULLY_RECOVERED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_NOT_RECOVERED, "Not recovered"),
        (STATUS_PARTIALLY_RECOVERED, "Partially recovered"),
        (STATUS_FULLY_RECOVERED, "Fully recovered"),
    ]

    input_allocation = models.OneToOneField("inputs.InputAllocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="debt")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="input_debts")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="input_debts", null=True, blank=True)
    province = models.ForeignKey("geography.Province", on_delete=models.PROTECT, related_name="input_debts", null=True, blank=True)
    district = models.ForeignKey("geography.District", on_delete=models.PROTECT, related_name="input_debts", null=True, blank=True)
    programme = models.ForeignKey("programmes.Programme", on_delete=models.PROTECT, related_name="input_debts")
    crop = models.CharField(max_length=80, blank=True)
    contracted_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    input_value = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    arda_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    sgr_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_debt = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    selling_price_per_tonne = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    required_recovery_tonnes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    recovered_tonnes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    outstanding_tonnes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_recovered = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    outstanding_monetary_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    recovery_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_NOT_RECOVERED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.crop or 'Debt'}"


class RecoveryRecord(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_PAID = "PAID"
    STATUS_OVERDUE = "OVERDUE"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_PAID, "Paid"),
        (STATUS_OVERDUE, "Overdue"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="recovery_records")
    province = models.CharField(max_length=120, blank=True)
    farm_name = models.CharField(max_length=255, blank=True)
    crop = models.CharField(max_length=80, blank=True)
    contracted_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    arda_grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grain_recovery_tonnes = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grain_delivered_tonnes = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    outstanding_tonnes = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    debt_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=20, default="USD")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    notes = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def calculate_outstanding_tonnes(self):
        outstanding = self.required_recovery_tonnes - self.recovered_tonnes
        if outstanding < 0:
            return Decimal("0.00")
        return outstanding

    def __str__(self):
        return f"{self.farmer.full_name} - {self.status}"
