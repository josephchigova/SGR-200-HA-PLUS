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
    def farmer_subscription_details(cls, farmer, season_name="", crop_season=""):
        """The fee follows the hectares the farmer intends to plant, for one season when given."""
        hectares = allocated_hectares([farmer.pk], season_name, crop_season).get(farmer.pk, Decimal("0.00"))
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


def normalize_crop_season(value):
    season = str(value or "").strip().upper()
    return season if season in {"SUMMER", "WINTER"} else ""


def _planting_query(model, farmer_ids, season_name, crop_season, farmer_field="farmer_id"):
    query = model.objects.filter(**{f"{farmer_field}__in": farmer_ids, "season__name__iexact": season_name})
    if not crop_season:
        return query
    if model.__name__ == "RegistrationCropAllocation":
        return query.filter(crop__category=crop_season)
    from django.db.models import Q

    from apps.programmes.models import Crop

    names = list(Crop.objects.filter(category=crop_season).values_list("name", flat=True))
    if not names:
        return query.none()
    name_filter = Q()
    for name in names:
        name_filter |= Q(crop__iexact=name)
    return query.filter(name_filter)


def _planting_subquery(model, season_name, crop_season, farmer_ref):
    query = model.objects.filter(farmer_id=OuterRef(farmer_ref), season__name__iexact=season_name)
    if not crop_season:
        return query
    if model.__name__ == "RegistrationCropAllocation":
        return query.filter(crop__category=crop_season)
    from django.db.models import Q

    from apps.programmes.models import Crop

    names = list(Crop.objects.filter(category=crop_season).values_list("name", flat=True))
    if not names:
        return query.none()
    name_filter = Q()
    for name in names:
        name_filter |= Q(crop__iexact=name)
    return query.filter(name_filter)


def allocated_hectares(farmer_ids, season_name, crop_season=""):
    """Hectares each farmer intends to plant.

    With no crop season, every crop in the agricultural year is added together. Summer or winter
    uses only the crops of that season, so a change in one season changes only that subscription.
    Registration is used first. A farmer with nothing recorded falls back to production records.
    """
    from apps.farmers.models import RegistrationCropAllocation
    from apps.production.models import FarmerProduction

    ids = list(farmer_ids)
    crop_season = normalize_crop_season(crop_season)
    if not ids or not season_name:
        return {}
    totals = {
        row["farmer_id"]: row["total"] or Decimal("0.00")
        for row in _planting_query(RegistrationCropAllocation, ids, season_name, crop_season)
        .values("farmer_id").annotate(total=Sum("hectares"))
    }
    missing = [farmer_id for farmer_id in ids if farmer_id not in totals]
    if missing:
        for row in (
            _planting_query(FarmerProduction, missing, season_name, crop_season)
            .values("farmer_id").annotate(total=Sum("contracted_hectares"))
        ):
            totals[row["farmer_id"]] = row["total"] or Decimal("0.00")
    return totals


def allocated_hectares_expression(season_name, farmer_ref="pk", crop_season=""):
    """The same figure as allocated_hectares, as a query expression on a Farmer queryset."""
    from apps.farmers.models import RegistrationCropAllocation
    from apps.production.models import FarmerProduction

    crop_season = normalize_crop_season(crop_season)
    allocation = (
        _planting_subquery(RegistrationCropAllocation, season_name, crop_season, farmer_ref)
        .values("farmer_id").annotate(total=Sum("hectares")).values("total")[:1]
    )
    production = (
        _planting_subquery(FarmerProduction, season_name, crop_season, farmer_ref)
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
