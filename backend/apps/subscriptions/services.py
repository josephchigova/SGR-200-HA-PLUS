from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.production.seasonal_services import SeasonalSubscriptionService


class SubscriptionPaymentService:
    @staticmethod
    def subscription_details(arable_hectares):
        hectares = Decimal(str(arable_hectares or 0))
        category = "200HA+" if hectares >= Decimal("200.00") else "UNDER_200HA"
        amount = SeasonalSubscriptionService.subscription_amount(hectares)
        return hectares, category, amount

    @classmethod
    def farmer_subscription_details(cls, farmer, season_name=""):
        """The subscription follows the crops allocated for the agricultural year, not the farm size."""
        hectares = allocated_hectares([farmer.pk], season_name).get(farmer.pk, Decimal("0.00"))
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


HECTARES = DecimalField(max_digits=14, decimal_places=2)


def allocated_hectares(farmer_ids, season_name):
    """Crop hectares each farmer is allocated for one agricultural year, summed over every crop.

    A farmer with 50 ha of maize and 180 ha of sorghum has 230 ha and pays the 200 ha+ rate,
    whatever the size of the farm. The crop allocation captured at registration is used. A farmer
    with no allocation for that year falls back to the hectares on their production records.
    """
    from apps.farmers.models import RegistrationCropAllocation
    from apps.production.models import FarmerProduction

    ids = list(farmer_ids)
    if not ids or not season_name:
        return {}
    totals = {
        row["farmer_id"]: row["total"] or Decimal("0.00")
        for row in RegistrationCropAllocation.objects.filter(farmer_id__in=ids, season__name__iexact=season_name)
        .values("farmer_id").annotate(total=Sum("hectares"))
    }
    missing = [farmer_id for farmer_id in ids if farmer_id not in totals]
    if missing:
        for row in (
            FarmerProduction.objects.filter(farmer_id__in=missing, season__name__iexact=season_name)
            .values("farmer_id").annotate(total=Sum("contracted_hectares"))
        ):
            totals[row["farmer_id"]] = row["total"] or Decimal("0.00")
    return totals


def allocated_hectares_expression(season_name, farmer_ref="pk"):
    """The same figure as allocated_hectares, as a query expression on a Farmer queryset."""
    from apps.farmers.models import RegistrationCropAllocation
    from apps.production.models import FarmerProduction

    allocation = (
        RegistrationCropAllocation.objects.filter(farmer_id=OuterRef(farmer_ref), season__name__iexact=season_name)
        .values("farmer_id").annotate(total=Sum("hectares")).values("total")[:1]
    )
    production = (
        FarmerProduction.objects.filter(farmer_id=OuterRef(farmer_ref), season__name__iexact=season_name)
        .values("farmer_id").annotate(total=Sum("contracted_hectares")).values("total")[:1]
    )
    return Coalesce(
        Subquery(allocation, output_field=HECTARES),
        Subquery(production, output_field=HECTARES),
        Value(Decimal("0.00")),
        output_field=HECTARES,
    )


def cluster_compliance(expected_by_farmer, paid_by_farmer):
    """Share of the subscriptions due that has been paid: total paid over total due, as a percent.

    Each farmer's payment counts up to what that farmer owes, so one overpayment cannot hide
    another farmer's arrears.
    """
    due = sum((Decimal(str(value or 0)) for value in expected_by_farmer.values()), Decimal("0"))
    if due <= 0:
        return 0
    paid = sum(
        (min(Decimal(str(paid_by_farmer.get(farmer_id) or 0)), Decimal(str(expected or 0))) for farmer_id, expected in expected_by_farmer.items()),
        Decimal("0"),
    )
    return int(min(paid / due * 100, Decimal(100)))
