from django.db import models


class DataBankEntry(models.Model):
    month = models.CharField(max_length=80)
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    receipts = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    source_check = models.CharField(max_length=255, blank=True)
    difference = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=80, blank=True)
    source_row = models.PositiveIntegerField(unique=True)


class ClusterPerformance(models.Model):
    cluster_name = models.CharField(max_length=255, unique=True)
    farmers_managed = models.PositiveIntegerField(default=0)
    maize_hectares = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    sorghum_hectares = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_hectares = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    paid_farmers = models.PositiveIntegerField(default=0)
    unpaid_farmers = models.PositiveIntegerField(default=0)
    payment_percent = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    province = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    cluster_contact = models.CharField(max_length=255, blank=True)
    contact_details = models.CharField(max_length=80, blank=True)
    expected_subscriptions = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class FinanceCashFlow(models.Model):
    month = models.CharField(max_length=80, unique=True)
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    receipts = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class BalanceSheetLine(models.Model):
    section = models.CharField(max_length=80, blank=True)
    particulars = models.CharField(max_length=255, unique=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    source_row = models.PositiveIntegerField(unique=True)


class ProfitLossLine(models.Model):
    particulars = models.CharField(max_length=255, unique=True)
    june = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    july = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    august = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    september = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    october = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    november = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    december = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    jun_aug_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    source_row = models.PositiveIntegerField(unique=True)


class MonthlySalary(models.Model):
    month = models.CharField(max_length=80, unique=True)
    planned_salary = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    actual_salary = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    variance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=80, blank=True)


class BudgetLine(models.Model):
    budget = models.CharField(max_length=80)
    group = models.CharField(max_length=160, blank=True)
    item = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    rate = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    unit = models.CharField(max_length=80, blank=True)
    cost_per_hectare = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    funded_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    source_row = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["budget", "source_row"], name="unique_budget_source_row")]
