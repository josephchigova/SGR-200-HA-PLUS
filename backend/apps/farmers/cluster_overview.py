"""Cluster performance for a lead farmer, in counts and percentages only."""

from decimal import Decimal

from django.db.models import Sum

from apps.accounts.privacy import compliance_label, compliance_percent
from apps.inputs.models import InputAllocation
from apps.production.models import FarmerProduction, SeasonalPlantingPlan
from apps.subscriptions.models import FarmerSubscription
from apps.subscriptions.services import SubscriptionPaymentService

from . import kyc
from .models import Farm, Farmer, FarmerDocument, RegistrationCropAllocation


def _percent(part, whole):
    return int(round(part / whole * 100)) if whole else 0


def build_cluster_overview(farmers, user, season_name, cluster=None):
    # The lead farmer's own record is the cluster, not one of its members.
    farmers = farmers.exclude(is_lead=True).select_related("district", "ward", "cluster")
    rows = list(farmers.order_by("surname", "first_name"))
    ids = [farmer.pk for farmer in rows]
    approved = [farmer for farmer in rows if farmer.verification_status in kyc.APPROVED_STATES]
    approved_ids = {farmer.pk for farmer in approved}

    arable = {
        row["farmer_id"]: row["total"] or Decimal("0")
        for row in Farm.objects.filter(farmer_id__in=ids, is_active=True).values("farmer_id").annotate(total=Sum("arable_hectares"))
    }
    paid = {}
    if season_name:
        for subscription in FarmerSubscription.objects.filter(farmer_id__in=ids, season__iexact=season_name):
            paid[subscription.farmer_id] = subscription.paid_amount

    planting = set(SeasonalPlantingPlan.objects.filter(farmer_id__in=ids, season__name__iexact=season_name).values_list("farmer_id", flat=True)) if season_name else set()
    producing = set(FarmerProduction.objects.filter(farmer_id__in=ids, season__name__iexact=season_name).values_list("farmer_id", flat=True)) if season_name else set()
    allocated = set(
        InputAllocation.objects.filter(farmer_id__in=ids, programme__season__name__iexact=season_name)
        .exclude(status=InputAllocation.STATUS_CANCELLED).values_list("farmer_id", flat=True)
    ) if season_name else set()

    crops = {}
    for allocation in RegistrationCropAllocation.objects.filter(farmer_id__in=ids).select_related("crop", "season"):
        crops.setdefault(allocation.farmer_id, []).append(f"{allocation.crop.name} {allocation.hectares.normalize():f} ha ({allocation.season.name})")

    documents = {}
    for document in FarmerDocument.objects.filter(farmer_id__in=ids, document_type__in=kyc.REQUIRED_CODES):
        entry = documents.setdefault(document.farmer_id, {"uploaded": set(), "verified": set()})
        entry["uploaded"].add(document.document_type)
        if document.review_status == FarmerDocument.REVIEW_VERIFIED:
            entry["verified"].add(document.document_type)

    required = len(kyc.REQUIRED_CODES)
    farmer_rows = []
    compliance_values = []
    for farmer in rows:
        percent = None
        if farmer.pk in approved_ids:
            _, _, expected = SubscriptionPaymentService.subscription_details(arable.get(farmer.pk, Decimal("0")))
            percent = compliance_percent(expected, paid.get(farmer.pk, 0))
            compliance_values.append(percent)
        docs = documents.get(farmer.pk, {"uploaded": set(), "verified": set()})
        farmer_rows.append({
            "id": farmer.pk,
            "name": farmer.full_name,
            "membership_number": farmer.membership_number,
            "registration_date": farmer.registration_date.isoformat() if farmer.registration_date else "",
            "crops": crops.get(farmer.pk, []),
            "crop_allocated": farmer.pk in crops,
            "district": farmer.district.name if farmer.district_id else "",
            "ward": farmer.ward.name if farmer.ward_id else "",
            "verification_status": farmer.verification_status,
            "review_remarks": farmer.review_remarks,
            "arable_hectares": str(arable.get(farmer.pk, Decimal("0"))),
            "subscription_compliance": percent,
            "subscription_status": compliance_label(percent) if percent is not None else "Awaiting approval",
            "documents_uploaded": len(docs["uploaded"]),
            "documents_verified": len(docs["verified"]),
            "documents_required": required,
            "planting_recorded": farmer.pk in planting or farmer.pk in producing,
            "inputs_allocated": farmer.pk in allocated,
        })

    total = len(rows)
    count = lambda *states: sum(1 for farmer in rows if farmer.verification_status in states)  # noqa: E731
    awaiting = count(*kyc.AWAITING_REVIEW)
    kyc_complete = sum(1 for entry in documents.values() if len(entry["verified"]) >= required)
    participating = len((planting | producing) & approved_ids)
    if cluster is None and not user.is_superuser and user.role == user.ROLE_LEAD_FARMER:
        cluster = getattr(user, "assigned_cluster", None)
    return {
        "cluster": {
            "id": cluster.id, "name": cluster.name, "province": cluster.province.name,
            "district": cluster.district.name if cluster.district_id else "",
            "lead_farmer": cluster.lead_member.full_name if cluster.lead_member_id else "",
        } if cluster else None,
        "season": season_name,
        "counts": {
            "total": total,
            "approved": len(approved),
            "awaiting_approval": awaiting,
            "incomplete": count(Farmer.STATUS_DRAFT),
            "corrections_requested": count(Farmer.STATUS_CORRECTIONS),
            "rejected": count(Farmer.STATUS_REJECTED),
        },
        "performance": {
            "registration_progress": _percent(len(approved) + awaiting, total),
            "approval_progress": _percent(len(approved), total),
            "kyc_progress": _percent(kyc_complete, total),
            "subscription_compliance": int(round(sum(compliance_values) / len(compliance_values))) if compliance_values else 0,
            "subscription_complete": sum(1 for value in compliance_values if value >= 100),
            "subscription_in_progress": sum(1 for value in compliance_values if 0 < value < 100),
            "subscription_not_started": sum(1 for value in compliance_values if value == 0),
            "participation": _percent(participating, len(approved)),
            "seasonal_cropping": _percent(len(planting & approved_ids), len(approved)),
            "input_allocation": _percent(len(allocated & approved_ids), len(approved)),
            "crop_allocation": _percent(len(set(crops) & set(ids)), total),
        },
        "farmers": farmer_rows,
        "by_district": _places(farmer_rows, "district"),
        "by_ward": _places(farmer_rows, "ward"),
    }


def _places(rows, field):
    groups = {}
    for row in rows:
        label = row.get(field) or "Not recorded"
        bucket = groups.setdefault(label, {"label": label, "farmers": 0, "approved": 0, "pending": 0, "compliance": [], "participating": 0, "with_crops": 0})
        bucket["farmers"] += 1
        if row.get("crop_allocated"):
            bucket["with_crops"] += 1
        if row["verification_status"] in kyc.APPROVED_STATES:
            bucket["approved"] += 1
            if row["subscription_compliance"] is not None:
                bucket["compliance"].append(row["subscription_compliance"])
            if row["planting_recorded"]:
                bucket["participating"] += 1
        elif row["verification_status"] in kyc.AWAITING_REVIEW:
            bucket["pending"] += 1
    result = []
    for bucket in groups.values():
        values = bucket.pop("compliance")
        approved = bucket["approved"]
        bucket["subscription_compliance"] = int(round(sum(values) / len(values))) if values else 0
        bucket["agricultural_participation"] = _percent(bucket.pop("participating"), approved)
        bucket["crop_allocation"] = _percent(bucket.pop("with_crops"), bucket["farmers"])
        result.append(bucket)
    result.sort(key=lambda item: (-item["farmers"], item["label"]))
    return result
