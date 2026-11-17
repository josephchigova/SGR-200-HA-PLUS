"""Input allocation: programme -> programme crop catalogue -> approved input request -> farmer.

An allocation names one programme, one of its crops and one approved input request for that
crop and agricultural year. The programme's own catalogue gives the products, quantity per
hectare and unit price; the approved request gives the hectares that may be allocated.
Confirming the allocation uses those hectares, keeps a snapshot of every product and price
on its lines, and records the cost as the farmer's input debt.

A farmer can receive Seed from one programme and Fertilizer from another as two allocations,
but never the same input type twice for the same crop and year.
"""

from decimal import ROUND_CEILING, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.arda_requests import stock
from apps.arda_requests.models import ARDARequestBatch
from apps.arda_requests.services import batch_figures, line_figures
from apps.farmers.models import Farmer, RegistrationCropAllocation
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.production.models import FarmerProduction
from apps.programmes.models import INPUT_CATEGORIES, INPUT_CATEGORY_CHOICES, CropInputRequirement, Programme
from apps.programmes.services import CropPricingService
from apps.recovery.models import InputDebt
from apps.recovery.services import RecoveryCalculationService

from .models import InputAllocation, InputAllocationLine

CATEGORY_LABELS = dict(INPUT_CATEGORY_CHOICES)
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


class AllocationError(ValueError):
    pass


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except Exception as error:
        raise AllocationError("Enter hectares as a number.") from error


def crop_hectares(farmer, crop, season):
    """Hectares of this crop the farmer was allocated for the year: registration crops first, then production records."""
    allocated = RegistrationCropAllocation.objects.filter(farmer=farmer, crop=crop, season=season).aggregate(total=Sum("hectares"))["total"]
    if allocated:
        return Decimal(allocated)
    contracted = FarmerProduction.objects.filter(farmer=farmer, season=season, crop__iexact=crop.name).aggregate(total=Sum("contracted_hectares"))["total"]
    return Decimal(contracted) if contracted else None


def programmes_for(*, crop, season):
    """Active programmes of this agricultural year that support the crop."""
    programmes = Programme.objects.filter(is_active=True).filter(Q(season=season) | Q(season__isnull=True)).order_by("name")
    return [programme for programme in programmes if programme.supports_crop(crop)]


def approved_batches(*, programme, crop, season):
    return ARDARequestBatch.objects.filter(
        programme=programme, status=ARDARequestBatch.STATUS_APPROVED, crop__iexact=crop.name, season=season,
    ).order_by("date_created", "pk")


def _catalogue(programme, crop, category):
    return list(
        CropInputRequirement.objects.select_related("input_product").filter(
            crop=crop, programme=programme, input_category=category, active=True, input_product__isnull=False,
        ).order_by("input_product__name", "id")
    )


def covered_categories(*, farmer, crop, season, exclude_allocation_id=None):
    """Input types the farmer already has a live allocation for, for this crop and year."""
    existing = InputAllocation.objects.filter(farmer=farmer).exclude(status=InputAllocation.STATUS_CANCELLED)
    existing = existing.filter(Q(crop_reference=crop) | Q(crop_reference__isnull=True, crop__iexact=crop.name))
    existing = existing.filter(Q(season=season) | Q(season__isnull=True, programme__season=season))
    if exclude_allocation_id:
        existing = existing.exclude(pk=exclude_allocation_id)
    covered = {}
    for allocation in existing.select_related("programme"):
        categories = {code for code in allocation.calculation_lines.values_list("input_category", flat=True) if code}
        # Older allocations took every input from one programme.
        for code in categories or INPUT_CATEGORIES:
            covered.setdefault(code, allocation)
    return covered


def programme_options(*, crop, season, farmer=None):
    """Programmes that can supply this crop and year, with their approved requests and catalogue."""
    covered = covered_categories(farmer=farmer, crop=crop, season=season) if farmer is not None else {}
    options = []
    for programme in programmes_for(crop=crop, season=season):
        catalogue = {}
        for category in programme.input_categories or []:
            catalogue[category] = [
                {
                    "requirement": requirement.id, "input_product": requirement.input_product_id,
                    "name": requirement.input_product.name, "unit": requirement.unit or requirement.input_product.unit,
                    "rate_per_hectare": str(requirement.rate_per_hectare),
                    "unit_price": str(requirement.cost_per_unit) if requirement.cost_per_unit is not None else None,
                    "pack_label": requirement.pack_label, "pack_size": str(requirement.pack_size) if requirement.pack_size else None,
                }
                for requirement in _catalogue(programme, crop, category)
            ]
        batches = []
        for batch in approved_batches(programme=programme, crop=crop, season=season):
            figures = batch_figures(batch)
            products = []
            for line in batch.lines.select_related("requirement__input_product"):
                line_numbers = line_figures(line)
                if line_numbers["approved_hectares"] <= 0:
                    continue
                requirement = line.requirement
                products.append({
                    "id": line.id, "requirement": requirement.id, "input_category": requirement.input_category,
                    "name": requirement.input_product.name if requirement.input_product_id else requirement.item_name,
                    "unit": requirement.unit, "rate_per_hectare": str(requirement.rate_per_hectare),
                    "unit_price": str(requirement.cost_per_unit) if requirement.cost_per_unit is not None else None,
                    "approved_hectares": str(line_numbers["approved_hectares"]),
                    "remaining_hectares": str(line_numbers["available_hectares"]),
                })
            batches.append({
                "id": batch.id, "request_number": batch.request_number, "products": products,
                "input_category": batch.input_category,
                "input_category_label": batch.get_input_category_display() if batch.input_category else "All of the programme's inputs",
                "approved_hectares": str(figures["approved_hectares"]),
                "allocated_hectares": str(figures["allocated_hectares"]),
                "remaining_hectares": str(figures["available_hectares"]),
            })
        options.append({
            "programme": programme.id,
            "programme_name": programme.name,
            "input_categories": programme.input_categories or [],
            "catalogue": catalogue,
            "batches": batches,
        })
    return {
        "options": options,
        "covered": {code: {"programme_name": allocation.programme.name, "allocation": allocation.pk} for code, allocation in covered.items()},
    }


def _requested_products(*, batch, programme, crop, allowed, covered, request_lines, input_categories):
    """The products an allocation takes from a request that names its products and varieties.

    Returns {category: [(catalogue line, request line)]}. Only approved lines can be used, at
    most one seed variety, and never an input type the farmer already has for this crop.
    """
    approved = [line for line in batch.lines.select_related("requirement__input_product") if (line.approved_hectares or 0) > 0]
    by_id = {line.pk: line for line in approved}

    def label(line):
        return line.requirement.input_product.name if line.requirement.input_product_id else line.requirement.item_name

    if request_lines:
        picked = []
        for value in request_lines:
            line = by_id.get(int(value)) if str(value).isdigit() else None
            if line is None:
                raise AllocationError(f"Choose products approved in input request {batch.request_number}.")
            picked.append(line)
    else:
        wanted = {str(item).upper() for item in input_categories or []}
        picked = []
        for line in approved:
            category = line.requirement.input_category
            if category in covered or (wanted and category not in wanted):
                continue
            picked.append(line)
        seeds = [line for line in picked if line.requirement.input_category == "SEED"]
        if len(seeds) > 1:
            raise AllocationError(f"Choose the seed variety: {', '.join(label(line) for line in seeds)}.")
    if not picked:
        raise AllocationError(f"Input request {batch.request_number} has no approved products left for this farmer.")
    if len([line for line in picked if line.requirement.input_category == "SEED"]) > 1:
        raise AllocationError("Choose one seed variety: each hectare is planted with one.")
    selected = {}
    for line in picked:
        requirement = line.requirement
        category = requirement.input_category
        if category not in allowed:
            raise AllocationError(f"{programme.name} does not supply {CATEGORY_LABELS.get(category, category).lower()} for this request.")
        if category in covered:
            raise AllocationError(
                f"The farmer already has {CATEGORY_LABELS[category].lower()} for {crop.name} from {covered[category].programme.name}. "
                "Cancel that allocation first."
            )
        if not requirement.active:
            raise AllocationError(f"{label(line)} is switched off in {programme.name}'s catalogue.")
        selected.setdefault(category, []).append((requirement, line))
    return {category: selected[category] for category in INPUT_CATEGORIES if category in selected}


def build_plan(*, farmer, farm, season, crop, hectares, programme, batch, input_categories=None, request_lines=None, exclude_allocation_id=None):
    """Work out every line of an allocation from the database. Returns the plan and the problems that block it.

    Nothing the browser sends about products, prices, quantities or hectares left is trusted:
    all of it is read here.
    """
    if season is None:
        raise AllocationError("Select the agricultural year.")
    if crop is None:
        raise AllocationError("Select the crop.")
    if programme is None:
        raise AllocationError("Select the programme.")
    if batch is None:
        raise AllocationError("Select the approved input request to allocate from.")
    area = _decimal(hectares).quantize(TWO)
    if area <= 0:
        raise AllocationError("Enter hectares greater than zero.")

    # Programme, crop, year and request must all belong together.
    if not programme.is_active:
        raise AllocationError(f"{programme.name} is inactive, so it cannot receive new allocations.")
    if programme.season_id and programme.season_id != season.pk:
        raise AllocationError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
    if not programme.supports_crop(crop):
        raise AllocationError(f"{programme.name} does not support {crop.name}.")
    if batch.programme_id != programme.pk:
        raise AllocationError(f"Input request {batch.request_number} belongs to {batch.programme.name}, not {programme.name}.")
    if (batch.crop or "").strip().lower() != crop.name.lower():
        raise AllocationError(f"Input request {batch.request_number} is for {batch.crop or 'no crop'}, not {crop.name}.")
    if batch.season_id != season.pk:
        raise AllocationError(f"Input request {batch.request_number} is for {batch.season.name if batch.season_id else 'no year'}, not {season.name}.")
    if batch.status != ARDARequestBatch.STATUS_APPROVED:
        raise AllocationError(f"Input request {batch.request_number} is {batch.get_status_display().lower()}. Only approved requests can be allocated from.")

    supplied = programme.input_categories or []
    if not supplied:
        raise AllocationError(f"{programme.name} has no input types. Choose Seed, Fertilizer or Chemicals on the programme first.")
    allowed = [batch.input_category] if batch.input_category else supplied
    allowed = [code for code in INPUT_CATEGORIES if code in allowed and code in supplied]

    eligibility = FarmerApprovalEligibilityService.evaluate_for_arda(farmer, season)
    if not eligibility["eligible"]:
        raise AllocationError("This farmer cannot receive inputs yet: " + " ".join(eligibility["reasons"]))
    selected_farm = farm or farmer.farms.filter(is_active=True).order_by("id").first()
    if selected_farm is None or selected_farm.farmer_id != farmer.pk:
        raise AllocationError("Select a farm belonging to this farmer.")
    limit = crop_hectares(farmer, crop, season)
    if limit is not None and area > limit:
        raise AllocationError(f"{farmer.full_name} was allocated {limit.normalize():f} ha of {crop.name} for {season.name}. Allocate inputs for at most that.")
    if limit is None and area > Decimal(selected_farm.arable_hectares or 0):
        raise AllocationError("Hectares exceed the farm's arable land.")

    covered = covered_categories(farmer=farmer, crop=crop, season=season, exclude_allocation_id=exclude_allocation_id)
    if batch.lines.exists():
        # The request names its products and varieties: allocate exactly those, as approved.
        selected = _requested_products(
            batch=batch, programme=programme, crop=crop, allowed=allowed, covered=covered,
            request_lines=request_lines, input_categories=input_categories,
        )
        chosen = list(selected)
    elif input_categories:
        chosen = [code for code in INPUT_CATEGORIES if code in {str(item).upper() for item in input_categories}]
        outside = [CATEGORY_LABELS.get(code, code) for code in chosen if code not in allowed]
        if outside or not chosen:
            raise AllocationError(f"Input request {batch.request_number} of {programme.name} does not cover {', '.join(outside) or 'that'}.")
        repeated = [code for code in chosen if code in covered]
        if repeated:
            first = covered[repeated[0]]
            raise AllocationError(
                f"{farmer.full_name} already has {', '.join(CATEGORY_LABELS[code].lower() for code in repeated)} for {crop.name} "
                f"in {season.name} from {first.programme.name}. Cancel that allocation first."
            )
    else:
        chosen = [code for code in allowed if code not in covered and _catalogue(programme, crop, code)]
        if not chosen:
            raise AllocationError(f"{farmer.full_name} already has every input {programme.name} supplies for {crop.name} in {season.name}.")

    problems = []
    categories = []
    lines = []
    total_cost = Decimal("0.00")
    for category in chosen:
        if batch.lines.exists():
            pairs = selected[category]
        else:
            pairs = [(requirement, None) for requirement in _catalogue(programme, crop, category)]
        requirements = [requirement for requirement, _line in pairs]
        if not requirements:
            raise AllocationError(f"{programme.name} has no {CATEGORY_LABELS[category].lower()} in its {crop.name} catalogue. Add it in the Crop Catalogue.")
        unpriced = [requirement.input_product.name for requirement in requirements if not requirement.cost_per_unit or requirement.cost_per_unit <= 0]
        if unpriced:
            raise AllocationError(f"{programme.name}: set a unit price for {', '.join(unpriced)} in the Crop Catalogue.")
        category_cost = Decimal("0.00")
        category_lines = []
        for requirement, request_line in pairs:
            required = (area * requirement.rate_per_hectare).quantize(FOUR)
            price = Decimal(requirement.cost_per_unit)
            cost = (required * price).quantize(TWO)
            packs = (required / requirement.pack_size).to_integral_value(rounding=ROUND_CEILING) if requirement.pack_size else None
            entry = {
                "category": category, "programme": programme, "requirement": requirement,
                "input_product": requirement.input_product, "unit": requirement.unit or requirement.input_product.unit,
                "rate_per_hectare": requirement.rate_per_hectare, "unit_price": price,
                "pack_label": requirement.pack_label, "pack_size": requirement.pack_size, "pack_price": requirement.pack_price,
                "packs": packs, "required_quantity": required, "cost": cost,
                "request_line": request_line, "line_figures": None,
            }
            if request_line is not None:
                # Each product or variety has its own approved hectares.
                numbers = line_figures(request_line, exclude_allocation_id=exclude_allocation_id)
                entry["line_figures"] = numbers
                if area > numbers["available_hectares"]:
                    problems.append(
                        f"{requirement.input_product.name} has {numbers['available_hectares'].normalize():f} ha of its "
                        f"{numbers['approved_hectares'].normalize():f} approved hectares left in {batch.request_number}, "
                        f"and this allocation needs {area.normalize():f} ha."
                    )
            category_cost += cost
            category_lines.append(entry)
            lines.append(entry)
        total_cost += category_cost
        categories.append({"category": category, "label": CATEGORY_LABELS[category], "lines": category_lines, "total_cost": category_cost})

    figures = batch_figures(batch, exclude_allocation_id=exclude_allocation_id)
    if area > figures["available_hectares"]:
        problems.append(
            f"Input request {batch.request_number} has {figures['available_hectares'].normalize():f} ha of its "
            f"{figures['approved_hectares'].normalize():f} approved hectares left, and this allocation needs {area.normalize():f} ha."
        )
    return {
        "farmer": farmer, "farm": selected_farm, "season": season, "crop": crop, "hectares": area,
        "programme": programme, "batch": batch, "batch_figures": figures,
        "crop_hectares_limit": limit, "categories": categories, "lines": lines,
        "total_cost": total_cost.quantize(TWO), "problems": problems,
    }


def serialize_plan(plan, *, show_money=True):
    def money(value):
        return str(Decimal(value).quantize(TWO)) if show_money and value is not None else None

    def qty(value):
        return format(Decimal(value).quantize(FOUR).normalize(), "f")

    figures = plan["batch_figures"]
    return {
        "farmer": plan["farmer"].pk, "farmer_name": plan["farmer"].full_name, "farm": plan["farm"].pk,
        "season": plan["season"].pk, "season_name": plan["season"].name,
        "crop": plan["crop"].pk, "crop_name": plan["crop"].name, "crop_season": plan["crop"].get_category_display(),
        "programme": plan["programme"].pk, "programme_name": plan["programme"].name,
        "request_batch": plan["batch"].pk, "request_number": plan["batch"].request_number,
        "hectares": str(plan["hectares"]),
        "crop_hectares_limit": str(plan["crop_hectares_limit"]) if plan["crop_hectares_limit"] is not None else None,
        "approved_hectares": str(figures["approved_hectares"]),
        "allocated_hectares": str(figures["allocated_hectares"]),
        "remaining_hectares": str(figures["available_hectares"]),
        "remaining_after": str(figures["available_hectares"] - plan["hectares"]),
        "total_cost": money(plan["total_cost"]),
        "problems": plan["problems"],
        "can_confirm": not plan["problems"],
        "categories": [
            {
                "category": entry["category"], "label": entry["label"], "total_cost": money(entry["total_cost"]),
                "lines": [
                    {
                        "input_product": line["input_product"].pk, "product_name": line["input_product"].name, "unit": line["unit"],
                        "rate_per_hectare": qty(line["rate_per_hectare"]), "required_quantity": qty(line["required_quantity"]),
                        "pack_label": line["pack_label"], "packs": str(line["packs"]) if line["packs"] is not None else None,
                        "request_line": line["request_line"].pk if line["request_line"] else None,
                        "approved_hectares": str(line["line_figures"]["approved_hectares"]) if line["line_figures"] else None,
                        "remaining_hectares": str(line["line_figures"]["available_hectares"]) if line["line_figures"] else None,
                        "unit_price": money(line["unit_price"]), "cost": money(line["cost"]),
                    }
                    for line in entry["lines"]
                ],
            }
            for entry in plan["categories"]
        ],
    }


@transaction.atomic
def confirm(*, farmer, farm, season, crop, hectares, programme, batch, input_categories=None, request_lines=None, user=None, crop_season=None):
    """Make the allocation: lock the farmer and the request, re-check everything, then record it."""
    if crop_season and crop is not None and crop.category != crop_season:
        raise AllocationError(f"{crop.name} is not a {'Summer' if crop_season == 'SUMMER' else 'Winter'} crop.")
    # One allocation at a time per farmer, so a double click cannot create two.
    farmer = Farmer.objects.select_for_update().get(pk=farmer.pk)
    # One allocation at a time per request, so two users cannot both take its last hectares.
    if batch is not None:
        batch = ARDARequestBatch.objects.select_for_update(of=("self",)).select_related("programme", "season").get(pk=batch.pk)
    plan = build_plan(
        farmer=farmer, farm=farm, season=season, crop=crop, hectares=hectares,
        programme=programme, batch=batch, input_categories=input_categories, request_lines=request_lines,
    )
    if plan["problems"]:
        raise AllocationError(" ".join(plan["problems"]))
    actor = user if getattr(user, "is_authenticated", False) else None
    selling_price = CropPricingService.resolve_price_per_tonne(crop=crop, season=season)
    rate_total = sum((line["rate_per_hectare"] * line["unit_price"] for line in plan["lines"]), Decimal("0"))
    allocation = InputAllocation.objects.create(
        farmer=farmer, farm=plan["farm"], programme=programme, season=season, crop_reference=crop, crop=crop.name,
        request_batch=batch, hectares=plan["hectares"], total_input_cost=plan["total_cost"],
        calculated_input_cost_per_hectare=rate_total.quantize(TWO), allocation_reference=batch.request_number,
        status=InputAllocation.STATUS_ALLOCATED, sourced_by_category=True, created_by=actor,
    )
    for line in plan["lines"]:
        InputAllocationLine.objects.create(
            allocation=allocation, source_requirement=line["requirement"], input_category=line["category"],
            programme=programme, input_product=line["input_product"], request_line=line["request_line"],
            group_name=CATEGORY_LABELS[line["category"]], item_name=line["input_product"].name, unit=line["unit"],
            rate_per_hectare=line["rate_per_hectare"], cost_per_unit=line["unit_price"],
            pack_label=line["pack_label"], pack_size=line["pack_size"], pack_price=line["pack_price"],
            cost_per_hectare=(line["rate_per_hectare"] * line["unit_price"]).quantize(FOUR),
            required_quantity=line["required_quantity"], calculated_cost=line["cost"], included_in_total=True,
        )
    RecoveryCalculationService.create_or_update_from_allocation(allocation=allocation, selling_price_per_tonne=selling_price)
    return allocation


@transaction.atomic
def cancel(*, allocation, reason, user=None):
    """Reverse an allocation: its hectares go back to the request and the debt is cancelled. Nothing is deleted."""
    reason = (reason or "").strip()
    if not reason:
        raise AllocationError("Give the reason for cancelling this allocation.")
    allocation = InputAllocation.objects.select_for_update().get(pk=allocation.pk)
    if allocation.status == InputAllocation.STATUS_CANCELLED:
        raise AllocationError("This allocation is already cancelled.")
    debt = InputDebt.objects.select_for_update().filter(input_allocation=allocation).first()
    if debt is not None and debt.recovered_tonnes > 0:
        raise AllocationError("Grain has already been recovered against this allocation, so it cannot be cancelled.")
    actor = user if getattr(user, "is_authenticated", False) else None
    # Allocations made while requests held product stock return that stock too.
    lines = list(allocation.calculation_lines.filter(batch_input__isnull=False))
    locked = stock.lock([line.batch_input_id for line in lines])
    for line in lines:
        stock.reverse(locked[line.batch_input_id], line.required_quantity, allocation=allocation, allocation_line=line, reason=reason, user=actor)
    allocation.status = InputAllocation.STATUS_CANCELLED
    allocation.cancelled_at = timezone.now()
    allocation.cancelled_by = actor
    allocation.cancellation_reason = reason
    allocation.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason", "updated_at"])
    if debt is not None:
        # The debt row stays as history; nothing is owed on a reversed allocation.
        debt.total_debt = Decimal("0.00")
        debt.required_recovery_tonnes = Decimal("0.00")
        debt.outstanding_tonnes = Decimal("0.00")
        debt.outstanding_monetary_balance = Decimal("0.00")
        debt.status = InputDebt.STATUS_CANCELLED
        debt.save(update_fields=["total_debt", "required_recovery_tonnes", "outstanding_tonnes", "outstanding_monetary_balance", "status", "updated_at"])
    return allocation
