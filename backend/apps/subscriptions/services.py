from decimal import Decimal

from django.db.models import Sum

from apps.production.seasonal_services import SeasonalSubscriptionService


class SubscriptionPaymentService:
    @staticmethod
    def subscription_details(arable_hectares):
        hectares = Decimal(str(arable_hectares or 0))
        category = "200HA+" if hectares >= Decimal("200.00") else "UNDER_200HA"
        amount = SeasonalSubscriptionService.subscription_amount(hectares)
        return hectares, category, amount

    @classmethod
    def farmer_subscription_details(cls, farmer):
        hectares = farmer.farms.aggregate(total=Sum("arable_hectares"))["total"] or Decimal("0.00")
        return cls.subscription_details(hectares)

    @staticmethod
    def calculate_summary(expected_amount, paid_amount):
        expected = Decimal(str(expected_amount))
        paid = Decimal(str(paid_amount))

        if expected < 0:
            raise ValueError("Expected amount cannot be negative.")
        if paid < 0:
            raise ValueError("Paid amount cannot be negative.")
        if paid > expected:
            raise ValueError("Paid amount cannot exceed the expected amount.")

        if paid == expected:
            payment_status = "PAID"
        elif paid == 0:
            payment_status = "UNPAID"
        else:
            payment_status = "PARTIAL"

        return {
            "outstanding_amount": expected - paid,
            "payment_status": payment_status,
        }

    @staticmethod
    def calculate_display_summary(expected_amount, paid_amount):
        expected = Decimal(str(expected_amount))
        paid = Decimal(str(paid_amount))
        outstanding = max(expected - paid, Decimal("0.00"))
        if paid <= 0:
            payment_status = "UNPAID"
        elif paid >= expected:
            payment_status = "PAID"
        else:
            payment_status = "PARTIAL"
        return {"outstanding_amount": outstanding, "payment_status": payment_status}