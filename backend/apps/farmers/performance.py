"""Cluster and lead-farmer performance from the register. No sample figures."""

from decimal import Decimal

from django.db.models import Q, Sum

from apps.production.models import FarmerProduction, SeasonalPlantingPlan
from apps.subscriptions.models import FarmerSubscription
from apps.subscriptions.services import SubscriptionPaymentService, allocated_hectares, cluster_compliance

from . import kyc
from .models import Farm, Farmer


def _percent(part, whole):
    return int(round(part / whole * 100)) if whole else 0


def _filters(queryset, request):
    province = request.query_params.get("province")
    district = request.query_params.get("district")
    ward = request.query_params.get("ward")
    lead = request.query_params.get("lead_member")
    cluster = request.query_params.get("cluster")
    status = request.query_params.get("verification_status")
    if province and str(province).isdigit():
        queryset = queryset.filter(province_id=int(province))
    if district and str(district).isdigit():
        queryset = queryset.filter(district_id=int(district))
    if ward and str(ward).isdigit():
        queryset = queryset.filter(ward_id=int(ward))
    if cluster and str(cluster).isdigit():
        queryset = queryset.filter(cluster_id=int(cluster))
    if lead and str(lead).isdigit():
        queryset = queryset.filter(cluster__lead_member_id=int(lead))
    if status:
        queryset = queryset.filter(verification_status__in=[part.strip() for part in status.split(",") if part.strip()])
    return queryset


def build_cluster_performance(queryset, request):
    season_name = request.query_params.get("season_name") or ""
    farmers = list(
        _filters(queryset, request)
        .select_related("province", "district", "ward", "cluster", "cluster__lead_member", "cluster__lead_member__province", "cluster__lead_member__district", "cluster__lead_member__ward", "cluster__province", "cluster__district")
        .order_by("cluster__name", "surname")
    )
    ids = [farmer.pk for farmer in farmers]
    # The rate follows the crop hectares allocated for the year, not the farm size.
    allocated_ha = allocated_hectares(ids, season_name)
    paid = {}
    if season_name:
        for subscription in FarmerSubscription.objects.filter(farmer_id__in=ids, season__iexact=season_name):
            paid[subscription.farmer_id] = subscription.paid_amount
    planting = set(SeasonalPlantingPlan.objects.filter(farmer_id__in=ids, season__name__iexact=season_name).values_list("farmer_id", flat=True)) if season_name else set()
    producing = set(FarmerProduction.objects.filter(farmer_id__in=ids, season__name__iexact=season_name).values_list("farmer_id", flat=True)) if season_name else set()

    groups = {}
    for farmer in farmers:
        cluster = farmer.cluster
        key = cluster.pk if cluster is not None else 0
        group = groups.get(key)
        if group is None:
            lead = cluster.lead_member if cluster is not None and cluster.lead_member_id else None
            group = {
                "cluster_id": cluster.pk if cluster is not None else None,
                "cluster": cluster.name if cluster is not None else "No lead farmer",
                "lead_farmer": lead.full_name if lead is not None else "",
                "lead_member": lead.pk if lead is not None else None,
                "province": lead.province.name if lead is not None and lead.province_id else (cluster.province.name if cluster is not None else ""),
                "district": lead.district.name if lead is not None and lead.district_id else (cluster.district.name if cluster is not None and cluster.district_id else ""),
                "ward": lead.ward.name if lead is not None and lead.ward_id else "",
                "farmers": 0,
                "approved": 0,
                "pending": 0,
                "incomplete": 0,
                "_expected": {},
                "_participating": 0,
            }
            groups[key] = group
        if group["lead_member"] and farmer.pk == group["lead_member"]:
            continue
        group["farmers"] += 1
        if farmer.verification_status in kyc.APPROVED_STATES:
            group["approved"] += 1
            _, _, expected = SubscriptionPaymentService.subscription_details(allocated_ha.get(farmer.pk, Decimal("0")))
            group["_expected"][farmer.pk] = expected
            if farmer.pk in planting or farmer.pk in producing:
                group["_participating"] += 1
        elif farmer.verification_status in kyc.AWAITING_REVIEW:
            group["pending"] += 1
        elif farmer.verification_status == Farmer.STATUS_DRAFT:
            group["incomplete"] += 1

    rows = []
    for group in groups.values():
        expected_by_farmer = group.pop("_expected")
        participating = group.pop("_participating")
        approved = group["approved"]
        # Amount paid over the amount that must be paid, across the group's approved farmers.
        group["subscription_compliance"] = cluster_compliance(expected_by_farmer, paid)
        group["agricultural_participation"] = _percent(participating, approved)
        pieces = [group["subscription_compliance"], group["agricultural_participation"], _percent(approved, group["farmers"])]
        group["performance"] = int(round(sum(pieces) / len(pieces))) if group["farmers"] else 0
        rows.append(group)
    rows.sort(key=lambda row: (-row["farmers"], row["cluster"]))

    sizes = [row["farmers"] for row in rows if row["cluster_id"]]
    counted = [farmer for farmer in farmers if not (farmer.cluster_id and farmer.cluster.lead_member_id == farmer.pk)]
    land = _land_and_production([farmer.pk for farmer in counted], season_name, allocated_ha)
    return {
        "season": season_name,
        "overview": {
            "clusters": len(sizes),
            "lead_farmers": sum(1 for row in rows if row["lead_member"]),
            "farmers": sum(row["farmers"] for row in rows),
            "average_cluster_size": int(round(sum(sizes) / len(sizes))) if sizes else 0,
            "largest_cluster": max(sizes) if sizes else 0,
            "smallest_cluster": min(sizes) if sizes else 0,
            "awaiting_approval": sum(row["pending"] for row in rows),
            "approved": sum(row["approved"] for row in rows),
            "incomplete": sum(row["incomplete"] for row in rows),
            **land,
        },
        "clusters": rows,
        "by_province": _distribution(counted, "province"),
        "by_district": _distribution(counted, "district"),
        "by_ward": _distribution(counted, "ward"),
    }


def _distribution(farmers, field):
    counts = {}
    for farmer in farmers:
        place = getattr(farmer, field, None)
        label = place.name if place is not None else "Not recorded"
        counts[label] = counts.get(label, 0) + 1
    return [{"label": label, "farmers": count} for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _land_and_production(ids, season_name, allocated_ha):
    """Hectares and tonnes for the filtered farmers, from their own records."""
    zero = Decimal("0.00")
    irrigated = Farm.objects.filter(farmer_id__in=ids, is_active=True).aggregate(total=Sum("irrigated_hectares"))["total"] or zero
    production = {"actual": zero, "estimated": zero, "harvested_area": zero}
    if season_name and ids:
        totals = FarmerProduction.objects.filter(farmer_id__in=ids, season__name__iexact=season_name).aggregate(
            actual=Sum("actual_production"),
            estimated=Sum("estimated_production"),
            # Yield is measured on land that has been harvested, so crops still growing do not lower it.
            harvested_area=Sum("planted_hectares", filter=Q(actual_production__gt=0)),
        )
        production = {key: value or zero for key, value in totals.items()}
    crop_hectares = sum((allocated_ha.get(farmer_id, zero) for farmer_id in ids), zero)
    average_yield = (production["actual"] / production["harvested_area"]) if production["harvested_area"] else zero
    return {
        "crop_hectares": f"{crop_hectares.quantize(Decimal('0.01'))}",
        "irrigated_hectares": f"{Decimal(irrigated).quantize(Decimal('0.01'))}",
        "production_tonnes": f"{production['actual'].quantize(Decimal('0.01'))}",
        "estimated_production_tonnes": f"{production['estimated'].quantize(Decimal('0.01'))}",
        "average_yield_tonnes_per_hectare": f"{Decimal(average_yield).quantize(Decimal('0.01'))}",
    }
