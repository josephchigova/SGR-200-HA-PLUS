"""Lead-farmer input allocations, and Admin's hectare decision.

Admin configures the programme catalogue: varieties, the rate per hectare and the price.
A lead farmer allocates hectares of those varieties to their own farmers. Quantity and
cost are calculated here. Nothing the browser sends for a quantity, a price or a total
is stored.

The lead farmer submits the consolidated request. Admin either accepts those hectares or
sets a lower maximum for that lead farmer, at crop, input-category and variety level.
Those maximums are not given to individual farmers. The lead farmer distributes them,
then submits the distribution. Only Admin's confirmation creates the farmer allocations.

There is no variety cap and no stock balance.
"""

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.farmers.models import Farmer
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
from .programme_allocation import CATEGORY_LABELS, FOUR, TWO, crop_hectares, covered_categories

REVIEW_ROLES = (User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_PROGRAMME_OFFICER)
SCOPE_ORDER = {
    InputSupplyLimit.SCOPE_CROP: 0,
    InputSupplyLimit.SCOPE_CATEGORY: 1,
    InputSupplyLimit.SCOPE_VARIETY: 2,
}


class SupplyError(ValueError):
    pass


def _decimal(value, label):
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise SupplyError(f"Enter {label} as a number.") from error
    if number.is_nan():
        raise SupplyError(f"Enter {label} as a number.")
    return number


def _money(value):
    return str(Decimal(value).quantize(TWO)) if value is not None else None


def _ha(value):
    return str(Decimal(value or 0).quantize(TWO))


def _qty(value):
    return format(Decimal(value or 0).quantize(FOUR), "f")


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


def _requirement(pk):
    if pk in (None, ""):
        raise SupplyError("Select the variety.")
    try:
        return CropInputRequirement.objects.select_related("input_product", "programme", "crop").get(pk=pk)
    except (CropInputRequirement.DoesNotExist, ValueError, TypeError) as error:
        raise SupplyError("Select a valid variety.") from error


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
        return Decimal("0.00")
    return (Decimal(quantity) * Decimal(requirement.cost_per_unit)).quantize(TWO)


def _event(supply, action, user, remarks="", detail=None):
    return InputSupplyEvent.objects.create(
        request=supply,
        action=action,
        actor=user if getattr(user, "is_authenticated", False) else None,
        actor_name=person_name(user),
        remarks=(remarks or "").strip(),
        detail=detail or {},
    )


def _notify(recipients, *, kind, key, title, body, url, tone):
    for recipient in recipients:
        if recipient is None:
            continue
        Notification.objects.get_or_create(
            recipient=recipient,
            dedupe_key=key,
            defaults={"kind": kind, "title": title[:200], "body": body, "url": url, "tone": tone},
        )


def _reviewers():
    return User.objects.filter(is_active=True).filter(Q(role__in=REVIEW_ROLES) | Q(is_superuser=True)).distinct()


def _notify_submitted(supply, event, final=False):
    verb = "submitted the final distribution for" if final else "submitted"
    _notify(
        _reviewers(),
        kind=Notification.KIND_INPUT_SUPPLY_SUBMITTED,
        key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} {'awaiting confirmation' if final else 'submitted'}",
        body=(
            f"{person_name(supply.lead_farmer)} {verb} {supply.crop.name} inputs "
            f"for {supply.programme.name}, {supply.season.name}."
        ),
        url="/input-approvals",
        tone="warning",
    )


def _notify_decided(supply, event, tone, url="/my-input-requests"):
    _notify(
        [supply.lead_farmer],
        kind=Notification.KIND_INPUT_SUPPLY_DECIDED,
        key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} {supply.get_status_display().lower()}",
        body=supply.decision_notes or f"Admin {supply.get_status_display().lower()} {supply.reference}.",
        url=url,
        tone=tone,
    )


def _context(*, programme_id, season_id, crop_id, crop_season=None):
    programme = _load(Programme, programme_id, "programme")
    season = _load(Season, season_id, "agricultural year")
    crop = _load(Crop, crop_id, "crop")
    if crop_season and crop.category != crop_season:
        raise SupplyError(f"{crop.name} is a {crop.get_category_display().lower()} crop.")
    if season.status != Season.STATUS_ACTIVE:
        raise SupplyError(f"{season.name} is not the active agricultural year, so its allocations cannot be changed.")
    if not programme.is_active:
        raise SupplyError(f"{programme.name} is inactive.")
    if programme.season_id and programme.season_id != season.pk:
        raise SupplyError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
    if not programme.supports_crop(crop):
        raise SupplyError(f"{programme.name} does not support {crop.name}.")
    return programme, season, crop


def _can_edit(supply):
    if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION:
        return supply.status in (InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED)
    return supply.status in (InputSupplyRequest.STATUS_DRAFT, InputSupplyRequest.STATUS_RETURNED)


def hectares_in_use(farmer, crop, season, exclude_request_id=None):
    """Crop hectares already spoken for: live allocations, plus every open submission."""
    allocated = InputAllocation.objects.filter(farmer=farmer, season=season).exclude(
        status=InputAllocation.STATUS_CANCELLED,
    ).filter(Q(crop_reference=crop) | Q(crop_reference__isnull=True, crop__iexact=crop.name)).aggregate(total=Sum("hectares"))["total"]
    open_rows = InputSupplyFarmer.objects.filter(
        farmer=farmer,
        request__crop=crop,
        request__season=season,
        request__status__in=InputSupplyRequest.OPEN_STATUSES,
    )
    if exclude_request_id:
        open_rows = open_rows.exclude(request_id=exclude_request_id)
    drafted = open_rows.aggregate(total=Sum("hectares"))["total"]
    return Decimal(allocated or 0) + Decimal(drafted or 0)


def _category_sums(lines):
    totals = {}
    for line in lines:
        category = line["requirement"].input_category
        totals[category] = totals.get(category, Decimal("0.00")) + line["hectares"]
    return totals


def land_hectares(lines):
    """Hectares of land these lines cover.

    Varieties of one input category are applied to different ground, so they add up.
    Seed, fertilizer and chemicals go on the same ground, so the land is the largest category.
    """
    totals = _category_sums(lines)
    if not totals:
        return Decimal("0.00")
    return max(totals.values())


def measure(entries):
    """Hectares at variety, category and crop level. Crop hectares are land, not a sum of every input."""
    varieties = {}
    categories = {}
    crop = Decimal("0.00")
    for entry in entries:
        by_category = _category_sums(entry["lines"])
        entry["land"] = max(by_category.values()) if by_category else Decimal("0.00")
        crop += entry["land"]
        for line in entry["lines"]:
            requirement = line["requirement"]
            varieties[requirement.pk] = varieties.get(requirement.pk, Decimal("0.00")) + line["hectares"]
        for category, hectares in by_category.items():
            categories[category] = categories.get(category, Decimal("0.00")) + hectares
    return {"varieties": varieties, "categories": categories, "crop": crop}


def build_entries(*, lead, programme, season, crop, farmers, exclude_request_id=None):
    """Turn farmer and variety hectares into calculated lines. Raises SupplyError."""
    if lead.role != User.ROLE_LEAD_FARMER:
        raise SupplyError("Only a lead farmer can allocate inputs to farmers.")
    if not lead.assigned_cluster_id:
        raise SupplyError("Your account is not assigned to a cluster, so you have no farmers to allocate to.")
    if not farmers:
        raise SupplyError("Add at least one farmer.")

    seen_farmers = set()
    entries = []
    for item in farmers:
        farmer = _load(Farmer, item.get("farmer"), "farmer")
        if farmer.pk in seen_farmers:
            raise SupplyError(f"{farmer.full_name} is listed more than once.")
        seen_farmers.add(farmer.pk)
        if farmer.cluster_id != lead.assigned_cluster_id:
            raise SupplyError(f"{farmer.full_name} is not one of your farmers.")
        eligibility = FarmerApprovalEligibilityService.evaluate_for_arda(farmer, season)
        if not eligibility["eligible"]:
            raise SupplyError(f"{farmer.full_name} cannot receive inputs yet: " + " ".join(eligibility["reasons"]))
        if item.get("farm"):
            farm = _load(farmer.farms.model, item.get("farm"), "farm")
        else:
            farm = farmer.farms.filter(is_active=True).order_by("id").first()
        if farm is None or farm.farmer_id != farmer.pk:
            raise SupplyError(f"Select a farm belonging to {farmer.full_name}.")

        raw_lines = item.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise SupplyError(f"Enter the hectares of each variety for {farmer.full_name}.")
        seen_requirements = set()
        lines = []
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise SupplyError(f"Enter the hectares of each variety for {farmer.full_name}.")
            requirement = _requirement(raw.get("requirement"))
            if requirement.pk in seen_requirements:
                raise SupplyError(f"Each variety can be entered once for {farmer.full_name}.")
            seen_requirements.add(requirement.pk)
            if requirement.programme_id != programme.pk or requirement.crop_id != crop.pk:
                raise SupplyError(f"{requirement.item_name} is not in {programme.name}'s {crop.name} catalogue.")
            if not requirement.active or not requirement.input_product_id:
                raise SupplyError(f"{requirement.item_name} is not an active catalogue variety.")
            if requirement.input_category not in (programme.input_categories or []):
                raise SupplyError(f"{programme.name} does not supply {CATEGORY_LABELS.get(requirement.input_category, 'that input').lower()}.")
            if not requirement.rate_per_hectare or requirement.rate_per_hectare <= 0:
                raise SupplyError(f"{requirement.input_product.name} has no application rate per hectare in the catalogue.")
            if (not requirement.cost_per_unit or requirement.cost_per_unit <= 0) and not (
                requirement.pack_size and requirement.pack_price and requirement.pack_price > 0
            ):
                raise SupplyError(f"Set a unit price for {requirement.input_product.name} in the crop catalogue.")
            area = _decimal(raw.get("hectares"), f"hectares for {requirement.input_product.name}").quantize(TWO)
            if area <= 0:
                raise SupplyError(f"Enter hectares greater than zero for {requirement.input_product.name}.")
            quantity = (area * Decimal(requirement.rate_per_hectare)).quantize(FOUR)
            if quantity <= 0:
                raise SupplyError(f"{requirement.input_product.name} works out to no quantity for {farmer.full_name}.")
            price = requirement.cost_per_unit
            lines.append({
                "requirement": requirement,
                "hectares": area,
                "rate_per_hectare": Decimal(requirement.rate_per_hectare),
                "quantity": quantity,
                "unit": catalogue_unit(requirement),
                "unit_price": Decimal(price) if price is not None else None,
                "estimated_cost": line_cost(quantity, requirement),
            })

        by_category = _category_sums(lines)
        limit = crop_hectares(farmer, crop, season)
        used = hectares_in_use(farmer, crop, season, exclude_request_id=exclude_request_id)
        ceiling = Decimal(limit) - used if limit is not None else None
        for category, area in by_category.items():
            label = CATEGORY_LABELS.get(category, category)
            if ceiling is not None and area > ceiling:
                allowance = Decimal(limit).quantize(TWO)
                raise SupplyError(
                    f"{farmer.full_name} has {allowance} ha of {crop.name} for {season.name}. "
                    f"{used.quantize(TWO)} ha is already allocated or in another submission, "
                    f"so {area} ha of {label.lower()} is too much."
                )
            if ceiling is None and area > Decimal(farm.arable_hectares or 0):
                raise SupplyError(f"Hectares of {label.lower()} for {farmer.full_name} exceed the farm's arable land.")

        covered = covered_categories(farmer=farmer, crop=crop, season=season)
        for category in by_category:
            if category in covered:
                label = CATEGORY_LABELS.get(category, category).lower()
                raise SupplyError(
                    f"{farmer.full_name} already has {label} for {crop.name} in {season.name}. "
                    "Cancel that allocation before requesting it again."
                )
        entries.append({"farmer": farmer, "farm": farm, "lines": lines})
    measure(entries)
    return entries


def _enforce_limits(supply, measured):
    limits = list(supply.limits.select_related("requirement__input_product"))
    if supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION and not limits:
        raise SupplyError("Admin has not set the approved hectares for this submission.")
    for limit in limits:
        if limit.scope == InputSupplyLimit.SCOPE_VARIETY:
            used = measured["varieties"].get(limit.requirement_id, Decimal("0.00"))
            name = limit.requirement.input_product.name if limit.requirement_id and limit.requirement.input_product_id else "That variety"
            kind = name
        elif limit.scope == InputSupplyLimit.SCOPE_CATEGORY:
            used = measured["categories"].get(limit.input_category, Decimal("0.00"))
            kind = CATEGORY_LABELS.get(limit.input_category, limit.input_category)
        else:
            used = measured["crop"]
            kind = supply.crop.name
        if used > Decimal(limit.approved_hectares):
            raise SupplyError(
                f"{kind} is limited to {_ha(limit.approved_hectares)} ha. "
                f"This distribution uses {_ha(used)} ha. Unused hectares can stay unallocated, but the approved maximum cannot be exceeded."
            )


def _entries_from_request(supply):
    farmers = []
    for entry in supply.farmers.prefetch_related("lines"):
        farmers.append({
            "farmer": entry.farmer_id,
            "farm": entry.farm_id,
            "lines": [
                {"requirement": line.requirement_id, "hectares": line.hectares}
                for line in entry.lines.all()
            ],
        })
    entries = build_entries(
        lead=supply.lead_farmer,
        programme=supply.programme,
        season=supply.season,
        crop=supply.crop,
        farmers=farmers,
        exclude_request_id=supply.pk,
    )
    return entries


def _apply(supply, entries):
    supply.farmers.all().delete()
    for entry in entries:
        row = InputSupplyFarmer.objects.create(
            request=supply, farmer=entry["farmer"], farm=entry["farm"], hectares=entry["land"],
        )
        for line in entry["lines"]:
            InputSupplyLine.objects.create(
                farmer_entry=row,
                requirement=line["requirement"],
                hectares=line["hectares"],
                rate_per_hectare=line["rate_per_hectare"],
                quantity=line["quantity"],
                unit=line["unit"],
                unit_price=line["unit_price"],
                estimated_cost=line["estimated_cost"],
            )


def _lock_open(lead, programme, season, crop):
    return list(
        InputSupplyRequest.objects.select_for_update().filter(
            lead_farmer=lead, programme=programme, season=season, crop=crop,
            status__in=InputSupplyRequest.OPEN_STATUSES,
        ).order_by("id")
    )


def _waiting_message(supply):
    if supply.status == InputSupplyRequest.STATUS_CONFIRMATION:
        return f"{supply.reference} is waiting for Admin to confirm the distribution."
    if supply.status == InputSupplyRequest.STATUS_SUBMITTED:
        return f"{supply.reference} is waiting for Admin to set the approved hectares."
    return f"{supply.reference} is {supply.get_status_display().lower()} and cannot be changed."


@transaction.atomic
def save_draft(*, lead, programme_id, season_id, crop_id, farmers, crop_season=None):
    programme, season, crop = _context(programme_id=programme_id, season_id=season_id, crop_id=crop_id, crop_season=crop_season)
    open_rows = _lock_open(lead, programme, season, crop)
    existing = open_rows[-1] if open_rows else None
    if existing and not _can_edit(existing):
        raise SupplyError(_waiting_message(existing))
    entries = build_entries(
        lead=lead, programme=programme, season=season, crop=crop, farmers=farmers,
        exclude_request_id=existing.pk if existing else None,
    )
    if existing and existing.stage == InputSupplyRequest.STAGE_DISTRIBUTION:
        _enforce_limits(existing, measure(entries))
    created = existing is None
    if created:
        try:
            supply = InputSupplyRequest.objects.create(
                reference=f"TMP{uuid.uuid4().hex}",
                lead_farmer=lead,
                programme=programme,
                season=season,
                crop=crop,
                stage=InputSupplyRequest.STAGE_REQUEST,
                status=InputSupplyRequest.STATUS_DRAFT,
            )
        except IntegrityError as error:
            raise SupplyError("You already have an open submission for this programme, year and crop. Refresh and continue that one.") from error
        supply.reference = f"LF{supply.pk:05d}"
        supply.save(update_fields=["reference"])
    else:
        supply = existing
    _apply(supply, entries)
    if created:
        _event(supply, InputSupplyEvent.SAVED, lead, "Draft saved.")
    elif supply.status == InputSupplyRequest.STATUS_RETURNED:
        _event(supply, InputSupplyEvent.CORRECTED, lead, "Allocations updated after Admin asked for corrections.")
    elif supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION:
        _event(supply, InputSupplyEvent.CORRECTED, lead, "Farmer distribution updated within the approved hectares.")
    return supply, created


@transaction.atomic
def submit(*, request_id, user):
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    if supply.lead_farmer_id != user.pk:
        raise SupplyError("You can only submit your own request.")
    if not _can_edit(supply):
        raise SupplyError(_waiting_message(supply))
    entries = _entries_from_request(supply)
    if not entries:
        raise SupplyError("Add at least one farmer before submitting.")
    final = supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION
    if final:
        _enforce_limits(supply, measure(entries))
    _apply(supply, entries)
    was_returned = supply.status == InputSupplyRequest.STATUS_RETURNED
    if final:
        supply.status = InputSupplyRequest.STATUS_CONFIRMATION
        action = InputSupplyEvent.FINAL_RESUBMITTED if was_returned else InputSupplyEvent.FINAL_SUBMITTED
    else:
        supply.status = InputSupplyRequest.STATUS_SUBMITTED
        action = InputSupplyEvent.RESUBMITTED if was_returned else InputSupplyEvent.SUBMITTED
    supply.submitted_at = timezone.now()
    supply.decision_notes = ""
    supply.reviewed_at = None
    supply.reviewed_by = None
    supply.save(update_fields=["status", "submitted_at", "decision_notes", "reviewed_at", "reviewed_by", "updated_at"])
    event = _event(supply, action, user)
    _notify_submitted(supply, event, final=final)
    return supply


def _decision_user(user):
    if not user or not user.is_authenticated:
        raise SupplyError("Sign in again.")
    if user.is_superuser or user.role in REVIEW_ROLES:
        return user
    raise SupplyError("Only an administrator can review input submissions.")


def _requested_levels(supply, entries):
    measured = measure(entries)
    levels = [{
        "scope": InputSupplyLimit.SCOPE_CROP,
        "input_category": "",
        "requirement": None,
        "requested": measured["crop"],
    }]
    for category in INPUT_CATEGORIES:
        if category not in measured["categories"]:
            continue
        levels.append({
            "scope": InputSupplyLimit.SCOPE_CATEGORY,
            "input_category": category,
            "requirement": None,
            "requested": measured["categories"][category],
        })
    requirements = {
        line["requirement"].pk: line["requirement"]
        for entry in entries for line in entry["lines"]
    }
    for requirement_id, hectares in measured["varieties"].items():
        levels.append({
            "scope": InputSupplyLimit.SCOPE_VARIETY,
            "input_category": requirements[requirement_id].input_category,
            "requirement": requirements[requirement_id],
            "requested": hectares,
        })
    return levels


def _approved_from_client(levels, payload):
    """Read only the approved hectares Admin typed. Requested hectares stay the server's figures."""
    supplied = {}
    if not isinstance(payload, list):
        raise SupplyError("Enter the approved hectares for the crop, each input category and each variety.")
    for item in payload:
        if not isinstance(item, dict):
            raise SupplyError("Enter the approved hectares as numbers.")
        scope = str(item.get("scope") or "").strip().upper()
        if scope == InputSupplyLimit.SCOPE_CROP:
            key = (scope, "", None)
        elif scope == InputSupplyLimit.SCOPE_CATEGORY:
            key = (scope, str(item.get("input_category") or "").strip().upper(), None)
        elif scope == InputSupplyLimit.SCOPE_VARIETY:
            try:
                key = (scope, "", int(item.get("requirement")))
            except (TypeError, ValueError) as error:
                raise SupplyError("Select the variety whose hectares you are setting.") from error
        else:
            raise SupplyError("Choose a crop, input category or variety for each hectare limit.")
        if "approved_hectares" not in item:
            continue
        approved = _decimal(item.get("approved_hectares"), "approved hectares").quantize(TWO)
        if approved < 0:
            raise SupplyError("Approved hectares cannot be negative.")
        supplied[key] = approved

    resolved = []
    crop_approved = supplied.get((InputSupplyLimit.SCOPE_CROP, "", None))
    if crop_approved is None:
        crop_approved = next(level["requested"] for level in levels if level["scope"] == InputSupplyLimit.SCOPE_CROP)
    if crop_approved <= 0:
        raise SupplyError("Enter approved hectares greater than zero, or reject the submission.")
    categories = {}
    for level in levels:
        if level["scope"] == InputSupplyLimit.SCOPE_CROP:
            approved = crop_approved
        elif level["scope"] == InputSupplyLimit.SCOPE_CATEGORY:
            key = (level["scope"], level["input_category"], None)
            approved = supplied.get(key, min(level["requested"], crop_approved))
            if approved > crop_approved:
                label = CATEGORY_LABELS.get(level["input_category"], level["input_category"])
                raise SupplyError(f"{label} cannot be approved for more than the {_ha(crop_approved)} ha allowed for the crop.")
            categories[level["input_category"]] = approved
        else:
            parent = categories.get(level["input_category"], crop_approved)
            key = (level["scope"], "", level["requirement"].pk)
            approved = supplied.get(key, min(level["requested"], parent))
            if approved > parent:
                name = level["requirement"].input_product.name
                raise SupplyError(f"{name} cannot be approved for more hectares than its input category.")
        resolved.append({**level, "approved": approved})
    return resolved


def _write_limits(supply, resolved, user, *, keep_requested):
    previous = {
        (limit.scope, limit.input_category, limit.requirement_id): limit
        for limit in supply.limits.all()
    }
    seen = set()
    for level in resolved:
        requirement = level["requirement"]
        key = (level["scope"], level["input_category"], requirement.pk if requirement else None)
        seen.add(key)
        current = previous.get(key)
        requested = current.requested_hectares if keep_requested and current else level["requested"]
        if current:
            current.requested_hectares = requested
            current.approved_hectares = level["approved"]
            current.updated_by = user
            current.save(update_fields=["requested_hectares", "approved_hectares", "updated_by", "updated_at"])
        else:
            InputSupplyLimit.objects.create(
                request=supply,
                scope=level["scope"],
                input_category=level["input_category"],
                requirement=requirement,
                requested_hectares=requested,
                approved_hectares=level["approved"],
                updated_by=user,
            )
    stale = [limit.pk for key, limit in previous.items() if key not in seen]
    if stale and not keep_requested:
        InputSupplyLimit.objects.filter(pk__in=stale).delete()


def _limit_detail(supply):
    rows = []
    for limit in supply.limits.select_related("requirement__input_product"):
        if limit.scope == InputSupplyLimit.SCOPE_VARIETY and limit.requirement_id and limit.requirement.input_product_id:
            name = limit.requirement.input_product.name
        elif limit.scope == InputSupplyLimit.SCOPE_CATEGORY:
            name = CATEGORY_LABELS.get(limit.input_category, limit.input_category)
        else:
            name = supply.crop.name
        rows.append({
            "scope": limit.scope,
            "name": name,
            "input_category": limit.input_category,
            "requirement": limit.requirement_id,
            "requested_hectares": _ha(limit.requested_hectares),
            "approved_hectares": _ha(limit.approved_hectares),
        })
    return rows


@transaction.atomic
def set_hectares(*, request_id, user, mode, limits, remarks=""):
    """Approve the requested hectares, or set the maximum hectares available to this lead farmer."""
    user = _decision_user(user)
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    issuing = supply.stage == InputSupplyRequest.STAGE_REQUEST and supply.status == InputSupplyRequest.STATUS_SUBMITTED
    adjusting = supply.stage == InputSupplyRequest.STAGE_DISTRIBUTION and supply.status in (
        InputSupplyRequest.STATUS_LIMITS_SET,
        InputSupplyRequest.STATUS_RETURNED,
        InputSupplyRequest.STATUS_CONFIRMATION,
    )
    if not issuing and not adjusting:
        raise SupplyError(
            f"{supply.reference} is {supply.get_status_display().lower()}. "
            "Set hectare limits on a submitted request, or adjust them before the distribution is confirmed."
        )
    choice = str(mode or "").strip().lower()
    if choice not in ("approve", "distribute"):
        raise SupplyError("Approve the requested hectares, or distribute the hectares that are available.")
    entries = _entries_from_request(supply)
    levels = _requested_levels(supply, entries)
    if choice == "approve":
        resolved = [{**level, "approved": level["requested"]} for level in levels]
        action = InputSupplyEvent.LIMITS_APPROVED
    else:
        resolved = _approved_from_client(levels, limits)
        action = InputSupplyEvent.LIMITS_ADJUSTED if adjusting else InputSupplyEvent.LIMITS_DISTRIBUTED
    before = _limit_detail(supply) if adjusting else []
    _write_limits(supply, resolved, user, keep_requested=adjusting)
    if supply.status == InputSupplyRequest.STATUS_CONFIRMATION:
        _enforce_limits(supply, measure(entries))
    note = (remarks or "").strip()
    if issuing:
        supply.stage = InputSupplyRequest.STAGE_DISTRIBUTION
        supply.status = InputSupplyRequest.STATUS_LIMITS_SET
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = note
    supply.save(update_fields=["stage", "status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    after = _limit_detail(supply)
    detail = {"limits": after}
    if before:
        detail["previous"] = before
    event = _event(supply, action, user, note, detail)
    _notify_decided(supply, event, "good", url="/input-allocations")
    return supply


@transaction.atomic
def approve(*, request_id, user, remarks=""):
    """Confirm the lead farmer's final distribution. This is the only step that allocates inputs."""
    user = _decision_user(user)
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    if supply.status != InputSupplyRequest.STATUS_CONFIRMATION:
        raise SupplyError(
            f"{supply.reference} is {supply.get_status_display().lower()}. "
            "Confirm the distribution only after the lead farmer has submitted it."
        )
    entries = _entries_from_request(supply)
    _enforce_limits(supply, measure(entries))
    _apply(supply, entries)
    try:
        selling_price = CropPricingService.resolve_price_per_tonne(crop=supply.crop, season=supply.season)
    except ValueError as error:
        raise SupplyError(str(error)) from error

    for entry in supply.farmers.select_related("farmer", "farm").prefetch_related("lines__requirement__input_product"):
        lines = list(entry.lines.all())
        total_cost = sum((line.estimated_cost for line in lines), Decimal("0.00")).quantize(TWO)
        per_hectare = (total_cost / entry.hectares).quantize(TWO) if entry.hectares else Decimal("0.00")
        allocation = InputAllocation.objects.create(
            farmer=entry.farmer,
            farm=entry.farm,
            programme=supply.programme,
            season=supply.season,
            crop_reference=supply.crop,
            crop=supply.crop.name,
            hectares=entry.hectares,
            total_input_cost=total_cost,
            calculated_input_cost_per_hectare=per_hectare,
            allocation_reference=supply.reference,
            status=InputAllocation.STATUS_ALLOCATED,
            sourced_by_category=True,
            created_by=user,
        )
        for line in lines:
            product = line.requirement.input_product
            requirement = line.requirement
            InputAllocationLine.objects.create(
                allocation=allocation,
                source_requirement=requirement,
                input_category=requirement.input_category,
                programme=supply.programme,
                input_product=product,
                group_name=CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                item_name=product.name,
                unit=line.unit,
                rate_per_hectare=line.rate_per_hectare,
                cost_per_unit=line.unit_price,
                pack_label=requirement.pack_label,
                pack_size=requirement.pack_size,
                pack_price=requirement.pack_price,
                cost_per_hectare=(line.rate_per_hectare * line.unit_price).quantize(FOUR) if line.unit_price is not None else Decimal("0.0000"),
                required_quantity=line.quantity,
                calculated_cost=line.estimated_cost,
                included_in_total=True,
            )
        RecoveryCalculationService.create_or_update_from_allocation(allocation=allocation, selling_price_per_tonne=selling_price)
        InputSupplyAllocation.objects.create(request=supply, allocation=allocation)

    supply.status = InputSupplyRequest.STATUS_APPROVED
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = (remarks or "").strip()
    supply.save(update_fields=["status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, InputSupplyEvent.APPROVED, user, supply.decision_notes)
    _notify_decided(supply, event, "good")
    return supply


@transaction.atomic
def _close(*, request_id, user, status, action, remarks, tone):
    user = _decision_user(user)
    remarks = (remarks or "").strip()
    if not remarks:
        raise SupplyError("Explain the decision so the lead farmer knows what to change.")
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    allowed = (InputSupplyRequest.STATUS_SUBMITTED, InputSupplyRequest.STATUS_CONFIRMATION)
    if action == InputSupplyEvent.REJECTED:
        allowed = allowed + (InputSupplyRequest.STATUS_LIMITS_SET, InputSupplyRequest.STATUS_RETURNED)
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
    _notify_decided(supply, event, tone, url="/input-allocations" if status == InputSupplyRequest.STATUS_RETURNED else "/my-input-requests")
    return supply


def reject(*, request_id, user, remarks):
    return _close(
        request_id=request_id, user=user, status=InputSupplyRequest.STATUS_REJECTED,
        action=InputSupplyEvent.REJECTED, remarks=remarks, tone="bad",
    )


def return_for_corrections(*, request_id, user, remarks):
    return _close(
        request_id=request_id, user=user, status=InputSupplyRequest.STATUS_RETURNED,
        action=InputSupplyEvent.RETURNED, remarks=remarks, tone="warning",
    )


@transaction.atomic
def reverse(*, request_id, user, remarks):
    """Undo a final approval. The allocations and their debt are cancelled. The hectare limits stay."""
    user = _decision_user(user)
    remarks = (remarks or "").strip()
    if not remarks:
        raise SupplyError("Give the reason for reversing this approval.")
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    if supply.status != InputSupplyRequest.STATUS_APPROVED:
        raise SupplyError("Only a confirmed allocation can be reversed.")
    links = list(supply.allocations.select_related("allocation"))
    if not links:
        raise SupplyError(f"{supply.reference} has no allocations to reverse.")
    for link in links:
        try:
            programme_allocation.cancel(allocation=link.allocation, reason=remarks, user=user)
        except programme_allocation.AllocationError as error:
            raise SupplyError(str(error)) from error
    supply.stage = InputSupplyRequest.STAGE_DISTRIBUTION
    supply.status = InputSupplyRequest.STATUS_RETURNED
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = remarks
    supply.save(update_fields=["stage", "status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, InputSupplyEvent.REVERSED, user, remarks)
    _notify_decided(supply, event, "warning", url="/input-allocations")
    return supply


def _product_name(requirement):
    if requirement.input_product_id:
        return requirement.input_product.name
    return requirement.item_name


def present(supply):
    variety_hectares = {}
    category_hectares = {}
    category_cost = {}
    farmers = []
    hectares_total = Decimal("0.00")
    estimated_cost = Decimal("0.00")
    totals = {}
    for entry in supply.farmers.all():
        hectares_total += Decimal(entry.hectares)
        by_category = {}
        lines = []
        for line in entry.lines.all():
            requirement = line.requirement
            product = _product_name(requirement)
            cost = Decimal(line.estimated_cost or 0)
            estimated_cost += cost
            variety_hectares[requirement.pk] = variety_hectares.get(requirement.pk, Decimal("0.00")) + Decimal(line.hectares)
            by_category[requirement.input_category] = by_category.get(requirement.input_category, Decimal("0.00")) + Decimal(line.hectares)
            category_cost[requirement.input_category] = category_cost.get(requirement.input_category, Decimal("0.00")) + cost
            lines.append({
                "id": line.pk,
                "requirement": requirement.pk,
                "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": product,
                "unit": line.unit,
                "hectares": _ha(line.hectares),
                "rate_per_hectare": _qty(line.rate_per_hectare),
                "quantity": _qty(line.quantity),
                "unit_price": _money(line.unit_price),
                "estimated_cost": _money(cost),
            })
            bucket = totals.setdefault(requirement.pk, {
                "requirement": requirement.pk,
                "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": product,
                "unit": line.unit,
                "hectares": Decimal("0.00"),
                "quantity": Decimal("0"),
                "estimated_cost": Decimal("0.00"),
                "rate_per_hectare": line.rate_per_hectare,
                "unit_price": line.unit_price,
            })
            bucket["hectares"] += Decimal(line.hectares)
            bucket["quantity"] += Decimal(line.quantity)
            bucket["estimated_cost"] += cost
        for category, hectares in by_category.items():
            category_hectares[category] = category_hectares.get(category, Decimal("0.00")) + hectares
        farmers.append({
            "id": entry.pk,
            "farmer": entry.farmer_id,
            "farmer_name": entry.farmer.full_name,
            "farm": entry.farm_id,
            "farm_name": entry.farm.farm_name,
            "hectares": _ha(entry.hectares),
            "lines": lines,
        })

    limit_rows = []
    for limit in supply.limits.all():
        if limit.scope == InputSupplyLimit.SCOPE_VARIETY:
            allocated = variety_hectares.get(limit.requirement_id, Decimal("0.00"))
            name = _product_name(limit.requirement) if limit.requirement_id else ""
            category = limit.requirement.input_category if limit.requirement_id else ""
        elif limit.scope == InputSupplyLimit.SCOPE_CATEGORY:
            allocated = category_hectares.get(limit.input_category, Decimal("0.00"))
            name = CATEGORY_LABELS.get(limit.input_category, limit.input_category)
            category = limit.input_category
        else:
            allocated = hectares_total
            name = supply.crop.name
            category = ""
        remaining = Decimal(limit.approved_hectares) - allocated
        limit_rows.append({
            "id": limit.pk,
            "scope": limit.scope,
            "scope_label": limit.get_scope_display(),
            "input_category": category,
            "input_category_label": CATEGORY_LABELS.get(category, ""),
            "requirement": limit.requirement_id,
            "name": name,
            "requested_hectares": _ha(limit.requested_hectares),
            "approved_hectares": _ha(limit.approved_hectares),
            "allocated_hectares": _ha(allocated),
            "remaining_hectares": _ha(remaining),
            "updated_at": limit.updated_at.isoformat() if limit.updated_at else None,
            "updated_by_name": person_name(limit.updated_by),
        })
    limit_rows.sort(key=lambda row: (SCOPE_ORDER.get(row["scope"], 9), row["input_category"], row["name"]))
    limits_by_variety = {
        row["requirement"]: row for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_VARIETY
    }
    limits_by_category = {
        row["input_category"]: row for row in limit_rows if row["scope"] == InputSupplyLimit.SCOPE_CATEGORY
    }

    categories = []
    for category, hectares in sorted(category_hectares.items()):
        limit = limits_by_category.get(category)
        categories.append({
            "input_category": category,
            "input_category_label": CATEGORY_LABELS.get(category, category),
            "hectares": _ha(hectares),
            "estimated_cost": _money(category_cost.get(category, Decimal("0.00"))),
            "requested_hectares": limit["requested_hectares"] if limit else None,
            "approved_hectares": limit["approved_hectares"] if limit else None,
        })

    events = [
        {
            "id": event.pk,
            "action": event.action,
            "action_label": event.get_action_display(),
            "actor_name": event.actor_name,
            "remarks": event.remarks,
            "detail": event.detail or {},
            "created_at": event.created_at.isoformat(),
        }
        for event in supply.events.all()
    ]
    return {
        "id": supply.pk,
        "reference": supply.reference,
        "stage": supply.stage,
        "stage_label": supply.get_stage_display(),
        "status": supply.status,
        "status_label": supply.get_status_display(),
        "lead_farmer": supply.lead_farmer_id,
        "lead_farmer_name": person_name(supply.lead_farmer),
        "programme": supply.programme_id,
        "programme_name": supply.programme.name,
        "season": supply.season_id,
        "season_name": supply.season.name,
        "crop": supply.crop_id,
        "crop_name": supply.crop.name,
        "crop_season": supply.crop.category,
        "crop_season_label": supply.crop.get_category_display(),
        "farmer_count": len(farmers),
        "hectares_total": _ha(hectares_total),
        "estimated_cost": _money(estimated_cost),
        "submitted_at": supply.submitted_at.isoformat() if supply.submitted_at else None,
        "reviewed_at": supply.reviewed_at.isoformat() if supply.reviewed_at else None,
        "reviewed_by_name": person_name(supply.reviewed_by),
        "decision_notes": supply.decision_notes,
        "farmers": farmers,
        "categories": categories,
        "limits": limit_rows,
        "totals": [
            {
                **row,
                "hectares": _ha(row["hectares"]),
                "quantity": _qty(row["quantity"]),
                "estimated_cost": _money(row["estimated_cost"]),
                "rate_per_hectare": _qty(row["rate_per_hectare"]),
                "unit_price": _money(row["unit_price"]),
                "requested_hectares": limits_by_variety.get(row["requirement"], {}).get("requested_hectares"),
                "approved_hectares": limits_by_variety.get(row["requirement"], {}).get("approved_hectares"),
            }
            for row in sorted(totals.values(), key=lambda row: (row["input_category"], row["product_name"]))
        ],
        "events": events,
    }


def _variety_payload(requirement):
    return {
        "id": requirement.pk,
        "requirement": requirement.pk,
        "input_category": requirement.input_category,
        "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
        "product_name": _product_name(requirement),
        "unit": catalogue_unit(requirement),
        "rate_per_hectare": _qty(requirement.rate_per_hectare),
        "unit_price": _money(requirement.cost_per_unit),
        "pack_label": requirement.pack_label,
        "pack_size": _qty(requirement.pack_size) if requirement.pack_size else None,
        "pack_price": _money(requirement.pack_price),
    }


def options_for(*, lead, season_id, crop_season=None):
    if lead.role != User.ROLE_LEAD_FARMER:
        raise SupplyError("Only a lead farmer can allocate inputs.")
    if not lead.assigned_cluster_id:
        raise SupplyError("Your account is not assigned to a cluster.")
    season = _load(Season, season_id, "agricultural year")
    return _options(lead, season, crop_season)


def _options(lead, season, crop_season):
    requirements = CropInputRequirement.objects.select_related("programme", "crop", "input_product").filter(
        programme__is_active=True,
        active=True,
        input_product__isnull=False,
        programme__programme_crops__crop_id=F("crop_id"),
        programme__programme_crops__active=True,
    ).filter(Q(programme__season=season) | Q(programme__season__isnull=True)).distinct()
    if crop_season:
        requirements = requirements.filter(crop__category=crop_season)
    programmes = {}
    for requirement in requirements.order_by("programme__name", "crop__name", "input_category", "input_product__name"):
        if requirement.input_category not in (requirement.programme.input_categories or []):
            continue
        if not requirement.rate_per_hectare or requirement.rate_per_hectare <= 0:
            continue
        programme = programmes.setdefault(requirement.programme_id, {
            "programme": requirement.programme_id,
            "programme_name": requirement.programme.name,
            "crops": {},
        })
        crop = programme["crops"].setdefault(requirement.crop_id, {
            "crop": requirement.crop_id,
            "crop_name": requirement.crop.name,
            "crop_season": requirement.crop.category,
            "crop_season_label": requirement.crop.get_category_display(),
            "varieties": [],
        })
        crop["varieties"].append(_variety_payload(requirement))
    farmer_rows = []
    farmers = Farmer.objects.filter(cluster_id=lead.assigned_cluster_id, is_active=True).prefetch_related("farms", "crop_allocations")
    for farmer in farmers.order_by("surname", "first_name"):
        farmer_rows.append({
            "id": farmer.pk,
            "name": farmer.full_name,
            "farms": [{"id": farm.pk, "name": farm.farm_name} for farm in farmer.farms.all() if farm.is_active],
            "crops": [
                {"crop": row.crop_id, "hectares": _ha(row.hectares)}
                for row in farmer.crop_allocations.all() if row.season_id == season.pk
            ],
        })
    open_requests = _supply_queryset().filter(
        lead_farmer=lead, season=season, status__in=InputSupplyRequest.OPEN_STATUSES,
    )
    if crop_season:
        open_requests = open_requests.filter(crop__category=crop_season)
    return {
        "season": season.pk,
        "season_name": season.name,
        "farmers": farmer_rows,
        "programmes": [
            {**programme, "crops": list(programme["crops"].values())}
            for programme in programmes.values()
        ],
        "open_requests": [present(row) for row in open_requests],
    }


def _supply_queryset():
    return InputSupplyRequest.objects.select_related(
        "lead_farmer", "programme", "season", "crop", "reviewed_by",
    ).prefetch_related(
        "farmers__farmer",
        "farmers__farm",
        "farmers__lines__requirement__input_product",
        "limits__requirement__input_product",
        "limits__updated_by",
        "events",
    )


def consolidated(*, season_id, crop_season=None):
    requests = InputSupplyRequest.objects.filter(season_id=season_id)
    if crop_season:
        requests = requests.filter(crop__category=crop_season)
    return {
        "submitted_count": requests.filter(status=InputSupplyRequest.STATUS_SUBMITTED).count(),
        "confirmation_count": requests.filter(status=InputSupplyRequest.STATUS_CONFIRMATION).count(),
        "limits_count": requests.filter(status=InputSupplyRequest.STATUS_LIMITS_SET).count(),
    }
