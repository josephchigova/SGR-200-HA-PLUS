"""Lead-farmer input allocations, Admin's hectare limits and the final approval.

Admin configures each programme's catalogue: varieties, unit, rate per hectare and price.
A lead farmer allocates hectares of those varieties to their own farmers. Every allocation
(one farmer, one crop, the varieties and hectares) is its own record: adding, changing or
removing one saves straight to the database, and the screen is redrawn from what was saved.
Quantity and cost are always calculated here from the catalogue. Nothing the browser sends
for a quantity, a price or a total is stored.

A lead farmer's allocations for one programme, agricultural year and season form one
submission. The lead farmer submits it; Admin either accepts the requested hectares or
issues lower maximums, at crop, input-category or variety level. The lead farmer then
distributes those hectares among their farmers, within the maximums, and submits the final
distribution. Only Admin's final approval makes the allocations official and creates the
farmer input debts, in one transaction.

There is no variety cap and no stock balance.
"""

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.farmers.models import Farm, Farmer
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.programmes.models import INPUT_CATEGORIES, Crop, CropInputRequirement, Programme, Season
from apps.programmes.services import CropPricingService
from apps.recovery.services import RecoveryCalculationService

from . import programme_allocation
from .models import (
    InputAllocation,
    InputAllocationLine,
    InputSupplyAllocation,
    InputSupplyEvent,
    InputSupplyFarmer,
    InputSupplyLimit,
    InputSupplyLine,
    InputSupplyRequest,
)
from .programme_allocation import CATEGORY_LABELS, FOUR, TWO, covered_categories, crop_hectares

REVIEW_ROLES = (User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_PROGRAMME_OFFICER)
SEASON_LABELS = {"SUMMER": "Summer", "WINTER": "Winter"}
SCOPE_ORDER = {InputSupplyLimit.SCOPE_CROP: 0, InputSupplyLimit.SCOPE_CATEGORY: 1, InputSupplyLimit.SCOPE_VARIETY: 2}
ZERO = Decimal("0.00")


class SupplyError(ValueError):
    pass


class SupplyConflict(SupplyError):
    """The record changed since the screen loaded it. The edit is refused instead of overwriting."""


# Small helpers ----------------------------------------------------------------------------

def _decimal(value, label):
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise SupplyError(f"Enter {label} as a number.") from error
    if number.is_nan() or number.is_infinite():
        raise SupplyError(f"Enter {label} as a number.")
    return number


def _money(value):
    return str(Decimal(value).quantize(TWO)) if value is not None else None


def _ha(value):
    return str(Decimal(value or 0).quantize(TWO))


def _qty(value):
    return format(Decimal(value or 0).quantize(FOUR).normalize(), "f")


def person_name(user):
    if not user:
        return ""
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email or user.username


def _load(model, pk, label):
    if pk in (None, ""):
        raise SupplyError(f"Select the {label}.")
    try:
        return model.objects.get(pk=pk)
    except (model.DoesNotExist, ValueError, TypeError) as error:
        raise SupplyError(f"Select a valid {label}.") from error


def _product_name(requirement):
    return requirement.input_product.name if requirement.input_product_id else requirement.item_name


def catalogue_unit(requirement):
    unit = (requirement.unit or "").strip()
    if not unit and requirement.input_product_id:
        unit = (requirement.input_product.unit or "").strip()
    return unit


def line_cost(quantity, requirement):
    """Cost of a calculated quantity, using the pack price when the catalogue sells packs."""
    pack_size = Decimal(requirement.pack_size) if requirement.pack_size else Decimal("0")
    if pack_size > 0 and requirement.pack_price is not None:
        return (Decimal(quantity) / pack_size * Decimal(requirement.pack_price)).quantize(TWO)
    if requirement.cost_per_unit is None:
        return ZERO
    return (Decimal(quantity) * Decimal(requirement.cost_per_unit)).quantize(TWO)


def _event(supply, action, user, remarks="", detail=None):
    return InputSupplyEvent.objects.create(
        request=supply, action=action, actor=user if getattr(user, "is_authenticated", False) else None,
        actor_name=person_name(user), remarks=(remarks or "").strip(), detail=detail or {},
    )


def _notify(recipients, *, kind, key, title, body, url, tone):
    for recipient in recipients:
        if recipient is not None:
            Notification.objects.get_or_create(
                recipient=recipient, dedupe_key=key,
                defaults={"kind": kind, "title": title[:200], "body": body, "url": url, "tone": tone},
            )


def _reviewers():
    return User.objects.filter(is_active=True).filter(Q(role__in=REVIEW_ROLES) | Q(is_superuser=True)).distinct()


def season_label(supply):
    return SEASON_LABELS.get(supply.season_code, "")


def _title(supply):
    return f"{supply.programme.name}, {supply.season.name} {season_label(supply)}".strip()


def _notify_submitted(supply, event, final=False):
    _notify(
        _reviewers(), kind=Notification.KIND_INPUT_SUPPLY_SUBMITTED, key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} {'final distribution submitted' if final else 'submitted'}",
        body=f"{person_name(supply.lead_farmer)} {'submitted the final distribution for' if final else 'submitted'} {_title(supply)}.",
        url="/input-approvals", tone="warning",
    )


def _notify_lead(supply, event, tone, body=None, url="/my-input-requests"):
    _notify(
        [supply.lead_farmer], kind=Notification.KIND_INPUT_SUPPLY_DECIDED, key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} {supply.get_status_display().lower()}",
        body=body or supply.decision_notes or f"Admin updated {supply.reference} ({_title(supply)}).", url=url, tone=tone,
    )


def _decision_user(user):
    if not user or not user.is_authenticated:
        raise SupplyError("Sign in again.")
    if user.is_superuser or user.role in REVIEW_ROLES:
        return user
    raise SupplyError("Only an administrator can review input submissions.")


def _lead(user):
    if not user or user.role != User.ROLE_LEAD_FARMER:
        raise SupplyError("Only a lead farmer can allocate inputs to farmers.")
    if not user.assigned_cluster_id:
        raise SupplyError("Your account is not assigned to a cluster, so you have no farmers to allocate to.")
    return user


def _can_edit(supply):
    """Lead farmers change a submission while drafting it, after Admin returns it, and within issued limits.

    Once it is with Admin it stays as sent; more farmers go into the lead farmer's next submission.
    """
    if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION:
        return supply.status in (InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED)
    return supply.status in (InputSupplyRequest.STATUS_DRAFT, InputSupplyRequest.STATUS_RETURNED)


def _waiting_message(supply):
    if supply.status == InputSupplyRequest.STATUS_CONFIRMATION:
        return f"{supply.reference} is waiting for Admin's final review, so its allocations cannot change now."
    if supply.status == InputSupplyRequest.STATUS_SUBMITTED:
        return f"{supply.reference} is with Admin, so its allocations cannot change. Add more farmers in a new submission."
    return f"{supply.reference} is {supply.get_status_display().lower()}, so its allocations cannot change."


def _locked(request_id):
    try:
        return InputSupplyRequest.objects.select_for_update(of=("self",)).select_related("lead_farmer", "programme", "season", "crop").get(pk=request_id)
    except InputSupplyRequest.DoesNotExist as error:
        raise SupplyError("That submission no longer exists. Refresh the page.") from error


# Programme, crop and farmer checks -------------------------------------------------------

def _context(*, programme_id, season_id, crop_season):
    programme = _load(Programme, programme_id, "programme")
    season = _load(Season, season_id, "agricultural year")
    crop_season = str(crop_season or "").upper()
    if crop_season not in SEASON_LABELS:
        raise SupplyError("Choose Summer or Winter.")
    if season.status != Season.STATUS_ACTIVE:
        raise SupplyError(f"{season.name} is not the active agricultural year, so its allocations cannot be changed.")
    if not programme.is_active:
        raise SupplyError(f"{programme.name} is inactive.")
    if programme.season_id and programme.season_id != season.pk:
        raise SupplyError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
    return programme, season, crop_season


def _crop(programme, crop_id, season_code):
    crop = _load(Crop, crop_id, "crop")
    if season_code and crop.category != season_code:
        raise SupplyError(f"{crop.name} is a {crop.get_category_display().lower()} crop, not {SEASON_LABELS[season_code].lower()}.")
    if not programme.supports_crop(crop):
        raise SupplyError(f"{programme.name} does not support {crop.name}.")
    return crop


def _lines(programme, crop, farmer, raw_lines):
    """Turn the varieties and hectares typed for one farmer into calculated lines."""
    if not isinstance(raw_lines, list) or not raw_lines:
        raise SupplyError(f"Choose at least one variety and its hectares for {farmer.full_name}.")
    seen = set()
    lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise SupplyError("Send each variety with its hectares.")
        requirement = (
            CropInputRequirement.objects.select_related("input_product").filter(pk=raw.get("requirement")).first()
            if str(raw.get("requirement") or "").isdigit() else None
        )
        if requirement is None:
            raise SupplyError("Select a valid variety.")
        name = _product_name(requirement)
        if requirement.pk in seen:
            raise SupplyError(f"{name} is entered twice for {farmer.full_name}.")
        seen.add(requirement.pk)
        if requirement.programme_id != programme.pk or requirement.crop_id != crop.pk:
            raise SupplyError(f"{name} is not in {programme.name}'s {crop.name} catalogue.")
        if not requirement.active or not requirement.input_product_id:
            raise SupplyError(f"{name} is not an active catalogue variety.")
        if requirement.input_category not in (programme.input_categories or []):
            raise SupplyError(f"{programme.name} does not supply {CATEGORY_LABELS.get(requirement.input_category, 'that input').lower()}.")
        if not requirement.rate_per_hectare or requirement.rate_per_hectare <= 0:
            raise SupplyError(f"{name} has no application rate per hectare in the catalogue.")
        priced = (requirement.cost_per_unit and requirement.cost_per_unit > 0) or (requirement.pack_size and requirement.pack_price and requirement.pack_price > 0)
        if not priced:
            raise SupplyError(f"Set a unit price for {name} in the crop catalogue.")
        area = _decimal(raw.get("hectares"), f"hectares for {name}").quantize(TWO)
        if area <= 0:
            raise SupplyError(f"Enter hectares greater than zero for {name}.")
        quantity = (area * Decimal(requirement.rate_per_hectare)).quantize(FOUR)
        lines.append({
            "requirement": requirement, "hectares": area, "rate_per_hectare": Decimal(requirement.rate_per_hectare),
            "quantity": quantity, "unit": catalogue_unit(requirement),
            "unit_price": Decimal(requirement.cost_per_unit) if requirement.cost_per_unit is not None else None,
            "estimated_cost": line_cost(quantity, requirement),
        })
    return lines


def _category_sums(lines):
    totals = {}
    for line in lines:
        category = line["requirement"].input_category
        totals[category] = totals.get(category, ZERO) + line["hectares"]
    return totals


def land_hectares(lines):
    """Varieties of one input category go on different ground, so they add up. Different categories share ground."""
    sums = _category_sums(lines)
    return max(sums.values()) if sums else ZERO


def hectares_in_use(farmer, crop, season, exclude_entry_id=None):
    """The farmer's crop hectares already spoken for: official allocations plus allocations in open submissions."""
    allocated = InputAllocation.objects.filter(farmer=farmer, season=season).exclude(status=InputAllocation.STATUS_CANCELLED).filter(
        Q(crop_reference=crop) | Q(crop_reference__isnull=True, crop__iexact=crop.name),
    ).aggregate(total=Sum("hectares"))["total"]
    rows = InputSupplyFarmer.objects.filter(farmer=farmer, crop=crop, request__season=season, request__status__in=InputSupplyRequest.OPEN_STATUSES)
    if exclude_entry_id:
        rows = rows.exclude(pk=exclude_entry_id)
    drafted = rows.aggregate(total=Sum("hectares"))["total"]
    return Decimal(allocated or 0) + Decimal(drafted or 0)


def _check_farmer(*, lead, farmer, farm, crop, season, lines, exclude_entry_id=None):
    """The farmer must be the lead farmer's, eligible, and within the hectares they intend to plant."""
    if farmer.cluster_id != lead.assigned_cluster_id:
        raise SupplyError(f"{farmer.full_name} is not one of your farmers.")
    eligibility = FarmerApprovalEligibilityService.evaluate_for_arda(farmer, season)
    if not eligibility["eligible"]:
        raise SupplyError(f"{farmer.full_name} cannot receive inputs yet: " + " ".join(eligibility["reasons"]))
    if farm is None or farm.farmer_id != farmer.pk:
        raise SupplyError(f"Select a farm belonging to {farmer.full_name}.")
    registered = [row for row in farmer.crop_allocations.all() if row.season_id == season.pk and row.crop_id == crop.pk]
    if registered:
        limit = sum((Decimal(row.hectares) for row in registered), ZERO)
    elif any(row.season_id == season.pk for row in farmer.crop_allocations.all()):
        raise SupplyError(
            f"{farmer.full_name} has no intended planting recorded for {crop.name} in {season.name}. "
            "Record it on the farmer's registration first."
        )
    else:
        limit = crop_hectares(farmer, crop, season)
    used = hectares_in_use(farmer, crop, season, exclude_entry_id=exclude_entry_id)
    for category, area in _category_sums(lines).items():
        label = CATEGORY_LABELS.get(category, category).lower()
        if limit is not None and area + used > limit:
            raise SupplyError(
                f"{farmer.full_name} intends to plant {_ha(limit)} ha of {crop.name} in {season.name}. "
                f"{_ha(used)} ha is already allocated or in another submission, so {_ha(area)} ha of {label} is too much."
            )
        if limit is None and area > Decimal(farm.arable_hectares or 0):
            raise SupplyError(f"{_ha(area)} ha of {label} is more than {farmer.full_name}'s arable land.")
    covered = covered_categories(farmer=farmer, crop=crop, season=season)
    for category in _category_sums(lines):
        if category in covered:
            raise SupplyError(
                f"{farmer.full_name} already has confirmed {CATEGORY_LABELS.get(category, category).lower()} for {crop.name} "
                f"in {season.name}. Cancel that allocation before allocating it again."
            )


def _write_lines(entry, lines):
    entry.lines.all().delete()
    InputSupplyLine.objects.bulk_create([
        InputSupplyLine(
            farmer_entry=entry, requirement=line["requirement"], hectares=line["hectares"], rate_per_hectare=line["rate_per_hectare"],
            quantity=line["quantity"], unit=line["unit"], unit_price=line["unit_price"], estimated_cost=line["estimated_cost"],
        )
        for line in lines
    ])


def _entry_lines(entry):
    """An allocation's varieties and hectares, as the API takes them."""
    return [{"requirement": line.requirement_id, "hectares": line.hectares} for line in entry.lines.all()]


# Hectares at crop, category and variety level -------------------------------------------

def measure(supply):
    """Distributed hectares from the saved allocations: per crop (land), per crop and category, per variety."""
    crops, categories, varieties = {}, {}, {}
    for entry in supply.farmers.select_related("crop").prefetch_related("lines__requirement"):
        crop_id = entry.crop_id
        crops[crop_id] = crops.get(crop_id, ZERO) + Decimal(entry.hectares)
        for line in entry.lines.all():
            key = (crop_id, line.requirement.input_category)
            categories[key] = categories.get(key, ZERO) + Decimal(line.hectares)
            varieties[line.requirement_id] = varieties.get(line.requirement_id, ZERO) + Decimal(line.hectares)
    return {"crops": crops, "categories": categories, "varieties": varieties}


def _limit_name(limit):
    if limit.scope == InputSupplyLimit.SCOPE_VARIETY and limit.requirement_id:
        return _product_name(limit.requirement)
    crop = limit.crop.name if limit.crop_id else ""
    if limit.scope == InputSupplyLimit.SCOPE_CATEGORY:
        return f"{crop} {CATEGORY_LABELS.get(limit.input_category, limit.input_category).lower()}".strip()
    return crop


def _distributed(limit, measured):
    if limit.scope == InputSupplyLimit.SCOPE_VARIETY:
        return measured["varieties"].get(limit.requirement_id, ZERO)
    if limit.scope == InputSupplyLimit.SCOPE_CATEGORY:
        return measured["categories"].get((limit.crop_id, limit.input_category), ZERO)
    return measured["crops"].get(limit.crop_id, ZERO)


def _levels_over(supply):
    """Each approved maximum the saved distribution goes past, keyed by level, with its message and hectares used."""
    measured = measure(supply)
    over = {}
    limits = list(supply.limits.select_related("crop", "requirement__input_product"))
    if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION:
        limited_varieties = {limit.requirement_id for limit in limits if limit.scope == InputSupplyLimit.SCOPE_VARIETY}
        limited_crops = {limit.crop_id for limit in limits if limit.scope == InputSupplyLimit.SCOPE_CROP}
        for crop_id, hectares in measured["crops"].items():
            if crop_id not in limited_crops and hectares > 0:
                crop = Crop.objects.filter(pk=crop_id).first()
                over[("crop", crop_id)] = (f"{crop.name if crop else 'That crop'} has no approved hectares in this submission.", hectares)
        for requirement_id, hectares in measured["varieties"].items():
            if requirement_id not in limited_varieties and hectares > 0:
                requirement = CropInputRequirement.objects.select_related("input_product").filter(pk=requirement_id).first()
                over[("variety", requirement_id)] = (f"{_product_name(requirement) if requirement else 'That variety'} was not approved for this submission.", hectares)
    for limit in limits:
        used = _distributed(limit, measured)
        if used > Decimal(limit.approved_hectares):
            over[("limit", limit.pk)] = (
                f"{_limit_name(limit)} is limited to {_ha(limit.approved_hectares)} ha; the allocations use {_ha(used)} ha, "
                f"so reduce it by {_ha(used - Decimal(limit.approved_hectares))} ha.",
                used,
            )
    return over


def limit_breaches(supply):
    """Every approved maximum the saved distribution goes past, explained."""
    return [message for message, _used in _levels_over(supply).values()]


def _enforce_limits(supply):
    breaches = limit_breaches(supply)
    if breaches:
        raise SupplyError(" ".join(breaches) + " Unused hectares can stay unallocated, but an approved maximum cannot be exceeded.")


def _refuse_new_excess(supply, before):
    """While a maximum is being shared out, any reduction can be saved, one farmer at a time.

    Only a change that pushes a level further past its maximum is refused. Every maximum is
    checked in full when the lead farmer sends the submission back to Admin.
    """
    if before is None:
        return
    worse = [message for key, (message, used) in _levels_over(supply).items() if used > before.get(key, ("", ZERO))[1]]
    if worse:
        raise SupplyError(" ".join(worse) + " Reduce other allocations first, or lower this one.")


# Lead farmer: one allocation at a time ---------------------------------------------------

def _draft_submission(lead, programme, season, crop_season):
    """The lead farmer's one draft for this programme and season, if they have started one."""
    return (
        InputSupplyRequest.objects.select_for_update()
        .filter(lead_farmer=lead, programme=programme, season=season, crop_season=crop_season, crop__isnull=True, status=InputSupplyRequest.STATUS_DRAFT)
        .first()
    )


def _target_submission(lead, programme, season, crop_season, request_id):
    """The submission a new allocation goes into: the one chosen on screen, or the draft (started if needed)."""
    if request_id not in (None, ""):
        supply = _locked(request_id)
        if supply.lead_farmer_id != lead.pk:
            raise SupplyError("That submission is not yours.")
        if supply.programme_id != programme.pk or supply.season_id != season.pk or supply.season_code != crop_season:
            raise SupplyError(f"{supply.reference} is for a different programme or season. Refresh the page.")
        if not _can_edit(supply):
            raise SupplyError(_waiting_message(supply))
        return supply
    supply = _draft_submission(lead, programme, season, crop_season)
    if supply is not None:
        return supply
    try:
        with transaction.atomic():
            supply = InputSupplyRequest.objects.create(
                reference=f"TMP{uuid.uuid4().hex}", lead_farmer=lead, programme=programme, season=season,
                crop_season=crop_season, stage=InputSupplyRequest.STAGE_REQUEST, status=InputSupplyRequest.STATUS_DRAFT,
            )
    except IntegrityError as error:
        raise SupplyConflict("A new submission for this programme and season was just started elsewhere. Refresh and try again.") from error
    supply.reference = f"LF{supply.pk:05d}"
    supply.save(update_fields=["reference"])
    return supply


def _refuse_duplicate(supply, farmer, crop, exclude_entry_id=None):
    """Within a programme, a farmer's crop is in one open submission at a time, so it is never sent twice.

    Other programmes are limited by the farmer's intended planting instead (see _check_farmer).
    """
    rows = InputSupplyFarmer.objects.filter(
        farmer=farmer, crop=crop, request__programme=supply.programme, request__season=supply.season,
        request__status__in=InputSupplyRequest.OPEN_STATUSES,
    ).select_related("request")
    if exclude_entry_id:
        rows = rows.exclude(pk=exclude_entry_id)
    existing = rows.first()
    if existing is None:
        return
    where = existing.request
    if where.pk == supply.pk:
        raise SupplyError(f"{farmer.full_name} already has a {crop.name} allocation in {where.reference}. Edit that allocation instead.")
    raise SupplyError(
        f"{farmer.full_name} already has a {crop.name} allocation in {where.reference} ({where.get_status_display().lower()}). "
        "Change it there, or wait until Admin has decided on it."
    )


def _allocation_detail(entry, lines):
    return {
        "farmer": entry.farmer.full_name, "crop": entry.crop.name if entry.crop_id else "",
        "varieties": [{"name": _product_name(line["requirement"]), "hectares": _ha(line["hectares"])} for line in lines],
    }


@transaction.atomic
def add_allocation(*, user, programme_id, season_id, crop_season, farmer_id, crop_id, lines, farm_id=None, request_id=None):
    """Save one farmer's crop allocation into the chosen submission, or into the draft (started if needed).

    A lead farmer can send several submissions for the same programme and season: farmers sent
    earlier stay with Admin while new farmers go into the next draft.
    """
    lead = _lead(user)
    programme, season, crop_season = _context(programme_id=programme_id, season_id=season_id, crop_season=crop_season)
    crop = _crop(programme, crop_id, crop_season)
    farmer = _load(Farmer, farmer_id, "farmer")
    farm = Farm.objects.filter(pk=farm_id).first() if farm_id else farmer.farms.filter(is_active=True).order_by("id").first()
    calculated = _lines(programme, crop, farmer, lines)
    _check_farmer(lead=lead, farmer=farmer, farm=farm, crop=crop, season=season, lines=calculated)

    supply = _target_submission(lead, programme, season, crop_season, request_id)
    _refuse_duplicate(supply, farmer, crop)
    before = _levels_over(supply) if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION else None
    entry = InputSupplyFarmer.objects.create(request=supply, farmer=farmer, farm=farm, crop=crop, hectares=land_hectares(calculated))
    _write_lines(entry, calculated)
    _refuse_new_excess(supply, before)
    _event(supply, InputSupplyEvent.ALLOCATION_ADDED, lead, "", _allocation_detail(entry, calculated))
    return supply, entry


def _owned_entry(user, entry_id):
    lead = _lead(user)
    entry = InputSupplyFarmer.objects.select_related("request", "farmer", "crop", "farm").filter(pk=entry_id, request__lead_farmer=lead).first()
    if entry is None:
        raise SupplyError("That allocation no longer exists. Refresh the page.")
    return lead, entry


def _check_version(entry, version):
    if version in (None, ""):
        raise SupplyConflict("Refresh the page and try again: the allocation's version was not sent.")
    if str(version) != str(entry.version):
        raise SupplyConflict(f"{entry.farmer.full_name}'s {entry.crop.name if entry.crop_id else ''} allocation was changed since you opened it. Refresh to see the latest figures.")


@transaction.atomic
def update_allocation(*, user, entry_id, lines, version, farm_id=None):
    """Change one allocation's varieties or hectares. Quantities and costs are recalculated."""
    lead, entry = _owned_entry(user, entry_id)
    supply = _locked(entry.request_id)
    entry = InputSupplyFarmer.objects.select_for_update(of=("self",)).select_related("farmer", "crop", "farm").get(pk=entry.pk)
    if not _can_edit(supply):
        raise SupplyError(_waiting_message(supply))
    _check_version(entry, version)
    farm = Farm.objects.filter(pk=farm_id).first() if farm_id else entry.farm
    calculated = _lines(supply.programme, entry.crop, entry.farmer, lines)
    before = _levels_over(supply) if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION else None
    _save_entry(supply, lead, entry, farm, calculated)
    _refuse_new_excess(supply, before)
    return supply, entry


def _save_entry(supply, lead, entry, farm, calculated):
    entry.farm = farm
    entry.hectares = land_hectares(calculated)
    entry.version = F("version") + 1
    entry.save(update_fields=["farm", "hectares", "version", "updated_at"])
    entry.refresh_from_db()
    _write_lines(entry, calculated)
    _event(supply, InputSupplyEvent.ALLOCATION_CHANGED, lead, "", _allocation_detail(entry, calculated))


@transaction.atomic
def redistribute(*, user, request_id, changes):
    """Save new hectares for several allocations of one submission together.

    Used to share out a maximum Admin set: each change carries the allocation's version, and
    a variety set to 0 ha is removed (an allocation left with none is removed). Either every
    change is saved or none is. Quantities and costs are recalculated on the server.
    """
    lead = _lead(user)
    supply = _locked(request_id)
    if supply.lead_farmer_id != lead.pk:
        raise SupplyError("You can only change your own submission.")
    if not _can_edit(supply):
        raise SupplyError(_waiting_message(supply))
    if not isinstance(changes, list) or not changes:
        raise SupplyError("There are no changes to save.")
    before = _levels_over(supply) if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION else None
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or not str(change.get("allocation") or "").isdigit():
            raise SupplyError("Each change must name the allocation it is for. Refresh the page.")
        entry_id = int(change["allocation"])
        if entry_id in seen:
            raise SupplyError("An allocation was sent twice. Refresh the page.")
        seen.add(entry_id)
        entry = InputSupplyFarmer.objects.select_for_update(of=("self",)).select_related("farmer", "crop", "farm").filter(pk=entry_id, request=supply).first()
        if entry is None:
            raise SupplyConflict("One of these allocations was removed since you opened the page. Refresh to see the latest figures.")
        _check_version(entry, change.get("version"))
        current = {line.requirement_id for line in entry.lines.all()}
        raw = change.get("lines")
        if not isinstance(raw, list):
            raise SupplyError(f"Enter the hectares for {entry.farmer.full_name}.")
        kept = []
        for line in raw:
            if not isinstance(line, dict) or not str(line.get("requirement") or "").isdigit() or int(line["requirement"]) not in current:
                raise SupplyError(f"Only the hectares of {entry.farmer.full_name}'s existing varieties can change here.")
            if _decimal(line.get("hectares"), "hectares") > 0:
                kept.append(line)
        if not kept:
            detail = _allocation_detail(entry, [{"requirement": line.requirement, "hectares": line.hectares} for line in entry.lines.select_related("requirement__input_product")])
            entry.delete()
            _event(supply, InputSupplyEvent.ALLOCATION_REMOVED, lead, "", detail)
            continue
        calculated = _lines(supply.programme, entry.crop, entry.farmer, kept)
        _check_farmer(lead=lead, farmer=entry.farmer, farm=entry.farm, crop=entry.crop, season=supply.season, lines=calculated, exclude_entry_id=entry.pk)
        _save_entry(supply, lead, entry, entry.farm, calculated)
    _refuse_new_excess(supply, before)
    return supply


@transaction.atomic
def delete_allocation(*, user, entry_id, version):
    """Remove one allocation from the database. An empty draft submission is removed with it."""
    lead, entry = _owned_entry(user, entry_id)
    supply = _locked(entry.request_id)
    entry = InputSupplyFarmer.objects.select_for_update(of=("self",)).select_related("farmer", "crop").get(pk=entry.pk)
    if not _can_edit(supply):
        raise SupplyError(_waiting_message(supply))
    _check_version(entry, version)
    detail = _allocation_detail(entry, [{"requirement": line.requirement, "hectares": line.hectares} for line in entry.lines.select_related("requirement__input_product")])
    entry.delete()
    if supply.status == InputSupplyRequest.STATUS_DRAFT and not supply.farmers.exists():
        supply.delete()
        return None
    _event(supply, InputSupplyEvent.ALLOCATION_REMOVED, lead, "", detail)
    return supply


def _revalidate(supply):
    """Check every saved allocation again before it goes to Admin or becomes official."""
    problems = []
    for entry in supply.farmers.select_related("farmer", "farm", "crop").prefetch_related("lines__requirement__input_product", "farmer__crop_allocations"):
        try:
            calculated = _lines(supply.programme, entry.crop, entry.farmer, _entry_lines(entry))
            _check_farmer(lead=supply.lead_farmer, farmer=entry.farmer, farm=entry.farm, crop=entry.crop, season=supply.season, lines=calculated, exclude_entry_id=entry.pk)
        except SupplyError as error:
            problems.append(str(error))
    if problems:
        raise SupplyError(" ".join(problems))


@transaction.atomic
def submit(*, request_id, user):
    lead = _lead(user)
    supply = _locked(request_id)
    if supply.lead_farmer_id != lead.pk:
        raise SupplyError("You can only submit your own submission.")
    if not _can_edit(supply):
        raise SupplyError(_waiting_message(supply))
    if not supply.farmers.exists():
        raise SupplyError("Add at least one allocation before submitting.")
    final = supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION
    _revalidate(supply)
    if final:
        _enforce_limits(supply)
    was_returned = supply.status == InputSupplyRequest.STATUS_RETURNED
    if final:
        supply.status = InputSupplyRequest.STATUS_CONFIRMATION
        action = InputSupplyEvent.FINAL_RESUBMITTED if was_returned else InputSupplyEvent.FINAL_SUBMITTED
    else:
        action = InputSupplyEvent.RESUBMITTED if supply.status in (InputSupplyRequest.STATUS_RETURNED, InputSupplyRequest.STATUS_SUBMITTED) else InputSupplyEvent.SUBMITTED
        supply.status = InputSupplyRequest.STATUS_SUBMITTED
    supply.submitted_at = timezone.now()
    supply.save(update_fields=["status", "submitted_at", "updated_at"])
    event = _event(supply, action, lead, "", {"hectares": _ha(sum(measure(supply)["crops"].values(), ZERO))})
    _notify_submitted(supply, event, final=final)
    return supply


# Admin: limits, final review -------------------------------------------------------------

def requested_levels(supply):
    """Requested hectares at crop, category and variety level, from the saved allocations."""
    measured = measure(supply)
    levels = []
    crops = {crop.pk: crop for crop in Crop.objects.filter(pk__in=measured["crops"].keys())}
    requirements = {
        requirement.pk: requirement
        for requirement in CropInputRequirement.objects.select_related("input_product").filter(pk__in=measured["varieties"].keys())
    }
    for crop_id, hectares in measured["crops"].items():
        levels.append({"scope": InputSupplyLimit.SCOPE_CROP, "crop": crops[crop_id], "input_category": "", "requirement": None, "requested": hectares})
        for category in INPUT_CATEGORIES:
            if (crop_id, category) in measured["categories"]:
                levels.append({"scope": InputSupplyLimit.SCOPE_CATEGORY, "crop": crops[crop_id], "input_category": category, "requirement": None, "requested": measured["categories"][(crop_id, category)]})
        for requirement_id, hectares in measured["varieties"].items():
            requirement = requirements[requirement_id]
            if requirement.crop_id == crop_id:
                levels.append({"scope": InputSupplyLimit.SCOPE_VARIETY, "crop": crops[crop_id], "input_category": requirement.input_category, "requirement": requirement, "requested": hectares})
    return levels


def _level_key(level):
    requirement = level["requirement"]
    crop = level["crop"]
    return (level["scope"], crop.pk if crop else None, level["input_category"] if level["scope"] == InputSupplyLimit.SCOPE_CATEGORY else "", requirement.pk if requirement else None)


def _approved_from_client(levels, payload):
    """Read only the approved hectares Admin typed. Requested hectares stay the server's figures."""
    if not isinstance(payload, list):
        raise SupplyError("Enter the approved hectares for each crop, input category and variety.")
    supplied = {}
    for item in payload:
        if not isinstance(item, dict) or "approved_hectares" not in item:
            continue
        scope = str(item.get("scope") or "").upper()
        try:
            crop_id = int(item["crop"]) if item.get("crop") not in (None, "") else None
            requirement_id = int(item["requirement"]) if item.get("requirement") not in (None, "") else None
        except (TypeError, ValueError) as error:
            raise SupplyError("Each hectare limit must name its crop or variety.") from error
        category = str(item.get("input_category") or "").upper() if scope == InputSupplyLimit.SCOPE_CATEGORY else ""
        approved = _decimal(item.get("approved_hectares"), "approved hectares").quantize(TWO)
        if approved < 0:
            raise SupplyError("Approved hectares cannot be negative.")
        supplied[(scope, crop_id, category, requirement_id)] = approved

    resolved = []
    crop_caps, category_caps = {}, {}
    for level in levels:
        key = _level_key(level)
        if level["scope"] == InputSupplyLimit.SCOPE_VARIETY:
            key = (InputSupplyLimit.SCOPE_VARIETY, None, "", level["requirement"].pk)
            if key not in supplied:
                key = _level_key(level)
        approved = supplied.get(key)
        crop_id = level["crop"].pk
        if level["scope"] == InputSupplyLimit.SCOPE_CROP:
            approved = level["requested"] if approved is None else approved
            crop_caps[crop_id] = approved
        elif level["scope"] == InputSupplyLimit.SCOPE_CATEGORY:
            parent = crop_caps.get(crop_id, level["requested"])
            approved = min(level["requested"], parent) if approved is None else approved
            if approved > parent:
                raise SupplyError(f"{level['crop'].name} {CATEGORY_LABELS.get(level['input_category'], '').lower()} cannot be approved for more than the {_ha(parent)} ha allowed for {level['crop'].name}.")
            category_caps[(crop_id, level["input_category"])] = approved
        else:
            parent = category_caps.get((crop_id, level["input_category"]), crop_caps.get(crop_id, level["requested"]))
            approved = min(level["requested"], parent) if approved is None else approved
            if approved > parent:
                raise SupplyError(f"{_product_name(level['requirement'])} cannot be approved for more hectares than its input category.")
        resolved.append({**level, "approved": approved})
    if not any(level["approved"] > 0 for level in resolved if level["scope"] == InputSupplyLimit.SCOPE_CROP):
        raise SupplyError("Approve hectares greater than zero for at least one crop, or reject the submission.")
    return resolved


def _limit_rows(supply):
    measured = measure(supply)
    rows = []
    for limit in supply.limits.select_related("crop", "requirement__input_product", "updated_by"):
        distributed = _distributed(limit, measured)
        rows.append({
            "id": limit.pk, "scope": limit.scope, "scope_label": limit.get_scope_display(),
            "crop": limit.crop_id, "crop_name": limit.crop.name if limit.crop_id else "",
            "input_category": limit.input_category or (limit.requirement.input_category if limit.requirement_id else ""),
            "input_category_label": CATEGORY_LABELS.get(limit.input_category or (limit.requirement.input_category if limit.requirement_id else ""), ""),
            "requirement": limit.requirement_id, "name": _limit_name(limit),
            "requested_hectares": _ha(limit.requested_hectares), "approved_hectares": _ha(limit.approved_hectares),
            "difference_hectares": _ha(Decimal(limit.approved_hectares) - Decimal(limit.requested_hectares)),
            "distributed_hectares": _ha(distributed), "remaining_hectares": _ha(Decimal(limit.approved_hectares) - distributed),
            "updated_at": limit.updated_at.isoformat() if limit.updated_at else None, "updated_by_name": person_name(limit.updated_by),
        })
    rows.sort(key=lambda row: (row["crop_name"], SCOPE_ORDER.get(row["scope"], 9), row["input_category"], row["name"]))
    return rows


def _write_limits(supply, resolved, user, *, keep_requested):
    previous = {(limit.scope, limit.crop_id, limit.input_category if limit.scope == InputSupplyLimit.SCOPE_CATEGORY else "", limit.requirement_id): limit for limit in supply.limits.all()}
    seen = set()
    for level in resolved:
        key = _level_key(level)
        seen.add(key)
        current = previous.get(key)
        if current:
            if not keep_requested:
                current.requested_hectares = level["requested"]
            current.approved_hectares = level["approved"]
            current.updated_by = user
            current.save(update_fields=["requested_hectares", "approved_hectares", "updated_by", "updated_at"])
        else:
            InputSupplyLimit.objects.create(
                request=supply, scope=level["scope"], crop=level["crop"], input_category=level["input_category"] if level["scope"] != InputSupplyLimit.SCOPE_CROP else "",
                requirement=level["requirement"], requested_hectares=level["requested"], approved_hectares=level["approved"], updated_by=user,
            )
    stale = [limit.pk for key, limit in previous.items() if key not in seen]
    if stale and not keep_requested:
        InputSupplyLimit.objects.filter(pk__in=stale).delete()


@transaction.atomic
def set_hectares(*, request_id, user, mode, limits, remarks=""):
    """Set maximum hectares on a submission instead of approving it as it is.

    The lead farmer shares the maximum among that submission's farmers and submits the final
    distribution for approval; it cannot go past the maximum. Other submissions are not limited
    by it. Changing a maximum flags the submission; if the saved distribution no longer fits, it
    goes back to the lead farmer. Approving as it is (mode "approve") is the approval itself.
    """
    if str(mode or "").strip().lower() == "approve":
        return approve(request_id=request_id, user=user, remarks=remarks)
    user = _decision_user(user)
    supply = _locked(request_id)
    issuing = supply.stage == InputSupplyRequest.STAGE_REQUEST and supply.status == InputSupplyRequest.STATUS_SUBMITTED
    adjusting = supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION and supply.status in (
        InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED, InputSupplyRequest.STATUS_CONFIRMATION,
    )
    if not issuing and not adjusting:
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()}. Hectare limits are set on a submitted request, or changed before the final approval.")
    choice = str(mode or "").strip().lower()
    if choice != "distribute":
        raise SupplyError("Approve the request as it is, or set maximum hectares.")
    levels = requested_levels(supply)
    if adjusting:
        # Requested hectares stay what the lead farmer asked for when the limits were first issued.
        stored = {(limit.scope, limit.crop_id, limit.input_category if limit.scope == InputSupplyLimit.SCOPE_CATEGORY else "", limit.requirement_id): limit for limit in supply.limits.all()}
        for level in levels:
            if _level_key(level) in stored:
                level["requested"] = Decimal(stored[_level_key(level)].requested_hectares)
    if not levels:
        raise SupplyError(f"{supply.reference} has no allocations to approve.")
    resolved = _approved_from_client(levels, limits)
    action = InputSupplyEvent.LIMITS_ADJUSTED if adjusting else InputSupplyEvent.LIMITS_DISTRIBUTED
    before = _limit_rows(supply) if adjusting else []
    _write_limits(supply, resolved, user, keep_requested=adjusting)
    note = (remarks or "").strip()
    message = None
    fields = ["stage", "status", "reviewed_at", "reviewed_by", "decision_notes", "hectares_capped", "updated_at"]
    supply.hectares_capped = True
    if issuing:
        supply.stage = InputSupplyRequest.STAGE_DISTRIBUTION
        supply.status = InputSupplyRequest.STATUS_LIMITS_SET
    else:
        supply.limits_changed_at = timezone.now()
        fields.append("limits_changed_at")
        breaches = limit_breaches(supply)
        if breaches and supply.status == InputSupplyRequest.STATUS_CONFIRMATION:
            supply.status = InputSupplyRequest.STATUS_LIMITS_SET
            message = "Admin changed the approved hectares and your distribution no longer fits: " + " ".join(breaches) + " Adjust it and submit again."
        elif breaches:
            message = "Admin changed the approved hectares. Adjust your distribution: " + " ".join(breaches)
        else:
            message = "Admin changed the approved hectares. Your distribution still fits; review it before the final approval."
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = note
    supply.save(update_fields=fields)
    detail = {"limits": _limit_rows(supply)}
    if before:
        detail["previous"] = before
    event = _event(supply, action, user, note, detail)
    _notify_lead(supply, event, "good" if issuing else "warning", body=message, url="/input-allocations")
    return supply


@transaction.atomic
def approve(*, request_id, user, remarks=""):
    """Approval: the only step that makes allocations official and creates farmer debts.

    A submitted request is approved as it is. Where Admin set maximum hectares, this is the
    final approval of the lead farmer's distribution. Everything happens in one transaction.
    Quantities and prices are recalculated from the catalogue now and kept on the official lines
    as the approved snapshot. The lead farmer can then send more farmers in a new submission.
    """
    user = _decision_user(user)
    supply = _locked(request_id)
    if supply.status == InputSupplyRequest.STATUS_APPROVED:
        raise SupplyError(f"{supply.reference} is already approved. Its allocations and debts were created once.")
    as_requested = supply.status == InputSupplyRequest.STATUS_SUBMITTED
    # Earlier requests whose hectares were approved unchanged wait in this status; they can be approved now.
    uncapped_earlier = supply.status == InputSupplyRequest.STATUS_LIMITS_SET and not supply.hectares_capped
    if not (as_requested or uncapped_earlier or supply.status == InputSupplyRequest.STATUS_CONFIRMATION):
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()}. Approve it once the lead farmer has submitted it.")
    if supply.allocations.exists():
        raise SupplyError(f"{supply.reference} already has official allocations.")
    if not supply.farmers.exists():
        raise SupplyError(f"{supply.reference} has no allocations to approve.")
    if not as_requested:
        _enforce_limits(supply)
    _revalidate(supply)
    prices = {}
    for entry in supply.farmers.select_related("farmer", "farm", "crop").prefetch_related("lines__requirement__input_product"):
        calculated = _lines(supply.programme, entry.crop, entry.farmer, _entry_lines(entry))
        _write_lines(entry, calculated)
        if entry.crop_id not in prices:
            try:
                prices[entry.crop_id] = CropPricingService.resolve_price_per_tonne(crop=entry.crop, season=supply.season)
            except ValueError as error:
                raise SupplyError(str(error)) from error
        total_cost = sum((line["estimated_cost"] for line in calculated), ZERO).quantize(TWO)
        hectares = land_hectares(calculated)
        allocation = InputAllocation.objects.create(
            farmer=entry.farmer, farm=entry.farm, programme=supply.programme, season=supply.season,
            crop_reference=entry.crop, crop=entry.crop.name, hectares=hectares, total_input_cost=total_cost,
            calculated_input_cost_per_hectare=(total_cost / hectares).quantize(TWO) if hectares else ZERO,
            allocation_reference=supply.reference, status=InputAllocation.STATUS_ALLOCATED, sourced_by_category=True, created_by=user,
        )
        for line in calculated:
            requirement = line["requirement"]
            InputAllocationLine.objects.create(
                allocation=allocation, source_requirement=requirement, input_category=requirement.input_category,
                programme=supply.programme, input_product=requirement.input_product,
                group_name=CATEGORY_LABELS.get(requirement.input_category, requirement.input_category), item_name=_product_name(requirement),
                unit=line["unit"], rate_per_hectare=line["rate_per_hectare"], cost_per_unit=line["unit_price"],
                pack_label=requirement.pack_label, pack_size=requirement.pack_size, pack_price=requirement.pack_price,
                cost_per_hectare=(line["rate_per_hectare"] * line["unit_price"]).quantize(FOUR) if line["unit_price"] is not None else Decimal("0.0000"),
                required_quantity=line["quantity"], calculated_cost=line["estimated_cost"], included_in_total=True,
            )
        RecoveryCalculationService.create_or_update_from_allocation(allocation=allocation, selling_price_per_tonne=prices[entry.crop_id])
        InputSupplyAllocation.objects.create(request=supply, allocation=allocation)
    supply.status = InputSupplyRequest.STATUS_APPROVED
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = (remarks or "").strip()
    supply.save(update_fields=["status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, InputSupplyEvent.APPROVED, user, supply.decision_notes, {
        "allocations": list(supply.allocations.values_list("allocation_id", flat=True)),
        "debts": list(supply.allocations.filter(allocation__debt__isnull=False).values_list("allocation__debt__id", flat=True)),
    })
    _notify_lead(supply, event, "good")
    return supply


@transaction.atomic
def _close(*, request_id, user, status, action, remarks, tone):
    user = _decision_user(user)
    remarks = (remarks or "").strip()
    if not remarks:
        raise SupplyError("Explain the decision so the lead farmer knows what to change.")
    supply = _locked(request_id)
    allowed = (InputSupplyRequest.STATUS_SUBMITTED, InputSupplyRequest.STATUS_CONFIRMATION)
    if action == InputSupplyEvent.REJECTED:
        allowed += (InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED)
    if supply.status not in allowed:
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()}. Only a submission waiting for review can be decided.")
    if status == InputSupplyRequest.STATUS_RETURNED and supply.status == InputSupplyRequest.STATUS_SUBMITTED:
        supply.stage = InputSupplyRequest.STAGE_REQUEST
    supply.status = status
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = remarks
    supply.save(update_fields=["stage", "status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, action, user, remarks)
    _notify_lead(supply, event, tone, url="/input-allocations" if status == InputSupplyRequest.STATUS_RETURNED else "/my-input-requests")
    return supply


def reject(*, request_id, user, remarks):
    return _close(request_id=request_id, user=user, status=InputSupplyRequest.STATUS_REJECTED, action=InputSupplyEvent.REJECTED, remarks=remarks, tone="bad")


def return_for_corrections(*, request_id, user, remarks):
    return _close(request_id=request_id, user=user, status=InputSupplyRequest.STATUS_RETURNED, action=InputSupplyEvent.RETURNED, remarks=remarks, tone="warning")


@transaction.atomic
def reverse(*, request_id, user, remarks):
    """Authorised correction of a final approval: allocations and debts are cancelled, never deleted."""
    user = _decision_user(user)
    remarks = (remarks or "").strip()
    if not remarks:
        raise SupplyError("Give the reason for reversing this approval.")
    supply = _locked(request_id)
    if supply.status != InputSupplyRequest.STATUS_APPROVED:
        raise SupplyError("Only an approved submission can be reversed.")
    links = list(supply.allocations.select_related("allocation"))
    for link in links:
        try:
            programme_allocation.cancel(allocation=link.allocation, reason=remarks, user=user)
        except programme_allocation.AllocationError as error:
            raise SupplyError(str(error)) from error
    # The cancelled allocations and debts stay on record, and the event below lists them.
    # Clearing the links lets a corrected distribution be approved again with new allocations.
    InputSupplyAllocation.objects.filter(request=supply).delete()
    # Within a maximum the corrected distribution must still fit it; otherwise it is corrected freely.
    supply.stage = InputSupplyRequest.STAGE_DISTRIBUTION if supply.hectares_capped else InputSupplyRequest.STAGE_REQUEST
    supply.status = InputSupplyRequest.STATUS_RETURNED
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = remarks
    supply.save(update_fields=["stage", "status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, InputSupplyEvent.REVERSED, user, remarks, {"cancelled_allocations": [link.allocation_id for link in links]})
    _notify_lead(supply, event, "warning", url="/input-allocations")
    return supply


# What the screens show -------------------------------------------------------------------

def present(supply):
    """A submission as the screens show it. Every total is worked out from the saved allocations."""
    limit_rows = _limit_rows(supply)
    variety_limits = {row["requirement"]: row for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_VARIETY}
    category_limits = {(row["crop"], row["input_category"]): row for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_CATEGORY}
    crop_limits = {row["crop"]: row for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_CROP}
    allocations = []
    crops = {}
    hectares_total = ZERO
    estimated_cost = ZERO
    farmers = set()
    for entry in supply.farmers.select_related("farmer", "farm", "crop").prefetch_related("lines__requirement__input_product"):
        farmers.add(entry.farmer_id)
        hectares_total += Decimal(entry.hectares)
        crop_id = entry.crop_id
        crop = crops.setdefault(crop_id, {
            "crop": crop_id, "crop_name": entry.crop.name if crop_id else "", "hectares": ZERO, "estimated_cost": ZERO,
            "farmers": set(), "categories": {}, "varieties": {},
        })
        crop["hectares"] += Decimal(entry.hectares)
        crop["farmers"].add(entry.farmer_id)
        lines = []
        for line in entry.lines.all():
            requirement = line.requirement
            cost = Decimal(line.estimated_cost or 0)
            estimated_cost += cost
            crop["estimated_cost"] += cost
            category = crop["categories"].setdefault(requirement.input_category, {"hectares": ZERO, "estimated_cost": ZERO})
            category["hectares"] += Decimal(line.hectares)
            category["estimated_cost"] += cost
            variety = crop["varieties"].setdefault(requirement.pk, {
                "requirement": requirement.pk, "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": _product_name(requirement), "unit": line.unit, "rate_per_hectare": line.rate_per_hectare,
                "unit_price": line.unit_price, "hectares": ZERO, "quantity": ZERO, "estimated_cost": ZERO, "farmers": set(),
            })
            variety["hectares"] += Decimal(line.hectares)
            variety["quantity"] += Decimal(line.quantity)
            variety["estimated_cost"] += cost
            variety["farmers"].add(entry.farmer_id)
            lines.append({
                "id": line.pk, "requirement": requirement.pk, "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": _product_name(requirement), "unit": line.unit, "hectares": _ha(line.hectares),
                "rate_per_hectare": _qty(line.rate_per_hectare), "quantity": _qty(line.quantity),
                "unit_price": _money(line.unit_price), "estimated_cost": _money(cost),
            })
        allocations.append({
            "id": entry.pk, "version": entry.version, "farmer": entry.farmer_id, "farmer_name": entry.farmer.full_name,
            "membership_number": entry.farmer.membership_number, "farm": entry.farm_id, "farm_name": entry.farm.farm_name,
            "crop": crop_id, "crop_name": entry.crop.name if crop_id else "", "hectares": _ha(entry.hectares),
            "estimated_cost": _money(sum((Decimal(line["estimated_cost"]) for line in lines), ZERO)), "lines": lines,
        })

    crop_rows = []
    for crop_id, crop in sorted(crops.items(), key=lambda item: item[1]["crop_name"]):
        limit = crop_limits.get(crop_id)
        crop_rows.append({
            "crop": crop_id, "crop_name": crop["crop_name"], "hectares": _ha(crop["hectares"]), "farmers": len(crop["farmers"]),
            "estimated_cost": _money(crop["estimated_cost"]),
            "requested_hectares": limit["requested_hectares"] if limit else None, "approved_hectares": limit["approved_hectares"] if limit else None,
            "remaining_hectares": limit["remaining_hectares"] if limit else None,
            "categories": [
                {
                    "input_category": code, "input_category_label": CATEGORY_LABELS.get(code, code),
                    "hectares": _ha(values["hectares"]), "estimated_cost": _money(values["estimated_cost"]),
                    "approved_hectares": category_limits.get((crop_id, code), {}).get("approved_hectares"),
                    "remaining_hectares": category_limits.get((crop_id, code), {}).get("remaining_hectares"),
                }
                for code, values in sorted(crop["categories"].items(), key=lambda item: INPUT_CATEGORIES.index(item[0]) if item[0] in INPUT_CATEGORIES else 9)
            ],
            "varieties": [
                {
                    **{key: value for key, value in variety.items() if key != "farmers"}, "farmers": len(variety["farmers"]),
                    "hectares": _ha(variety["hectares"]), "quantity": _qty(variety["quantity"]), "estimated_cost": _money(variety["estimated_cost"]),
                    "rate_per_hectare": _qty(variety["rate_per_hectare"]), "unit_price": _money(variety["unit_price"]),
                    "requested_hectares": variety_limits.get(requirement_id, {}).get("requested_hectares"),
                    "approved_hectares": variety_limits.get(requirement_id, {}).get("approved_hectares"),
                    "remaining_hectares": variety_limits.get(requirement_id, {}).get("remaining_hectares"),
                }
                for requirement_id, variety in sorted(crop["varieties"].items(), key=lambda item: (INPUT_CATEGORIES.index(item[1]["input_category"]) if item[1]["input_category"] in INPUT_CATEGORIES else 9, item[1]["product_name"]))
            ],
        })

    events = [
        {
            "id": event.pk, "action": event.action, "action_label": event.get_action_display(), "actor_name": event.actor_name,
            "remarks": event.remarks, "detail": event.detail or {}, "created_at": event.created_at.isoformat(),
        }
        for event in supply.events.all()
    ]
    approved_total = sum((Decimal(row["approved_hectares"]) for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_CROP), ZERO)
    requested_total = sum((Decimal(row["requested_hectares"]) for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_CROP), ZERO)
    limits_changed = bool(supply.limits_changed_at and supply.status in (InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED, InputSupplyRequest.STATUS_CONFIRMATION))
    return {
        "id": supply.pk, "reference": supply.reference, "stage": supply.stage, "stage_label": supply.get_stage_display(),
        "status": supply.status, "status_label": supply.get_status_display(), "editable": _can_edit(supply),
        "lead_farmer": supply.lead_farmer_id, "lead_farmer_name": person_name(supply.lead_farmer),
        "programme": supply.programme_id, "programme_name": supply.programme.name,
        "season": supply.season_id, "season_name": supply.season.name,
        "crop_season": supply.season_code, "crop_season_label": season_label(supply),
        "earlier_workflow": supply.crop_id is not None,
        "farmer_count": len(farmers), "allocation_count": len(allocations),
        "hectares_total": _ha(hectares_total), "estimated_cost": _money(estimated_cost),
        "requested_hectares": _ha(requested_total) if limit_rows else _ha(hectares_total),
        "approved_hectares": _ha(approved_total) if limit_rows else (_ha(hectares_total) if supply.status == InputSupplyRequest.STATUS_APPROVED else None),
        "difference_hectares": _ha(approved_total - requested_total) if limit_rows else None,
        "hectares_capped": supply.hectares_capped,
        "remaining_hectares": _ha(approved_total - hectares_total) if limit_rows else None,
        "limits_changed": limits_changed, "limits_changed_at": supply.limits_changed_at.isoformat() if supply.limits_changed_at else None,
        "submitted_at": supply.submitted_at.isoformat() if supply.submitted_at else None,
        "reviewed_at": supply.reviewed_at.isoformat() if supply.reviewed_at else None, "reviewed_by_name": person_name(supply.reviewed_by),
        "decision_notes": supply.decision_notes,
        "allocations": allocations, "crops": crop_rows, "limits": limit_rows, "events": events,
        "official_allocations": list(supply.allocations.values_list("allocation_id", flat=True)),
    }


def _variety_payload(requirement):
    return {
        "requirement": requirement.pk, "input_category": requirement.input_category,
        "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
        "product_name": _product_name(requirement), "unit": catalogue_unit(requirement),
        "rate_per_hectare": _qty(requirement.rate_per_hectare), "unit_price": _money(requirement.cost_per_unit),
        "pack_label": requirement.pack_label, "pack_size": _qty(requirement.pack_size) if requirement.pack_size else None,
        "pack_price": _money(requirement.pack_price),
    }


def options_for(*, lead, season_id, crop_season):
    """What a lead farmer can allocate in one agricultural year and season."""
    lead = _lead(lead)
    season = _load(Season, season_id, "agricultural year")
    crop_season = str(crop_season or "SUMMER").upper()
    requirements = (
        CropInputRequirement.objects.select_related("programme", "crop", "input_product")
        .filter(programme__is_active=True, active=True, input_product__isnull=False, crop__category=crop_season,
                programme__programme_crops__crop_id=F("crop_id"), programme__programme_crops__active=True)
        .filter(Q(programme__season=season) | Q(programme__season__isnull=True)).distinct()
    )
    programmes = {}
    for requirement in requirements.order_by("programme__name", "crop__name", "input_category", "input_product__name"):
        if requirement.input_category not in (requirement.programme.input_categories or []) or not requirement.rate_per_hectare or requirement.rate_per_hectare <= 0:
            continue
        programme = programmes.setdefault(requirement.programme_id, {"programme": requirement.programme_id, "programme_name": requirement.programme.name, "crops": {}})
        crop = programme["crops"].setdefault(requirement.crop_id, {"crop": requirement.crop_id, "crop_name": requirement.crop.name, "varieties": []})
        crop["varieties"].append(_variety_payload(requirement))
    farmers = Farmer.objects.filter(cluster_id=lead.assigned_cluster_id, is_active=True).prefetch_related("farms", "crop_allocations")
    farmer_rows = [
        {
            "id": farmer.pk, "name": farmer.full_name, "membership_number": farmer.membership_number,
            "farms": [{"id": farm.pk, "name": farm.farm_name} for farm in farmer.farms.all() if farm.is_active],
            "crops": [{"crop": row.crop_id, "hectares": _ha(row.hectares)} for row in farmer.crop_allocations.all() if row.season_id == season.pk],
        }
        for farmer in farmers.order_by("surname", "first_name")
    ]
    return {
        "season": season.pk, "season_name": season.name, "crop_season": crop_season, "crop_season_label": SEASON_LABELS.get(crop_season, ""),
        "farmers": farmer_rows,
        "programmes": [{**programme, "crops": list(programme["crops"].values())} for programme in programmes.values()],
    }


def consolidated(*, season_id, crop_season=None, programme_id=None):
    """Admin's totals across every lead farmer's submission, excluding rejected ones."""
    queryset = InputSupplyRequest.objects.filter(season_id=season_id).exclude(status=InputSupplyRequest.STATUS_REJECTED).select_related("lead_farmer", "programme", "season", "crop")
    if crop_season:
        queryset = queryset.filter(Q(crop_season=crop_season) | Q(crop__category=crop_season))
    if programme_id:
        queryset = queryset.filter(programme_id=programme_id)
    leads = []
    varieties = {}
    for supply in queryset.order_by("programme__name", "lead_farmer__first_name"):
        data = present(supply)
        leads.append({
            "id": supply.pk, "reference": supply.reference, "lead_farmer_name": data["lead_farmer_name"], "programme_name": data["programme_name"],
            "status": supply.status, "status_label": data["status_label"], "farmer_count": data["farmer_count"],
            "requested_hectares": data["requested_hectares"], "approved_hectares": data["approved_hectares"],
            "difference_hectares": data["difference_hectares"], "distributed_hectares": data["hectares_total"], "estimated_cost": data["estimated_cost"],
        })
        for crop in data["crops"]:
            for variety in crop["varieties"]:
                key = (data["programme_name"], crop["crop_name"], variety["requirement"])
                row = varieties.setdefault(key, {
                    "programme_name": data["programme_name"], "crop_name": crop["crop_name"], "input_category_label": variety["input_category_label"],
                    "product_name": variety["product_name"], "unit": variety["unit"], "hectares": ZERO, "quantity": ZERO, "estimated_cost": ZERO,
                    "approved_hectares": ZERO, "lead_farmers": 0,
                })
                row["hectares"] += Decimal(variety["hectares"])
                row["quantity"] += Decimal(variety["quantity"])
                row["estimated_cost"] += Decimal(variety["estimated_cost"] or 0)
                row["approved_hectares"] += Decimal(variety["approved_hectares"] or 0)
                row["lead_farmers"] += 1
    return {
        "counts": {
            status: queryset.filter(status=status).count()
            for status in (InputSupplyRequest.STATUS_SUBMITTED, InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_CONFIRMATION, InputSupplyRequest.STATUS_APPROVED)
        },
        "lead_farmers": leads,
        "varieties": [
            {**row, "hectares": _ha(row["hectares"]), "quantity": _qty(row["quantity"]), "estimated_cost": _money(row["estimated_cost"]), "approved_hectares": _ha(row["approved_hectares"])}
            for row in sorted(varieties.values(), key=lambda row: (row["programme_name"], row["crop_name"], row["input_category_label"], row["product_name"]))
        ],
    }


def _measured_at(measured, *, crop_id, category, requirement_id):
    """Hectares from measure() at the level the filters ask for: variety, input type, or crop land."""
    if requirement_id:
        return measured["varieties"].get(requirement_id, ZERO)
    if category:
        return sum((value for (crop, code), value in measured["categories"].items() if code == category and (not crop_id or crop == crop_id)), ZERO)
    return sum((value for crop, value in measured["crops"].items() if not crop_id or crop == crop_id), ZERO)


def _limits_at(limits, field, *, crop_id, category, requirement_id):
    if requirement_id:
        rows = [limit for limit in limits if limit.scope == InputSupplyLimit.SCOPE_VARIETY and limit.requirement_id == requirement_id]
    elif category:
        rows = [limit for limit in limits if limit.scope == InputSupplyLimit.SCOPE_CATEGORY and limit.input_category == category and (not crop_id or limit.crop_id == crop_id)]
    else:
        rows = [limit for limit in limits if limit.scope == InputSupplyLimit.SCOPE_CROP and (not crop_id or limit.crop_id == crop_id)]
    return sum((Decimal(getattr(limit, field)) for limit in rows), ZERO)


def programme_progress(*, programme_id, crop_season=None, crop_id=None, category=None, requirement_id=None, lead_id=None):
    """How far a programme's hectares have got, worked out from the saved submissions.

    Requested: hectares lead farmers sent to Admin. Approved: the maximums Admin set, or the
    requested hectares where Admin approved a submission as it was. Distributed: farmer
    allocations in submissions Admin has approved or limited (provisional until approved).
    Finally approved: allocations in approved submissions. Awaiting decision: submitted
    hectares Admin has not decided on yet. Drafts and rejected submissions are left out.
    """
    programme = _load(Programme, programme_id, "programme")
    to_int = lambda value: int(value) if str(value or "").isdigit() else None
    crop_id, requirement_id, lead_id = to_int(crop_id), to_int(requirement_id), to_int(lead_id)
    category = str(category or "").upper() or None
    if requirement_id:
        requirement = CropInputRequirement.objects.filter(pk=requirement_id, programme=programme).first()
        if requirement is None:
            raise SupplyError("That variety is not in this programme's catalogue.")
    queryset = (
        InputSupplyRequest.objects.filter(programme=programme)
        .exclude(status__in=[InputSupplyRequest.STATUS_DRAFT, InputSupplyRequest.STATUS_REJECTED])
        .select_related("lead_farmer", "crop").prefetch_related("limits")
    )
    if crop_season:
        queryset = queryset.filter(Q(crop_season=crop_season) | Q(crop__category=crop_season))
    leads = {}
    for supply in queryset:
        level = {"crop_id": crop_id, "category": category, "requirement_id": requirement_id}
        distributed = _measured_at(measure(supply), **level)
        limits = list(supply.limits.all())
        approved_status = supply.status == InputSupplyRequest.STATUS_APPROVED
        if limits:
            requested, approved, decided = _limits_at(limits, "requested_hectares", **level), _limits_at(limits, "approved_hectares", **level), True
        elif approved_status:
            requested, approved, decided = distributed, distributed, True
        else:
            requested, approved, decided = distributed, ZERO, False
        if not (requested or distributed or approved):
            continue
        row = leads.setdefault(supply.lead_farmer_id, {
            "lead_farmer": supply.lead_farmer_id, "lead_farmer_name": person_name(supply.lead_farmer), "submissions": 0,
            "requested": ZERO, "approved": ZERO, "distributed": ZERO, "final": ZERO, "awaiting": ZERO,
        })
        row["submissions"] += 1
        row["requested"] += requested
        if decided:
            row["approved"] += approved
            row["distributed"] += distributed
        else:
            row["awaiting"] += distributed
        if approved_status:
            row["final"] += distributed

    def shaped(row):
        remaining = row["approved"] - row["distributed"]
        progress = (row["distributed"] / row["approved"] * 100).quantize(Decimal("0.1")) if row["approved"] else None
        return {
            **{key: value for key, value in row.items() if key not in ("requested", "approved", "distributed", "final", "awaiting")},
            "requested_hectares": _ha(row["requested"]), "approved_hectares": _ha(row["approved"]),
            "distributed_hectares": _ha(row["distributed"]), "remaining_hectares": _ha(remaining),
            "final_hectares": _ha(row["final"]), "awaiting_hectares": _ha(row["awaiting"]),
            "provisional_hectares": _ha(row["distributed"] - row["final"]),
            "progress_percent": str(progress) if progress is not None else None,
        }

    rows = sorted(leads.values(), key=lambda row: row["lead_farmer_name"].lower())
    if lead_id:
        rows = [row for row in rows if row["lead_farmer"] == lead_id]
    totals = {"requested": ZERO, "approved": ZERO, "distributed": ZERO, "final": ZERO, "awaiting": ZERO, "submissions": 0}
    for row in rows:
        for key in totals:
            totals[key] += row[key]
    requirements = CropInputRequirement.objects.filter(programme=programme, active=True).select_related("crop", "input_product").order_by("crop__name", "input_category")
    if crop_season:
        requirements = requirements.filter(crop__category=crop_season)
    return {
        "programme": programme.pk, "programme_name": programme.name,
        "totals": shaped({**totals, "lead_farmer": None, "lead_farmer_name": ""}),
        "lead_farmers": [shaped(row) for row in rows],
        "options": {
            "crops": [{"id": crop, "name": name} for crop, name in sorted({(item.crop_id, item.crop.name) for item in requirements}, key=lambda pair: pair[1])],
            "categories": [code for code in INPUT_CATEGORIES if any(item.input_category == code for item in requirements)],
            "varieties": [
                {"requirement": item.pk, "crop": item.crop_id, "input_category": item.input_category, "name": f"{_product_name(item)} · {item.crop.name}"}
                for item in requirements
            ],
            "lead_farmers": [{"id": row["lead_farmer"], "name": row["lead_farmer_name"]} for row in sorted(leads.values(), key=lambda row: row["lead_farmer_name"].lower())],
        },
    }


def supply_queryset():
    return InputSupplyRequest.objects.select_related("lead_farmer", "programme", "season", "crop", "reviewed_by").prefetch_related("events")
