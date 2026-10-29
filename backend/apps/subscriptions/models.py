from django.db import models

from apps.farmers.models import Farmer


class Subscription(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FarmerSubscription(models.Model):
    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="subscriptions")
    category = models.CharField(max_length=80, blank=True)
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    outstanding_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=40, blank=True)
    season = models.CharField(max_length=80, default="2026/2027")
    payment_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["farmer__surname", "farmer__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["farmer", "season"], name="unique_farmer_subscription_season")
        ]


class SubscriptionPayment(models.Model):
    METHOD_CASH = "CASH"
    METHOD_BANK = "BANK"
    METHOD_CHOICES = [(METHOD_CASH, "Cash"), (METHOD_BANK, "Bank")]

    subscription = models.ForeignKey(FarmerSubscription, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    reference = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="subscription_payments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="subscription_payment_positive"),
        ]
