"""Input allocation with Seed, Fertilizer and Chemicals each sourced from its own programme.

For a farmer, crop, agricultural year and number of hectares, each input category names
a programme (or is left out). The programme's catalogue gives the products, quantity per
hectare and unit price; the programme's request batch gives the stock. Confirming the
allocation takes the stock out of exactly that batch, records the price paid as a
snapshot on each line, and records the cost as the farmer's input debt.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.arda_requests import stock
from apps.arda_requests.models import RequestBatchInput
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
    except Exception as error:  # noqa: BLE001 - any bad number is a user error here
        raise AllocationError("Enter hectares as a number.") from error


def crop_hectares(farmer, crop, season):
    """Hectares of this crop the farmer was allocated for the year: registration crops first, then production records."""
    allocated = RegistrationCropAllocation.objects.filter(farmer=farmer, crop=crop, season=season).aggregate(total=Sum("hectares"))["total"]
    if allocated:
        return Decimal(allocated)
    contracted = FarmerProduction.objects.filter(farmer=farmer, season=season, crop__iexact=crop.name).aggregate(total=Sum("contracted_hectares"))["total"]
    return Decimal(contracted) if contracted else None


def eligible_batch_lines(programme, season, product_ids):
    lines = RequestBatchInput.objects.select_related("batch", "input_product").filter(
        batch__programme=programme,
        batch__status__in=stock.ALLOCATABLE_BATCH_STATUSES,
        input_product_id__in=product_ids,
    )
    if season is not None:
        lines = lines.filter(Q(batch__season=season) | Q(batch__season__isnull=True))
    return lines.order_by("batch__date_created", "batch_id", "id")


def programme_options(*, crop, season):
    """Programmes that can supply each category for this crop and year, with products, prices and batches."""
    requirements = (
        CropInputRequirement.objects.select_related("programme", "input_product")
        .filter(crop=crop, active=True, programme__isnull=False, input_product__isnull=False, input_category__in=INPUT_CATEGORIES)
        .filter(Q(programme__season=season) | Q(programme__season__isnull=True))
        .filter(programme__is_active=True)
        .order_by("programme__name", "input_category", "input_product__name")
    )
    grouped = {}
    for requirement in requirements:
        key = (requirement.input_category, requirement.programme_id)
        entry = grouped.setdefault(key, {"programme": requirement.programme, "requirements": []})
        entry["requirements"].append(requirement)
    options = {category: [] for category in INPUT_CATEGORIES}
    for (category, _), entry in grouped.items():
        programme = entry["programme"]
        product_ids = [requirement.input_product_id for requirement in entry["requirements"]]
        batches = {}
        for line in eligible_batch_lines(programme, season, product_ids):
            batch = batches.setdefault(line.batch_id, {
                "id": line.batch_id, "request_number": line.batch.request_number, "status": line.batch.status,
                "products": {},
            })
            batch["products"][line.input_product_id] = {
                "batch_input": line.id, "requested": str(line.requested_quantity), "allocated": str(line.allocated_quantity),
                "available": str(line.available_quantity), "unit": line.unit,
            }
        options[category].append({
            "programme": programme.id,
            "programme_name": programme.name,
            "programme_code": programme.code,
            "products": [
                {
                    "requirement": requirement.id, "input_product": requirement.input_product_id,
                    "name": requirement.input_product.name, "unit": requirement.unit or requirement.input_product.unit,
                    "rate_per_hectare": str(requirement.rate_per_hectare),
                    "unit_price": str(requirement.cost_per_unit) if requirement.cost_per_unit is not None else None,
                }
                for requirement in entry["requirements"]
            ],
            "batches": [
                {**batch, "covers_all_products": all(pid in batch["products"] for pid in product_ids), "products": batch["products"]}
                for batch in batches.values()
            ],
        })
    return options


def build_plan(*, farmer, farm, season, crop, hectares, selections, locked=None, exclude_allocation_id=None):
    """Work out every line of an allocation. Returns the plan and a list of problems that block confirming it."""
    if season is None:
        raise AllocationError("Select the agricultural year.")
    if crop is None:
        raise AllocationError("Select a crop from the crop catalogue.")
    area = _decimal(hectares).quantize(TWO)
    if area <= 0:
        raise AllocationError("Enter hectares greater than zero.")
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
    existing = InputAllocation.objects.filter(farmer=farmer, crop_reference=crop).exclude(status=InputAllocation.STATUS_CANCELLED)
    existing = existing.filter(Q(season=season) | Q(season__isnull=True, programme__season=season))
    if exclude_allocation_id:
        existing = existing.exclude(pk=exclude_allocation_id)
    if existing.exists():
        raise AllocationError(f"{farmer.full_name} already has an input allocation for {crop.name} in {season.name}. Cancel it before allocating again.")

    chosen = {category: (selections or {}).get(category) or {} for category in INPUT_CATEGORIES}
    if not any(choice.get("programme") for choice in chosen.values()):
        raise AllocationError("Choose a programme for at least one of Seed, Fertilizer or Chemicals.")

    problems = []
    categories = []
    lines = []
    total_cost = Decimal("0.00")
    for category in INPUT_CATEGORIES:
        choice = chosen[category]
        if not choice.get("programme"):
            categories.append({"category": category, "label": CATEGORY_LABELS[category], "programme": None, "lines": [], "total_cost": "0.00"})
            continue
        programme = Programme.objects.filter(pk=choice["programme"], is_active=True).first()
        if programme is None:
            raise AllocationError(f"Choose a valid programme for {CATEGORY_LABELS[category]}.")
        requirements = list(
            CropInputRequirement.objects.select_related("input_product").filter(
                crop=crop, programme=programme, input_category=category, active=True, input_product__isnull=False,
            ).order_by("input_product__name", "id")
        )
        if not requirements:
            raise AllocationError(f"{programme.name} has no {CATEGORY_LABELS[category].lower()} configured for {crop.name}. Add it in the Crop Catalogue.")
        unpriced = [requirement.input_product.name for requirement in requirements if not requirement.cost_per_unit or requirement.cost_per_unit <= 0]
        if unpriced:
            raise AllocationError(f"{programme.name}: set a unit price for {', '.join(unpriced)} in the Crop Catalogue.")
        product_ids = [requirement.input_product_id for requirement in requirements]
        candidates = list(eligible_batch_lines(programme, season, product_ids))
        by_batch = {}
        for line in candidates:
            by_batch.setdefault(line.batch_id, {})[line.input_product_id] = line
        complete = {batch_id: products for batch_id, products in by_batch.items() if all(pid in products for pid in product_ids)}
        batch_id = choice.get("batch")
        if batch_id:
            batch_id = int(batch_id)
            if batch_id not in by_batch:
                raise AllocationError(f"The chosen {CATEGORY_LABELS[category].lower()} batch does not belong to {programme.name} or has none of its products.")
        elif complete:
            needed = {requirement.input_product_id: (area * requirement.rate_per_hectare) for requirement in requirements}
            enough = [bid for bid, products in complete.items() if all(products[pid].available_quantity >= needed[pid] for pid in product_ids)]
            batch_id = (enough or list(complete))[0]
        elif by_batch:
            batch_id = next(iter(by_batch))
        else:
            batch_id = None
        batch_products = by_batch.get(batch_id, {})
        category_cost = Decimal("0.00")
        category_lines = []
        for requirement in requirements:
            required = (area * requirement.rate_per_hectare).quantize(FOUR)
            price = Decimal(requirement.cost_per_unit)
            cost = (required * price).quantize(TWO)
            batch_line = batch_products.get(requirement.input_product_id)
            if batch_line is not None and locked is not None:
                batch_line = locked.get(batch_line.pk, batch_line)
            available = batch_line.available_quantity if batch_line is not None else Decimal("0")
            entry = {
                "category": category,
                "programme": programme,
                "requirement": requirement,
                "input_product": requirement.input_product,
                "unit": requirement.unit or requirement.input_product.unit,
                "rate_per_hectare": requirement.rate_per_hectare,
                "unit_price": price,
                "required_quantity": required,
                "cost": cost,
                "batch_input": batch_line,
                "available_quantity": available,
                "available_after": available - required,
            }
            if batch_line is None:
                problems.append(f"{requirement.input_product.name} ({programme.name}) is not in any submitted or approved request batch for {season.name}.")
            elif required > available:
                problems.append(
                    f"Not enough {requirement.input_product.name} in batch {batch_line.batch.request_number}: "
                    f"{required.normalize():f} {entry['unit']} needed, {available.normalize():f} {entry['unit']} available."
                )
            category_cost += cost
            category_lines.append(entry)
            lines.append(entry)
        total_cost += category_cost
        categories.append({
            "category": category, "label": CATEGORY_LABELS[category], "programme": programme,
            "batch": batch_products and next(iter(batch_products.values())).batch,
            "lines": category_lines, "total_cost": category_cost,
        })
    return {
        "farmer": farmer, "farm": selected_farm, "season": season, "crop": crop, "hectares": area,
        "crop_hectares_limit": limit, "categories": categories, "lines": lines,
        "total_cost": total_cost.quantize(TWO), "problems": problems,
    }


def serialize_plan(plan, *, show_money=True):
    def money(value):
        return str(Decimal(value).quantize(TWO)) if show_money else None

    def qty(value):
        return format(Decimal(value).quantize(FOUR).normalize(), "f")

    return {
        "farmer": plan["farmer"].pk, "farm": plan["farm"].pk, "season": plan["season"].pk, "season_name": plan["season"].name,
        "crop": plan["crop"].pk, "crop_name": plan["crop"].name, "hectares": str(plan["hectares"]),
        "crop_hectares_limit": str(plan["crop_hectares_limit"]) if plan["crop_hectares_limit"] is not None else None,
        "total_cost": money(plan["total_cost"]),
        "problems": plan["problems"],
        "can_confirm": not plan["problems"],
        "categories": [
            {
                "category": entry["category"], "label": entry["label"],
                "programme": entry["programme"].pk if entry["programme"] else None,
                "programme_name": entry["programme"].name if entry["programme"] else "",
                "batch": entry.get("batch").pk if entry.get("batch") else None,
                "batch_number": entry.get("batch").request_number if entry.get("batch") else "",
                "total_cost": money(entry["total_cost"]),
                "total_quantity": qty(sum((line["required_quantity"] for line in entry["lines"]), Decimal("0"))),
                "lines": [
                    {
                        "input_product": line["input_product"].pk, "product_name": line["input_product"].name, "unit": line["unit"],
                        "rate_per_hectare": qty(line["rate_per_hectare"]), "required_quantity": qty(line["required_quantity"]),
                        "available_quantity": qty(line["available_quantity"]), "available_after": qty(line["available_after"]),
                        "unit_price": money(line["unit_price"]), "cost": money(line["cost"]),
                        "batch_input": line["batch_input"].pk if line["batch_input"] else None,
                        "batch_number": line["batch_input"].batch.request_number if line["batch_input"] else "",
                        "sufficient": line["batch_input"] is not None and line["required_quantity"] <= line["available_quantity"],
                    }
                    for line in entry["lines"]
                ],
            }
            for entry in plan["categories"]
        ],
    }


@transaction.atomic
def confirm(*, farmer, farm, season, crop, hectares, selections, user=None, crop_season=None):
    """Make the allocation: lock the farmer and the batches, re-check everything, then take the stock."""
    if crop_season and crop is not None and crop.category != crop_season:
        raise AllocationError(f"{crop.name} is not a {'Summer' if crop_season == 'SUMMER' else 'Winter'} crop.")
    # One allocation at a time per farmer, so a double click cannot create two.
    farmer = Farmer.objects.select_for_update().get(pk=farmer.pk)
    draft = build_plan(farmer=farmer, farm=farm, season=season, crop=crop, hectares=hectares, selections=selections)
    locked = stock.lock([line["batch_input"].pk for line in draft["lines"] if line["batch_input"] is not None])
    plan = build_plan(farmer=farmer, farm=farm, season=season, crop=crop, hectares=hectares, selections=selections, locked=locked)
    if any(line["batch_input"] is not None and line["batch_input"].pk not in locked for line in plan["lines"]):
        raise AllocationError("Batch balances changed while this allocation was being made. Review the summary and confirm again.")
    if plan["problems"]:
        raise AllocationError(" ".join(plan["problems"]))
    selling_price = CropPricingService.resolve_price_per_tonne(crop=crop, season=season)
    primary = next(entry["programme"] for entry in plan["categories"] if entry["programme"] is not None)
    rate_total = sum((line["rate_per_hectare"] * line["unit_price"] for line in plan["lines"]), Decimal("0"))
    allocation = InputAllocation.objects.create(
        farmer=farmer, farm=plan["farm"], programme=primary, season=season, crop_reference=crop, crop=crop.name,
        hectares=plan["hectares"], total_input_cost=plan["total_cost"],
        calculated_input_cost_per_hectare=rate_total.quantize(TWO),
        status=InputAllocation.STATUS_ALLOCATED, sourced_by_category=True, created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    actor = user if getattr(user, "is_authenticated", False) else None
    for line in plan["lines"]:
        requirement = line["requirement"]
        record = InputAllocationLine.objects.create(
            allocation=allocation, source_requirement=requirement, input_category=line["category"],
            programme=line["programme"], input_product=line["input_product"], batch_input=line["batch_input"],
            group_name=CATEGORY_LABELS[line["category"]], item_name=line["input_product"].name, unit=line["unit"],
            rate_per_hectare=line["rate_per_hectare"], cost_per_unit=line["unit_price"],
            cost_per_hectare=(line["rate_per_hectare"] * line["unit_price"]).quantize(FOUR),
            required_quantity=line["required_quantity"], calculated_cost=line["cost"], included_in_total=True,
        )
        stock.allocate(locked[line["batch_input"].pk], line["required_quantity"], allocation=allocation, allocation_line=record, user=actor)
    RecoveryCalculationService.create_or_update_from_allocation(allocation=allocation, selling_price_per_tonne=selling_price)
    return allocation


@transaction.atomic
def cancel(*, allocation, reason, user=None):
    """Reverse an allocation: stock goes back to its batches and the debt is cancelled. Nothing is deleted."""
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
