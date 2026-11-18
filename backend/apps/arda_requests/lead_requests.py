"""Lead farmer input requests: one consolidated request per lead farmer, programme, year and season.

A lead farmer lists their farmers, each with a crop, hectares and the products wanted. Products
come from the programme's own input request for that crop and year, so quantities and prices
come from the programme catalogue. The lead farmer submits the whole request once; Admin approves
or rejects it as one. Approving turns every farmer line into that farmer's input allocation, using
the programme request's hectares, in one transaction: if any farmer cannot be allocated, nothing is.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.farmers.models import Farmer
from apps.programmes.models import INPUT_CATEGORY_CHOICES, Crop

from .models import ARDARequestBatch, LeadRequest, LeadRequestLine, RequestBatchLine

CATEGORY_LABELS = dict(INPUT_CATEGORY_CHOICES)
SEASON_LABELS = dict(LeadRequest.SEASON_CHOICES)
EDITABLE = (LeadRequest.STATUS_DRAFT, LeadRequest.STATUS_REJECTED)
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


class LeadRequestError(ValueError):
    pass


def _name(requirement):
    return requirement.input_product.name if requirement.input_product_id else requirement.item_name


def programme_request_for(*, programme, crop, season):
    """The programme's own input request for this crop and year. Lead farmer requests draw on it."""
    return (
        ARDARequestBatch.objects.filter(programme=programme, season=season, crop__iexact=crop.name, status=ARDARequestBatch.STATUS_APPROVED)
        .order_by("date_created", "pk")
        .first()
    )


def open_request(*, cluster, programme, season, crop_season, user=None):
    """Start a lead farmer's request for a programme, agricultural year and season."""
    if cluster is None:
        raise LeadRequestError("Choose the lead farmer's cluster.")
    if season is None:
        raise LeadRequestError("Choose the agricultural year.")
    if crop_season not in SEASON_LABELS:
        raise LeadRequestError("Choose Summer or Winter.")
    if not programme.is_active:
        raise LeadRequestError(f"{programme.name} is inactive, so it takes no new requests.")
    if programme.season_id and programme.season_id != season.pk:
        raise LeadRequestError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
    if not programme.supported_crops().filter(category=crop_season).exists():
        raise LeadRequestError(f"{programme.name} supports no {SEASON_LABELS[crop_season].lower()} crops.")
    existing = LeadRequest.objects.filter(cluster=cluster, programme=programme, season=season, crop_season=crop_season).first()
    if existing is not None:
        raise LeadRequestError(
            f"{cluster.name} already has a {programme.name} request for {season.name} {SEASON_LABELS[crop_season]}. Add to that request instead."
        )
    return LeadRequest.objects.create(
        cluster=cluster, programme=programme, season=season, crop_season=crop_season,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _editable(request):
    if request.status not in EDITABLE:
        raise LeadRequestError(f"This request is {request.get_status_display().lower()}, so its farmers can no longer be changed.")


@transaction.atomic
def save_line(*, request, farmer, crop, hectares, products, farm=None, line=None):
    """Add or change one farmer's crop, hectares and products in a lead farmer's request."""
    from apps.inputs.programme_allocation import crop_hectares

    request = LeadRequest.objects.select_for_update().get(pk=request.pk)
    _editable(request)
    if farmer is None or farmer.cluster_id != request.cluster_id:
        raise LeadRequestError(f"Choose a farmer in {request.cluster.name}.")
    if crop is None:
        raise LeadRequestError("Choose the crop.")
    if crop.category != request.crop_season:
        raise LeadRequestError(f"{crop.name} is not a {SEASON_LABELS[request.crop_season].lower()} crop.")
    if not request.programme.supports_crop(crop):
        raise LeadRequestError(f"{request.programme.name} does not support {crop.name}.")
    if farm is not None and farm.farmer_id != farmer.pk:
        raise LeadRequestError("Choose a farm belonging to this farmer.")
    try:
        area = Decimal(str(hectares)).quantize(TWO)
    except Exception as error:
        raise LeadRequestError("Enter the hectares as a number.") from error
    if area <= 0:
        raise LeadRequestError("Enter hectares greater than zero.")
    limit = crop_hectares(farmer, crop, request.season)
    if limit is not None and area > limit:
        raise LeadRequestError(f"{farmer.full_name} was allocated {limit.normalize():f} ha of {crop.name} for {request.season.name}.")
    batch = programme_request_for(programme=request.programme, crop=crop, season=request.season)
    if batch is None:
        raise LeadRequestError(f"{request.programme.name} has no input request for {crop.name} in {request.season.name} yet.")
    chosen = list(RequestBatchLine.objects.select_related("requirement__input_product").filter(batch=batch, pk__in=products or []))
    if len(chosen) != len(set(products or [])):
        raise LeadRequestError(f"Choose products from {request.programme.name}'s {crop.name} request ({batch.request_number}).")
    if not chosen:
        raise LeadRequestError("Choose at least one product or variety.")
    if len([item for item in chosen if item.requirement.input_category == "SEED"]) > 1:
        raise LeadRequestError("Choose one seed variety: each hectare is planted with one.")
    if any(not item.requirement.active or not item.approved_hectares for item in chosen):
        raise LeadRequestError("One of the chosen products is no longer available in the programme request.")
    duplicate = LeadRequestLine.objects.filter(request=request, farmer=farmer, crop=crop)
    if line is not None:
        duplicate = duplicate.exclude(pk=line.pk)
    if duplicate.exists():
        raise LeadRequestError(f"{farmer.full_name} is already in this request for {crop.name}. Change that line instead.")
    if line is None:
        line = LeadRequestLine(request=request)
    line.farmer, line.farm, line.crop, line.hectares, line.batch = farmer, farm, crop, area, batch
    line.save()
    line.products.set(chosen)
    return line


@transaction.atomic
def delete_line(line):
    request = LeadRequest.objects.select_for_update().get(pk=line.request_id)
    _editable(request)
    line.delete()


@transaction.atomic
def submit(request, *, user=None):
    request = LeadRequest.objects.select_for_update().get(pk=request.pk)
    _editable(request)
    if not request.lines.exists():
        raise LeadRequestError("Add at least one farmer before submitting.")
    request.status = LeadRequest.STATUS_SUBMITTED
    request.submitted_by = user if getattr(user, "is_authenticated", False) else None
    request.submitted_at = timezone.now()
    request.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
    return request


@transaction.atomic
def approve(request, *, user=None, notes=""):
    """Approve the whole request: every farmer line becomes an input allocation, or none does."""
    from apps.inputs.programme_allocation import AllocationError, confirm

    request = LeadRequest.objects.select_for_update().select_related("programme", "season", "cluster").get(pk=request.pk)
    if request.status != LeadRequest.STATUS_SUBMITTED:
        raise LeadRequestError(f"Only a submitted request can be approved. This one is {request.get_status_display().lower()}.")
    problems = []
    for line in request.lines.select_related("farmer", "farm", "crop", "batch").prefetch_related("products"):
        try:
            allocation = confirm(
                farmer=line.farmer, farm=line.farm, season=request.season, crop=line.crop, hectares=line.hectares,
                programme=request.programme, batch=line.batch, request_lines=[item.pk for item in line.products.all()], user=user,
            )
        except AllocationError as error:
            problems.append(f"{line.farmer.full_name} ({line.crop.name}): {error}")
            continue
        line.allocation = allocation
        line.save(update_fields=["allocation"])
    if problems:
        # Nothing is allocated unless every farmer can be.
        transaction.set_rollback(True)
        raise LeadRequestError("The request was not approved. " + " ".join(problems))
    request.status = LeadRequest.STATUS_APPROVED
    request.decided_by = user if getattr(user, "is_authenticated", False) else None
    request.decided_at = timezone.now()
    request.decision_notes = (notes or "").strip()
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "updated_at"])
    return request


@transaction.atomic
def reject(request, *, user=None, notes=""):
    request = LeadRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != LeadRequest.STATUS_SUBMITTED:
        raise LeadRequestError(f"Only a submitted request can be rejected. This one is {request.get_status_display().lower()}.")
    if not (notes or "").strip():
        raise LeadRequestError("Give the reason, so the lead farmer can correct the request.")
    request.status = LeadRequest.STATUS_REJECTED
    request.decided_by = user if getattr(user, "is_authenticated", False) else None
    request.decided_at = timezone.now()
    request.decision_notes = notes.strip()
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_notes", "updated_at"])
    return request


def line_items(line):
    """Quantity and cost of each product on one farmer line, from the programme catalogue."""
    rows = []
    for product in line.products.all():
        requirement = product.requirement
        quantity = (line.hectares * requirement.rate_per_hectare).quantize(FOUR)
        price = Decimal(requirement.cost_per_unit or 0)
        rows.append({
            "request_line": product.pk, "input_category": requirement.input_category,
            "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
            "product_name": _name(requirement), "unit": requirement.unit, "rate_per_hectare": requirement.rate_per_hectare,
            "quantity": quantity, "unit_price": price, "cost": (quantity * price).quantize(TWO),
        })
    return rows


def totals(lines):
    """Consolidated quantities by crop, input type and product for a set of farmer lines."""
    grouped = {}
    farmers = set()
    for line in lines:
        farmers.add(line.farmer_id)
        for item in line_items(line):
            key = (line.crop.name, item["input_category"], item["product_name"], item["unit"])
            row = grouped.setdefault(key, {
                "crop": line.crop.name, "input_category": item["input_category"], "input_category_label": item["input_category_label"],
                "product_name": item["product_name"], "unit": item["unit"], "rate_per_hectare": item["rate_per_hectare"],
                "hectares": Decimal("0.00"), "quantity": Decimal("0.0000"), "cost": Decimal("0.00"), "farmers": set(),
            })
            row["hectares"] += line.hectares
            row["quantity"] += item["quantity"]
            row["cost"] += item["cost"]
            row["farmers"].add(line.farmer_id)
    order = {code: index for index, (code, _label) in enumerate(INPUT_CATEGORY_CHOICES)}
    rows = sorted(grouped.values(), key=lambda row: (row["crop"], order.get(row["input_category"], 9), row["product_name"]))
    for row in rows:
        row["farmers"] = len(row["farmers"])
    return {"rows": rows, "farmers": len(farmers)}


def farmer_options(request):
    """Farmers in the lead farmer's cluster."""
    return Farmer.objects.filter(cluster_id=request.cluster_id).order_by("full_name")


def season_crops(request):
    return Crop.objects.filter(pk__in=request.programme.supported_crops().values("pk"), category=request.crop_season).order_by("name")
