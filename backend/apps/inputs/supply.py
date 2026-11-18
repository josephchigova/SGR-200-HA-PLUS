"""Lead-farmer input supply: Admin sets a quantity cap per variety, lead farmers allocate it.

A cap is how much of one catalogue variety is available for a programme, agricultural year,
crop and season. It is not stock and it is not given to a farmer by Admin. A lead farmer
splits the available varieties across their own farmers. Quantities are hectares times the
catalogue rate. The lead farmer submits the consolidated request. Approval consumes the cap.
A return, a rejection or a reversal does not.

Nothing the browser sends about quantities or totals is stored as given. The server
recalculates every line from the crop catalogue.
"""

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.farmers.models import Farmer
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.programmes.models import Crop, CropInputRequirement, Programme, Season
from apps.programmes.services import CropPricingService
from apps.recovery.services import RecoveryCalculationService

from . import programme_allocation
from .models import (
    InputAllocation,
    InputAllocationLine,
    InputSupplyAllocation,
    InputSupplyEvent,
    InputSupplyFarmer,
    InputSupplyLine,
    InputSupplyRequest,
    ProgrammeVarietyCap,
)
from .programme_allocation import CATEGORY_LABELS, FOUR, TWO, crop_hectares, covered_categories

REVIEW_ROLES = (User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_PROGRAMME_OFFICER)


class SupplyError(ValueError):
    pass


def _decimal(value, label):
    try:
        return Decimal(str(value))
    except Exception as error:
        raise SupplyError(f"Enter {label} as a number.") from error


def _money(value):
    return str(Decimal(value).quantize(TWO)) if value is not None else None


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
        return CropInputRequirement.objects.select_related("input_product").get(pk=pk)
    except (CropInputRequirement.DoesNotExist, ValueError, TypeError) as error:
        raise SupplyError("Select a valid variety.") from error


def catalogue_unit(requirement):
    unit = (requirement.unit or "").strip()
    if not unit and requirement.input_product_id:
        unit = (requirement.input_product.unit or "").strip()
    return unit


def _reserved(cap, *, exclude_request_id=None):
    """Quantity already approved or submitted against this cap. Drafts and returns are not included."""
    lines = InputSupplyLine.objects.filter(
        cap=cap,
        farmer_entry__request__status__in=[InputSupplyRequest.STATUS_SUBMITTED, InputSupplyRequest.STATUS_APPROVED],
    )
    if exclude_request_id:
        lines = lines.exclude(farmer_entry__request_id=exclude_request_id)
    approved = lines.filter(farmer_entry__request__status=InputSupplyRequest.STATUS_APPROVED).aggregate(total=Sum("quantity"))["total"]
    submitted = lines.filter(farmer_entry__request__status=InputSupplyRequest.STATUS_SUBMITTED).aggregate(total=Sum("quantity"))["total"]
    return Decimal(approved or 0), Decimal(submitted or 0)


def cap_figures(cap, *, exclude_request_id=None, cache=None):
    key = (cap.pk, exclude_request_id)
    if cache is not None and key in cache:
        return cache[key]
    approved, submitted = _reserved(cap, exclude_request_id=exclude_request_id)
    figures = {
        "cap_quantity": Decimal(cap.cap_quantity),
        "approved_quantity": approved,
        "submitted_quantity": submitted,
        "remaining_quantity": Decimal(cap.cap_quantity) - approved - submitted,
    }
    if cache is not None:
        cache[key] = figures
    return figures


def hectares_in_use(farmer, crop, season, exclude_request_id=None):
    """Hectares already spoken for: live allocations, plus drafts, submissions and returns."""
    allocated = InputAllocation.objects.filter(farmer=farmer, season=season).exclude(
        status=InputAllocation.STATUS_CANCELLED,
    ).filter(Q(crop_reference=crop) | Q(crop_reference__isnull=True, crop__iexact=crop.name)).aggregate(total=Sum("hectares"))["total"]
    open_rows = InputSupplyFarmer.objects.filter(
        farmer=farmer,
        request__crop=crop,
        request__season=season,
        request__status__in=InputSupplyRequest.EDITABLE + (InputSupplyRequest.STATUS_SUBMITTED,),
    )
    if exclude_request_id:
        open_rows = open_rows.exclude(request_id=exclude_request_id)
    drafted = open_rows.aggregate(total=Sum("hectares"))["total"]
    return Decimal(allocated or 0) + Decimal(drafted or 0)


def _event(supply, action, user, remarks=""):
    event = InputSupplyEvent.objects.create(
        request=supply,
        action=action,
        actor=user if getattr(user, "is_authenticated", False) else None,
        actor_name=person_name(user),
        remarks=(remarks or "").strip(),
    )
    return event


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


def _notify_submitted(supply, event):
    _notify(
        _reviewers(),
        kind=Notification.KIND_INPUT_SUPPLY_SUBMITTED,
        key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} submitted",
        body=f"{person_name(supply.lead_farmer)} submitted {supply.crop.name} inputs for {supply.programme.name}, {supply.season.name}.",
        url="/input-approvals",
        tone="warning",
    )


def _notify_decided(supply, event, tone):
    _notify(
        [supply.lead_farmer],
        kind=Notification.KIND_INPUT_SUPPLY_DECIDED,
        key=f"input-supply:{supply.pk}:event:{event.pk}",
        title=f"{supply.reference} {supply.get_status_display().lower()}",
        body=supply.decision_notes or f"Admin {supply.get_status_display().lower()} {supply.reference}.",
        url="/my-input-requests",
        tone=tone,
    )


def _context(*, programme_id, season_id, crop_id, crop_season=None):
    programme = _load(Programme, programme_id, "programme")
    season = _load(Season, season_id, "agricultural year")
    crop = _load(Crop, crop_id, "crop")
    if crop_season and crop.category != crop_season:
        raise SupplyError(f"{crop.name} is a {crop.get_category_display().lower()} crop.")
    if season.status != Season.STATUS_ACTIVE:
        raise SupplyError(f"{season.name} is not the active agricultural year, so its caps and requests cannot be changed.")
    if not programme.is_active:
        raise SupplyError(f"{programme.name} is inactive.")
    if programme.season_id and programme.season_id != season.pk:
        raise SupplyError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
    if not programme.supports_crop(crop):
        raise SupplyError(f"{programme.name} does not support {crop.name}.")
    return programme, season, crop


def build_entries(*, lead, programme, season, crop, farmers, exclude_request_id=None):
    """Turn the lead farmer's farmer/variety choices into calculated lines. Raises SupplyError."""
    if lead.role != User.ROLE_LEAD_FARMER:
        raise SupplyError("Only a lead farmer can allocate inputs to farmers.")
    if not lead.assigned_cluster_id:
        raise SupplyError("Your account is not assigned to a cluster, so you have no farmers to allocate to.")
    if not farmers:
        raise SupplyError("Add at least one farmer.")

    seen_farmers = set()
    entries = []
    cap_totals = {}
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
        farm = None
        if item.get("farm"):
            farm = _load(farmer.farms.model, item.get("farm"), "farm")
        else:
            farm = farmer.farms.filter(is_active=True).order_by("id").first()
        if farm is None or farm.farmer_id != farmer.pk:
            raise SupplyError(f"Select a farm belonging to {farmer.full_name}.")

        area = _decimal(item.get("hectares"), "hectares").quantize(TWO)
        if area <= 0:
            raise SupplyError(f"Enter hectares greater than zero for {farmer.full_name}.")
        limit = crop_hectares(farmer, crop, season)
        used = hectares_in_use(farmer, crop, season, exclude_request_id=exclude_request_id)
        if limit is not None and area + used > Decimal(limit):
            raise SupplyError(
                f"{farmer.full_name} has {Decimal(limit).quantize(TWO)} ha of {crop.name} for {season.name}. "
                f"{used.quantize(TWO)} ha is already allocated or in another request, so {area} ha is too much."
            )
        if limit is None and area > Decimal(farm.arable_hectares or 0):
            raise SupplyError(f"Hectares for {farmer.full_name} exceed the farm's arable land.")

        requirement_ids = list(item.get("requirements") or [])
        if not requirement_ids:
            raise SupplyError(f"Choose at least one variety for {farmer.full_name}.")
        if len(requirement_ids) != len(set(requirement_ids)):
            raise SupplyError(f"Each variety can be chosen once for {farmer.full_name}.")

        requirements = []
        for requirement_id in requirement_ids:
            requirement = _requirement(requirement_id)
            if requirement.programme_id != programme.pk or requirement.crop_id != crop.pk:
                raise SupplyError(f"{requirement.item_name} is not in {programme.name}'s {crop.name} catalogue.")
            if not requirement.active or not requirement.input_product_id:
                raise SupplyError(f"{requirement.item_name} is not an active catalogue variety.")
            if requirement.input_category not in (programme.input_categories or []):
                raise SupplyError(f"{programme.name} does not supply {CATEGORY_LABELS.get(requirement.input_category, 'that input').lower()}.")
            if not requirement.rate_per_hectare or requirement.rate_per_hectare <= 0:
                raise SupplyError(f"{requirement.input_product.name} has no quantity per hectare in the catalogue.")
            if not requirement.cost_per_unit or requirement.cost_per_unit <= 0:
                raise SupplyError(f"Set a unit price for {requirement.input_product.name} in the crop catalogue.")
            requirements.append(requirement)

        seeds = [requirement for requirement in requirements if requirement.input_category == "SEED"]
        if len(seeds) > 1:
            names = ", ".join(requirement.input_product.name for requirement in seeds)
            raise SupplyError(f"Choose one seed variety for {farmer.full_name}. Each hectare is planted with one ({names}).")
        covered = covered_categories(farmer=farmer, crop=crop, season=season)
        for requirement in requirements:
            if requirement.input_category in covered:
                label = CATEGORY_LABELS.get(requirement.input_category, requirement.input_category).lower()
                raise SupplyError(
                    f"{farmer.full_name} already has {label} for {crop.name} in {season.name}. Cancel that allocation before requesting it again."
                )

        lines = []
        for requirement in requirements:
            try:
                cap = ProgrammeVarietyCap.objects.select_related("requirement__input_product").get(
                    programme=programme, season=season, crop=crop, requirement=requirement,
                )
            except ProgrammeVarietyCap.DoesNotExist as error:
                raise SupplyError(
                    f"Admin has not made {requirement.input_product.name} available for {programme.name} {crop.name} in {season.name}."
                ) from error
            quantity = (area * Decimal(requirement.rate_per_hectare)).quantize(FOUR)
            if quantity <= 0:
                raise SupplyError(f"{requirement.input_product.name} works out to no quantity for {farmer.full_name}.")
            lines.append({
                "requirement": requirement,
                "cap": cap,
                "rate_per_hectare": Decimal(requirement.rate_per_hectare),
                "quantity": quantity,
                "unit": catalogue_unit(requirement) or cap.unit,
                "unit_price": Decimal(requirement.cost_per_unit),
            })
            cap_totals[cap.pk] = cap_totals.get(cap.pk, Decimal("0")) + quantity
        entries.append({"farmer": farmer, "farm": farm, "hectares": area, "lines": lines})
    return entries, cap_totals


def _entries_from_request(supply):
    farmers = []
    for entry in supply.farmers.prefetch_related("lines"):
        farmers.append({
            "farmer": entry.farmer_id,
            "farm": entry.farm_id,
            "hectares": entry.hectares,
            "requirements": [line.requirement_id for line in entry.lines.all()],
        })
    return build_entries(
        lead=supply.lead_farmer,
        programme=supply.programme,
        season=supply.season,
        crop=supply.crop,
        farmers=farmers,
        exclude_request_id=supply.pk,
    )


def _apply(supply, entries):
    supply.farmers.all().delete()
    for entry in entries:
        row = InputSupplyFarmer.objects.create(
            request=supply, farmer=entry["farmer"], farm=entry["farm"], hectares=entry["hectares"],
        )
        for line in entry["lines"]:
            InputSupplyLine.objects.create(
                farmer_entry=row,
                requirement=line["requirement"],
                cap=line["cap"],
                rate_per_hectare=line["rate_per_hectare"],
                quantity=line["quantity"],
                unit=line["unit"],
                unit_price=line["unit_price"],
            )


def _ensure_caps(supply_id, cap_totals):
    locked = {
        cap.pk: cap
        for cap in ProgrammeVarietyCap.objects.select_for_update().filter(pk__in=list(cap_totals))
    }
    if set(locked) != set(cap_totals):
        raise SupplyError("A variety is no longer available. Refresh and choose again.")
    for cap_id, quantity in cap_totals.items():
        cap = locked[cap_id]
        approved, submitted = _reserved(cap, exclude_request_id=supply_id)
        already = approved + submitted
        if already + quantity > Decimal(cap.cap_quantity):
            requirement = CropInputRequirement.objects.select_related("input_product").get(pk=cap.requirement_id)
            product = requirement.input_product.name if requirement.input_product_id else requirement.item_name
            left = Decimal(cap.cap_quantity) - already
            raise SupplyError(
                f"{product} has {_qty(left)} {cap.unit} left "
                f"(cap {_qty(cap.cap_quantity)}, already approved or submitted {_qty(already)}). "
                f"This request needs {_qty(quantity)} {cap.unit}."
            )


def _lock_open(lead, programme, season, crop):
    """Lock the lead farmer's open request for this programme, year and crop, if there is one."""
    return list(
        InputSupplyRequest.objects.select_for_update().filter(
            lead_farmer=lead, programme=programme, season=season, crop=crop,
            status__in=[InputSupplyRequest.STATUS_DRAFT, InputSupplyRequest.STATUS_SUBMITTED, InputSupplyRequest.STATUS_RETURNED],
        ).order_by("id")
    )


@transaction.atomic
def save_draft(*, lead, programme_id, season_id, crop_id, farmers, crop_season=None):
    programme, season, crop = _context(programme_id=programme_id, season_id=season_id, crop_id=crop_id, crop_season=crop_season)
    open_rows = _lock_open(lead, programme, season, crop)
    submitted = [row for row in open_rows if row.status == InputSupplyRequest.STATUS_SUBMITTED]
    if submitted:
        raise SupplyError(f"{submitted[0].reference} is waiting for Admin. Wait for a decision before changing it.")
    editable = [row for row in open_rows if row.status in InputSupplyRequest.EDITABLE]
    existing = editable[-1] if editable else None
    entries, cap_totals = build_entries(
        lead=lead, programme=programme, season=season, crop=crop, farmers=farmers,
        exclude_request_id=existing.pk if existing else None,
    )
    created = existing is None
    if created:
        try:
            supply = InputSupplyRequest.objects.create(
                reference=f"TMP{uuid.uuid4().hex}",
                lead_farmer=lead,
                programme=programme,
                season=season,
                crop=crop,
                status=InputSupplyRequest.STATUS_DRAFT,
            )
        except IntegrityError as error:
            raise SupplyError("You already have an open request for this programme, year and crop. Refresh and continue that one.") from error
        supply.reference = f"LF{supply.pk:05d}"
        supply.save(update_fields=["reference"])
    else:
        supply = existing
    _apply(supply, entries)
    _ensure_caps(supply.pk, cap_totals)
    if created:
        _event(supply, InputSupplyEvent.SAVED, lead, "Draft saved.")
    elif supply.status == InputSupplyRequest.STATUS_RETURNED:
        _event(supply, InputSupplyEvent.CORRECTED, lead, "Allocations updated after Admin asked for corrections.")
    return supply, created


@transaction.atomic
def submit(*, request_id, user):
    supply = InputSupplyRequest.objects.select_for_update().select_related("lead_farmer", "programme", "season", "crop").get(pk=request_id)
    if supply.lead_farmer_id != user.pk:
        raise SupplyError("You can only submit your own request.")
    if supply.status not in InputSupplyRequest.EDITABLE:
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()} and cannot be submitted.")
    entries, cap_totals = _entries_from_request(supply)
    if not entries:
        raise SupplyError("Add at least one farmer before submitting.")
    _apply(supply, entries)
    _ensure_caps(supply.pk, cap_totals)
    was_returned = supply.status == InputSupplyRequest.STATUS_RETURNED
    supply.status = InputSupplyRequest.STATUS_SUBMITTED
    supply.submitted_at = timezone.now()
    supply.decision_notes = ""
    supply.reviewed_at = None
    supply.reviewed_by = None
    supply.save(update_fields=["status", "submitted_at", "decision_notes", "reviewed_at", "reviewed_by", "updated_at"])
    event = _event(supply, InputSupplyEvent.RESUBMITTED if was_returned else InputSupplyEvent.SUBMITTED, user)
    _notify_submitted(supply, event)
    return supply


def _decision_user(user):
    if not user or not user.is_authenticated:
        raise SupplyError("Sign in again.")
    if user.is_superuser or user.role in REVIEW_ROLES:
        return user
    raise SupplyError("Only an administrator can review input requests.")


@transaction.atomic
def approve(*, request_id, user, remarks=""):
    user = _decision_user(user)
    supply = InputSupplyRequest.objects.select_for_update().select_related(
        "lead_farmer", "programme", "season", "crop",
    ).get(pk=request_id)
    if supply.status != InputSupplyRequest.STATUS_SUBMITTED:
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()}. Only a submitted request can be approved.")
    entries, cap_totals = _entries_from_request(supply)
    _apply(supply, entries)
    _ensure_caps(supply.pk, cap_totals)
    try:
        selling_price = CropPricingService.resolve_price_per_tonne(crop=supply.crop, season=supply.season)
    except ValueError as error:
        raise SupplyError(str(error)) from error

    for entry in supply.farmers.select_related("farmer", "farm").prefetch_related("lines__requirement__input_product"):
        lines = list(entry.lines.all())
        total_cost = sum((line.quantity * line.unit_price for line in lines), Decimal("0")).quantize(TWO)
        rate_total = sum((line.rate_per_hectare * line.unit_price for line in lines), Decimal("0"))
        allocation = InputAllocation.objects.create(
            farmer=entry.farmer,
            farm=entry.farm,
            programme=supply.programme,
            season=supply.season,
            crop_reference=supply.crop,
            crop=supply.crop.name,
            hectares=entry.hectares,
            total_input_cost=total_cost,
            calculated_input_cost_per_hectare=rate_total.quantize(TWO),
            allocation_reference=supply.reference,
            status=InputAllocation.STATUS_ALLOCATED,
            sourced_by_category=True,
            created_by=user,
        )
        for line in lines:
            product = line.requirement.input_product
            InputAllocationLine.objects.create(
                allocation=allocation,
                source_requirement=line.requirement,
                input_category=line.requirement.input_category,
                programme=supply.programme,
                input_product=product,
                group_name=CATEGORY_LABELS.get(line.requirement.input_category, line.requirement.input_category),
                item_name=product.name,
                unit=line.unit,
                rate_per_hectare=line.rate_per_hectare,
                cost_per_unit=line.unit_price,
                pack_label=line.requirement.pack_label,
                pack_size=line.requirement.pack_size,
                pack_price=line.requirement.pack_price,
                cost_per_hectare=(line.rate_per_hectare * line.unit_price).quantize(FOUR),
                required_quantity=line.quantity,
                calculated_cost=(line.quantity * line.unit_price).quantize(TWO),
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
    supply = InputSupplyRequest.objects.select_for_update().select_related("lead_farmer", "programme", "season", "crop").get(pk=request_id)
    if supply.status != InputSupplyRequest.STATUS_SUBMITTED:
        raise SupplyError(f"{supply.reference} is {supply.get_status_display().lower()}. Only a submitted request can be reviewed.")
    supply.status = status
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = remarks
    supply.save(update_fields=["status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, action, user, remarks)
    _notify_decided(supply, event, tone)
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
    """Undo an approval. The allocations and their debt are cancelled, and the cap is released."""
    user = _decision_user(user)
    remarks = (remarks or "").strip()
    if not remarks:
        raise SupplyError("Give the reason for reversing this approval.")
    supply = InputSupplyRequest.objects.select_for_update().select_related("lead_farmer", "programme", "season", "crop").get(pk=request_id)
    if supply.status != InputSupplyRequest.STATUS_APPROVED:
        raise SupplyError("Only an approved request can be reversed. Edit it by sending it back, then let the lead farmer resubmit.")
    links = list(supply.allocations.select_related("allocation"))
    if not links:
        raise SupplyError(f"{supply.reference} has no allocations to reverse.")
    for link in links:
        try:
            programme_allocation.cancel(allocation=link.allocation, reason=remarks, user=user)
        except programme_allocation.AllocationError as error:
            raise SupplyError(str(error)) from error
    supply.status = InputSupplyRequest.STATUS_RETURNED
    supply.reviewed_at = timezone.now()
    supply.reviewed_by = user
    supply.decision_notes = remarks
    supply.save(update_fields=["status", "reviewed_at", "reviewed_by", "decision_notes", "updated_at"])
    event = _event(supply, InputSupplyEvent.REVERSED, user, remarks)
    _notify_decided(supply, event, "warning")
    return supply


@transaction.atomic
def save_cap(*, actor, programme_id, season_id, crop_id, requirement_id, cap_quantity, notes="", instance=None):
    programme, season, crop = _context(programme_id=programme_id, season_id=season_id, crop_id=crop_id)
    requirement = _requirement(requirement_id)
    if requirement.programme_id != programme.pk or requirement.crop_id != crop.pk:
        raise SupplyError(f"{requirement.item_name} is not in {programme.name}'s {crop.name} catalogue.")
    if not requirement.active or not requirement.input_product_id or not requirement.input_category:
        raise SupplyError("Choose an active catalogue variety.")
    if requirement.input_category not in (programme.input_categories or []):
        raise SupplyError(f"{programme.name} does not supply {CATEGORY_LABELS.get(requirement.input_category, 'that input').lower()}.")
    unit = catalogue_unit(requirement)
    if not unit:
        raise SupplyError(f"Give {requirement.input_product.name} a unit of measurement in the crop catalogue first.")
    quantity = _decimal(cap_quantity, "the available cap").quantize(FOUR)
    if quantity <= 0:
        raise SupplyError("The available cap must be greater than zero.")

    if instance is None:
        if ProgrammeVarietyCap.objects.filter(programme=programme, season=season, crop=crop, requirement=requirement).exists():
            raise SupplyError(f"{requirement.input_product.name} already has a cap for {programme.name} {crop.name} in {season.name}. Edit that cap.")
        cap = ProgrammeVarietyCap(
            programme=programme, season=season, crop=crop, requirement=requirement, created_by=actor,
        )
    else:
        cap = ProgrammeVarietyCap.objects.select_for_update().get(pk=instance.pk)
        if cap.requirement_id != requirement.pk or cap.programme_id != programme.pk or cap.season_id != season.pk or cap.crop_id != crop.pk:
            raise SupplyError("A cap stays on the variety it was created for. Edit the quantity, or add a new variety.")
    approved, submitted = _reserved(cap) if cap.pk else (Decimal("0"), Decimal("0"))
    if quantity < approved + submitted:
        raise SupplyError(
            f"Approved and submitted requests already use {_qty(approved + submitted)} {unit}. "
            f"The cap cannot be lower than that."
        )
    cap.cap_quantity = quantity
    cap.unit = unit
    cap.notes = notes or ""
    cap.save()
    return cap


def present_cap(cap, *, cache=None):
    figures = cap_figures(cap, cache=cache)
    requirement = cap.requirement
    product = requirement.input_product.name if requirement.input_product_id else requirement.item_name
    return {
        "id": cap.pk,
        "programme": cap.programme_id,
        "programme_name": cap.programme.name,
        "season": cap.season_id,
        "season_name": cap.season.name,
        "crop": cap.crop_id,
        "crop_name": cap.crop.name,
        "crop_season": cap.crop.category,
        "crop_season_label": cap.crop.get_category_display(),
        "requirement": requirement.pk,
        "input_category": requirement.input_category,
        "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
        "product_name": product,
        "unit": cap.unit,
        "rate_per_hectare": _qty(requirement.rate_per_hectare),
        "cap_quantity": _qty(figures["cap_quantity"]),
        "approved_quantity": _qty(figures["approved_quantity"]),
        "submitted_quantity": _qty(figures["submitted_quantity"]),
        "remaining_quantity": _qty(figures["remaining_quantity"]),
        "notes": cap.notes,
    }


def present(supply, *, cache=None):
    cache = cache if cache is not None else {}
    totals = {}
    farmers = []
    hectares_total = Decimal("0.00")
    for entry in supply.farmers.all():
        hectares_total += Decimal(entry.hectares)
        lines = []
        for line in entry.lines.all():
            requirement = line.requirement
            product = requirement.input_product.name if requirement.input_product_id else requirement.item_name
            figures = cap_figures(line.cap, cache=cache)
            lines.append({
                "id": line.pk,
                "requirement": requirement.pk,
                "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": product,
                "unit": line.unit,
                "rate_per_hectare": _qty(line.rate_per_hectare),
                "quantity": _qty(line.quantity),
                "unit_price": _money(line.unit_price),
                "cap_quantity": _qty(figures["cap_quantity"]),
                "approved_quantity": _qty(figures["approved_quantity"]),
                "submitted_quantity": _qty(figures["submitted_quantity"]),
                "remaining_quantity": _qty(figures["remaining_quantity"]),
            })
            bucket = totals.setdefault(requirement.pk, {
                "requirement": requirement.pk,
                "input_category": requirement.input_category,
                "input_category_label": CATEGORY_LABELS.get(requirement.input_category, requirement.input_category),
                "product_name": product,
                "unit": line.unit,
                "quantity": Decimal("0"),
                "cap_quantity": figures["cap_quantity"],
                "approved_quantity": figures["approved_quantity"],
                "submitted_quantity": figures["submitted_quantity"],
                "remaining_quantity": figures["remaining_quantity"],
            })
            bucket["quantity"] += Decimal(line.quantity)
        farmers.append({
            "id": entry.pk,
            "farmer": entry.farmer_id,
            "farmer_name": entry.farmer.full_name,
            "farm": entry.farm_id,
            "farm_name": entry.farm.farm_name,
            "hectares": str(entry.hectares),
            "lines": lines,
        })
    events = [
        {
            "id": event.pk,
            "action": event.action,
            "action_label": event.get_action_display(),
            "actor_name": event.actor_name,
            "remarks": event.remarks,
            "created_at": event.created_at.isoformat(),
        }
        for event in supply.events.all()
    ]
    return {
        "id": supply.pk,
        "reference": supply.reference,
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
        "hectares_total": str(hectares_total.quantize(TWO)),
        "submitted_at": supply.submitted_at.isoformat() if supply.submitted_at else None,
        "reviewed_at": supply.reviewed_at.isoformat() if supply.reviewed_at else None,
        "reviewed_by_name": person_name(supply.reviewed_by),
        "decision_notes": supply.decision_notes,
        "farmers": farmers,
        "totals": [
            {**row, "quantity": _qty(row["quantity"]), "cap_quantity": _qty(row["cap_quantity"]),
             "approved_quantity": _qty(row["approved_quantity"]), "submitted_quantity": _qty(row["submitted_quantity"]),
             "remaining_quantity": _qty(row["remaining_quantity"])}
            for row in sorted(totals.values(), key=lambda row: (row["input_category"], row["product_name"]))
        ],
        "events": events,
    }


def options_for(*, lead, season_id, crop_season=None):
    if lead.role != User.ROLE_LEAD_FARMER:
        raise SupplyError("Only a lead farmer can allocate inputs.")
    if not lead.assigned_cluster_id:
        raise SupplyError("Your account is not assigned to a cluster.")
    season = _load(Season, season_id, "agricultural year")
    caps = ProgrammeVarietyCap.objects.select_related(
        "programme", "season", "crop", "requirement__input_product",
    ).filter(season=season, programme__is_active=True)
    if crop_season:
        caps = caps.filter(crop__category=crop_season)
    cache = {}
    programmes = {}
    for cap in caps:
        programme = programmes.setdefault(cap.programme_id, {
            "programme": cap.programme_id, "programme_name": cap.programme.name, "crops": {},
        })
        crop = programme["crops"].setdefault(cap.crop_id, {
            "crop": cap.crop_id, "crop_name": cap.crop.name, "crop_season": cap.crop.category,
            "crop_season_label": cap.crop.get_category_display(), "varieties": [],
        })
        crop["varieties"].append(present_cap(cap, cache=cache))
    farmer_rows = []
    farmers = Farmer.objects.filter(cluster_id=lead.assigned_cluster_id, is_active=True).prefetch_related("farms", "crop_allocations")
    for farmer in farmers.order_by("surname", "first_name"):
        farmer_rows.append({
            "id": farmer.pk,
            "name": farmer.full_name,
            "farms": [{"id": farm.pk, "name": farm.farm_name} for farm in farmer.farms.all() if farm.is_active],
            "crops": [
                {"crop": row.crop_id, "hectares": str(row.hectares)}
                for row in farmer.crop_allocations.all() if row.season_id == season.pk
            ],
        })
    open_requests = InputSupplyRequest.objects.select_related(
        "lead_farmer", "programme", "season", "crop", "reviewed_by",
    ).prefetch_related(
        "farmers__farmer", "farmers__farm", "farmers__lines__requirement__input_product", "farmers__lines__cap", "events",
    ).filter(lead_farmer=lead, season=season, status__in=InputSupplyRequest.EDITABLE)
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
        "open_requests": [present(row, cache=cache) for row in open_requests],
    }


def consolidated(*, season_id, crop_season=None):
    caps = ProgrammeVarietyCap.objects.select_related(
        "programme", "season", "crop", "requirement__input_product",
    ).filter(season_id=season_id)
    if crop_season:
        caps = caps.filter(crop__category=crop_season)
    cache = {}
    rows = [present_cap(cap, cache=cache) for cap in caps]
    submitted = InputSupplyRequest.objects.filter(season_id=season_id, status=InputSupplyRequest.STATUS_SUBMITTED)
    if crop_season:
        submitted = submitted.filter(crop__category=crop_season)
    return {"caps": rows, "submitted_count": submitted.count()}
