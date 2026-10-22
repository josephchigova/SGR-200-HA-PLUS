from decimal import Decimal

from django.db import transaction

from .models import InputDebt


class RecoveryCalculationService:
    @staticmethod
    def calculate_summary(required_tonnes: Decimal | str, recovered_tonnes: Decimal | str):
        required = Decimal(str(required_tonnes))
        recovered = Decimal(str(recovered_tonnes))
        if required < 0:
            raise ValueError("Required recovery cannot be negative.")
        if recovered < 0:
            raise ValueError("Recovered tonnes cannot be negative.")
        applied_recovered = min(recovered, required)
        outstanding = max(required - applied_recovered, Decimal("0.00"))
        percentage = Decimal("0.00") if required == 0 else (applied_recovered / required) * Decimal("100.00")
        if applied_recovered == 0:
            status = InputDebt.STATUS_NOT_RECOVERED
        elif outstanding == 0:
            status = InputDebt.STATUS_FULLY_RECOVERED
        else:
            status = InputDebt.STATUS_PARTIALLY_RECOVERED
        return {
            "outstanding_tonnes": outstanding,
            "recovery_percentage": percentage.quantize(Decimal("0.01")),
            "status": status,
        }

    @staticmethod
    def calculate_monetary_summary(input_cost: Decimal | str, selling_price_per_tonne: Decimal | str, recovered_tonnes: Decimal | str):
        original_input_cost = Decimal(str(input_cost))
        selling_price = Decimal(str(selling_price_per_tonne))
        recovered = Decimal(str(recovered_tonnes))
        if original_input_cost < 0:
            raise ValueError("Input cost cannot be negative.")
        if selling_price <= 0:
            raise ValueError("Selling price per tonne must be greater than zero.")
        amount_recovered = (recovered * selling_price).quantize(Decimal("0.01"))
        if amount_recovered > original_input_cost:
            amount_recovered = original_input_cost
        outstanding_balance = (original_input_cost - amount_recovered).quantize(Decimal("0.01"))
        if outstanding_balance < 0:
            outstanding_balance = Decimal("0.00")
        return {
            "amount_recovered": amount_recovered,
            "outstanding_monetary_balance": outstanding_balance,
        }

    @staticmethod
    def calculate_outstanding(required_tonnes: Decimal | str, recovered_tonnes: Decimal | str):
        return RecoveryCalculationService.calculate_summary(required_tonnes, recovered_tonnes)["outstanding_tonnes"]

    @staticmethod
    def calculate_percentage(required_tonnes: Decimal | str, recovered_tonnes: Decimal | str):
        return RecoveryCalculationService.calculate_summary(required_tonnes, recovered_tonnes)["recovery_percentage"]

    @staticmethod
    @transaction.atomic
    def create_or_update_from_allocation(*, allocation, selling_price_per_tonne):
        selling_price = Decimal(str(selling_price_per_tonne))
        input_cost = Decimal(str(allocation.total_input_cost))
        existing = InputDebt.objects.filter(input_allocation=allocation).first()
        recovered = Decimal("0.00")
        if existing and existing.recovered_tonnes > 0:
            selling_price = Decimal(str(existing.selling_price_per_tonne))
            recovered = Decimal(str(existing.recovered_tonnes))
        if selling_price <= 0:
            raise ValueError("Selling price per tonne must be greater than zero.")
        required_tonnes = (input_cost / selling_price).quantize(Decimal("0.01"))
        summary = RecoveryCalculationService.calculate_summary(required_tonnes, recovered)
        monetary_summary = RecoveryCalculationService.calculate_monetary_summary(
            input_cost,
            selling_price,
            recovered,
        )

        defaults = {
            "farmer": allocation.farmer,
            "farm": allocation.farm,
            "province": allocation.farmer.province,
            "district": allocation.farmer.district,
            "programme": allocation.programme,
            "crop": allocation.crop,
            "contracted_hectares": allocation.hectares,
            "input_value": input_cost,
            "total_debt": input_cost,
            "selling_price_per_tonne": selling_price,
            "required_recovery_tonnes": required_tonnes,
            "recovered_tonnes": recovered,
            "outstanding_tonnes": summary["outstanding_tonnes"],
            "amount_recovered": monetary_summary["amount_recovered"],
            "outstanding_monetary_balance": monetary_summary["outstanding_monetary_balance"],
            "recovery_percentage": summary["recovery_percentage"],
            "status": summary["status"],
            "arda_amount": Decimal("0.00"),
            "sgr_amount": Decimal("0.00"),
        }
        debt, _ = InputDebt.objects.update_or_create(
            input_allocation=allocation,
            defaults=defaults,
        )
        return debt

    @staticmethod
    @transaction.atomic
    def apply_delivery(delivery):
        remaining = Decimal(str(delivery.recovery_tonnes))
        if remaining <= 0:
            return
        debts = InputDebt.objects.select_for_update().filter(
            farmer=delivery.farmer,
            programme__season=delivery.season,
            crop__iexact=delivery.crop,
        ).order_by("created_at")
        if not debts.exists():
            raise ValueError("No matching recovery debt exists for this farmer, crop, and season.")
        for debt in debts:
            if remaining <= 0:
                break
            recoverable = min(remaining, debt.outstanding_tonnes)
            if recoverable <= 0:
                continue
            debt.recovered_tonnes += recoverable
            debt_summary = RecoveryCalculationService.calculate_summary(
                debt.required_recovery_tonnes,
                debt.recovered_tonnes,
            )
            monetary_summary = RecoveryCalculationService.calculate_monetary_summary(
                debt.input_value,
                debt.selling_price_per_tonne,
                debt.recovered_tonnes,
            )
            debt.outstanding_tonnes = debt_summary["outstanding_tonnes"]
            debt.recovery_percentage = debt_summary["recovery_percentage"]
            debt.status = debt_summary["status"]
            debt.amount_recovered = monetary_summary["amount_recovered"]
            debt.outstanding_monetary_balance = monetary_summary["outstanding_monetary_balance"]
            debt.save(update_fields=[
                "recovered_tonnes",
                "outstanding_tonnes",
                "recovery_percentage",
                "status",
                "amount_recovered",
                "outstanding_monetary_balance",
                "updated_at",
            ])
            remaining -= recoverable
