"""Asset register calculations and history.

Acquisition cost, maintenance and disposal stay on the asset register.
These operations do not create journals or operating expenses.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .ledger import money, text_amount
from .models import (
    Asset,
    AssetAuditEvent,
    AssetDisposal,
    AssetDocument,
    AssetMaintenance,
    AssetTransfer,
    AssetValuation,
)

RATE_PLACES = Decimal("0.0001")
OPEN_STATUSES = {Asset.STATUS_ACTIVE, Asset.STATUS_MAINTENANCE}
CLOSED_STATUSES = {Asset.STATUS_DISPOSED, Asset.STATUS_WRITTEN_OFF}
TRACKED_FIELDS = (
    "name",
    "description",
    "category",
    "supplier",
    "cost",
    "current_value",
    "location",
    "department",
    "responsible_person",
    "condition",
    "status",
    "warranty_expiry",
    "notes",
    "residual_value",
    "useful_life_years",
    "depreciation_method",
    "depreciation_rate",
    "accumulated_depreciation",
    "purchase_date",
)


def reject(detail):
    raise ValidationError(detail)


def rate_amount(value):
    return Decimal(str(value or 0)).quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def apply_carrying_amounts(asset):
    cost = money(asset.cost)
    residual = money(asset.residual_value)
    accumulated = money(asset.accumulated_depreciation)
    current = money(asset.current_value)
    if cost < 0 or residual < 0 or accumulated < 0 or current < 0:
        reject("Financial amounts cannot be negative.")
    if residual > cost:
        reject("Residual value cannot exceed the acquisition cost.")
    if accumulated > cost:
        reject("Accumulated depreciation cannot exceed the acquisition cost.")
    asset.cost = cost
    asset.residual_value = residual
    asset.accumulated_depreciation = accumulated
    asset.current_value = current
    method = asset.depreciation_method or Asset.METHOD_NONE
    life = asset.useful_life_years
    if method == Asset.METHOD_STRAIGHT_LINE:
        if life is None or life <= 0:
            reject("Enter a useful life in years for straight-line depreciation.")
        annual = money((cost - residual) / life)
        asset.annual_depreciation = annual
        asset.depreciation_rate = rate_amount(Decimal(100) / life)
    elif method == Asset.METHOD_REDUCING:
        rate = rate_amount(asset.depreciation_rate)
        if rate <= 0 or rate > Decimal(100):
            reject("Enter a reducing-balance rate between 0 and 100 percent.")
        asset.depreciation_rate = rate
        asset.annual_depreciation = money((cost - accumulated) * rate / Decimal(100))
    else:
        asset.depreciation_method = Asset.METHOD_NONE
        asset.annual_depreciation = money(0)
        asset.depreciation_rate = rate_amount(0)
    asset.closing_nbv = money(cost - accumulated)


def allocate_asset_code():
    highest = 0
    codes = Asset.objects.select_for_update().filter(asset_id__startswith="AST-").values_list("asset_id", flat=True)
    for code in codes:
        suffix = code[4:]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"AST-{highest + 1:04d}"


def audit(asset, action, user, detail):
    AssetAuditEvent.objects.create(asset=asset, action=action, actor=user if getattr(user, "is_authenticated", False) else None, detail=detail)


def _sync_category_name(asset):
    if asset.category_ref_id:
        asset.category = asset.category_ref.name


def _snapshot(asset):
    return {field: getattr(asset, field) for field in TRACKED_FIELDS}


def _changes(before, asset):
    lines = []
    for field, previous in before.items():
        current = getattr(asset, field)
        if previous != current:
            lines.append(f"{field}: {previous} -> {current}")
    return lines


def register_asset(user, category, **fields):
    supplied_value = fields.pop("current_value", None)
    requested_code = (fields.pop("asset_id", None) or "").strip()
    for _attempt in range(3):
        try:
            with transaction.atomic():
                asset = Asset(category_ref=category, created_by=user, updated_by=user, asset_id=requested_code, **fields)
                if not asset.asset_id:
                    asset.asset_id = allocate_asset_code()
                asset.name = (asset.name or "").strip()
                asset.description = (asset.description or "").strip()
                if not asset.name:
                    asset.name = asset.description
                if not asset.description:
                    asset.description = asset.name
                if not asset.name:
                    reject("Enter an asset name.")
                if asset.condition not in dict(Asset.CONDITION_CHOICES):
                    reject("Select an asset condition.")
                if asset.status in CLOSED_STATUSES:
                    reject("Record a disposal or write-off from the asset record. Do not set that status on registration.")
                asset.current_value = asset.cost if supplied_value in (None, "") else supplied_value
                _sync_category_name(asset)
                apply_carrying_amounts(asset)
                asset.save()
                valued_on = asset.purchase_date or timezone.localdate()
                AssetValuation.objects.create(
                    asset=asset,
                    valued_on=valued_on,
                    amount=asset.cost,
                    kind=AssetValuation.KIND_ACQUISITION,
                    note="Acquisition cost stored on the asset register. No expense or journal was posted.",
                    recorded_by=user,
                )
                if asset.current_value != asset.cost:
                    AssetValuation.objects.create(
                        asset=asset,
                        valued_on=valued_on,
                        amount=asset.current_value,
                        kind=AssetValuation.KIND_REVALUATION,
                        note="Opening estimated value.",
                        recorded_by=user,
                    )
                audit(asset, "REGISTERED", user, f"Registered {asset.asset_id} {asset.display_name}. Acquisition cost {text_amount(asset.cost)} was not posted to expenses.")
                return asset
        except IntegrityError:
            if requested_code:
                reject("That asset code is already in use.")
            continue
    reject("A unique asset code could not be assigned. Try again.")


@transaction.atomic
def update_asset(asset, user, category, **fields):
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    if hasattr(asset, "disposal"):
        reject("This asset has been disposed or written off and can no longer be edited.")
    before = _snapshot(asset)
    previous_value = asset.current_value
    for name, value in fields.items():
        setattr(asset, name, value)
    asset.category_ref = category
    asset.name = (asset.name or "").strip() or asset.description
    asset.description = (asset.description or "").strip() or asset.name
    if asset.status in CLOSED_STATUSES:
        reject("Use the disposal action to dispose of or write off an asset.")
    asset.updated_by = user
    _sync_category_name(asset)
    apply_carrying_amounts(asset)
    asset.save()
    changes = _changes(before, asset)
    if asset.current_value != previous_value:
        AssetValuation.objects.create(
            asset=asset,
            valued_on=timezone.localdate(),
            amount=asset.current_value,
            kind=AssetValuation.KIND_REVALUATION,
            note="Estimated value updated on the asset register. No journal was posted.",
            recorded_by=user,
        )
    if changes:
        audit(asset, "UPDATED", user, "\n".join(changes))
    return asset


@transaction.atomic
def record_valuation(asset, user, valued_on, amount, note=""):
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    if hasattr(asset, "disposal"):
        reject("A disposed asset cannot be revalued.")
    amount = money(amount)
    if amount < 0:
        reject("The estimated value cannot be negative.")
    previous = asset.current_value
    asset.current_value = amount
    asset.updated_by = user
    asset.save(update_fields=["current_value", "updated_by", "updated_at"])
    AssetValuation.objects.create(
        asset=asset,
        valued_on=valued_on,
        amount=amount,
        kind=AssetValuation.KIND_REVALUATION,
        note=note or "Estimated value recorded. No journal was posted.",
        recorded_by=user,
    )
    audit(asset, "VALUATION", user, f"Estimated value {text_amount(previous)} -> {text_amount(amount)} on {valued_on.isoformat()}.")
    return asset


@transaction.atomic
def record_maintenance(asset, user, activity_date, description, cost, supplier="", notes=""):
    cost = money(cost)
    if cost < 0:
        reject("Maintenance cost cannot be negative.")
    if not description.strip():
        reject("Describe the maintenance activity.")
    record = AssetMaintenance.objects.create(
        asset=asset,
        activity_date=activity_date,
        description=description.strip(),
        cost=cost,
        supplier=supplier.strip(),
        notes=notes.strip(),
        recorded_by=user,
    )
    audit(asset, "MAINTENANCE", user, f"{activity_date.isoformat()} {record.description} cost {text_amount(cost)}. Not posted to operating expenses.")
    return record


@transaction.atomic
def transfer_asset(asset, user, transfer_date, to_location, to_department, to_person, notes=""):
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    if asset.status in CLOSED_STATUSES:
        reject("A disposed or written-off asset cannot be transferred.")
    to_location = (to_location or "").strip()
    to_department = (to_department or "").strip()
    to_person = (to_person or "").strip()
    if not any([to_location, to_department, to_person]):
        reject("Enter the location, department or person receiving the asset.")
    record = AssetTransfer.objects.create(
        asset=asset,
        transfer_date=transfer_date,
        from_location=asset.location,
        to_location=to_location or asset.location,
        from_department=asset.department,
        to_department=to_department or asset.department,
        from_person=asset.responsible_person,
        to_person=to_person or asset.responsible_person,
        notes=notes.strip(),
        recorded_by=user,
    )
    asset.location = record.to_location
    asset.department = record.to_department
    asset.responsible_person = record.to_person
    asset.updated_by = user
    asset.save(update_fields=["location", "department", "responsible_person", "updated_by", "updated_at"])
    audit(
        asset,
        "TRANSFER",
        user,
        f"{transfer_date.isoformat()} from {record.from_location or 'unassigned'} / {record.from_department or 'unassigned'} / {record.from_person or 'unassigned'} "
        f"to {record.to_location or 'unassigned'} / {record.to_department or 'unassigned'} / {record.to_person or 'unassigned'}.",
    )
    return record


@transaction.atomic
def dispose_asset(asset, user, kind, disposed_on, reason, proceeds):
    asset = Asset.objects.select_for_update().get(pk=asset.pk)
    if AssetDisposal.objects.filter(asset=asset).exists():
        reject("This asset already has a disposal or write-off record.")
    if kind not in {AssetDisposal.KIND_DISPOSED, AssetDisposal.KIND_WRITTEN_OFF}:
        reject("Choose disposal or write-off.")
    if not (reason or "").strip():
        reject("Enter the reason for disposal or write-off.")
    proceeds = money(proceeds or 0)
    if proceeds < 0:
        reject("Disposal proceeds cannot be negative.")
    if asset.purchase_date and disposed_on < asset.purchase_date:
        reject("The disposal date cannot be earlier than the acquisition date.")
    record = AssetDisposal.objects.create(
        asset=asset,
        kind=kind,
        disposed_on=disposed_on,
        reason=reason.strip(),
        proceeds=proceeds,
        recorded_by=user,
    )
    asset.status = kind
    asset.updated_by = user
    asset.save(update_fields=["status", "updated_by", "updated_at"])
    audit(
        asset,
        "DISPOSAL",
        user,
        f"{kind} on {disposed_on.isoformat()}. Proceeds {text_amount(proceeds)}. Reason: {record.reason}. No ledger posting was created.",
    )
    return record


def add_document(asset, user, upload, title=""):
    if upload.size > 10 * 1024 * 1024:
        reject("Attachments must be 10 MB or smaller.")
    document = AssetDocument.objects.create(
        asset=asset,
        title=(title or getattr(upload, "name", "") or "Supporting document")[:180],
        file=upload,
        uploaded_by=user,
    )
    audit(asset, "DOCUMENT", user, f"Attached {document.title}.")
    return document


def _category_label(asset_category, category_name):
    return category_name or asset_category or "Uncategorised"


def asset_summary():
    totals = Asset.objects.aggregate(
        total_assets=Count("id"),
        total_acquisition_value=Sum("cost"),
        under_maintenance=Count("id", filter=Q(status=Asset.STATUS_MAINTENANCE)),
        disposed_or_written_off=Count("id", filter=Q(status__in=CLOSED_STATUSES)),
    )
    open_assets = Asset.objects.filter(status__in=OPEN_STATUSES)
    open_totals = open_assets.aggregate(current=Sum("current_value"), nbv=Sum("closing_nbv"))
    grouped = {}
    for asset in Asset.objects.select_related("category_ref"):
        label = _category_label(asset.category, asset.category_ref.name if asset.category_ref_id else "")
        bucket = grouped.setdefault(label, {"category": label, "count": 0, "acquisition_value": Decimal("0"), "current_value": Decimal("0")})
        bucket["count"] += 1
        bucket["acquisition_value"] += money(asset.cost)
        if asset.status in OPEN_STATUSES:
            bucket["current_value"] += money(asset.current_value)
    categories = [
        {
            "category": row["category"],
            "count": row["count"],
            "acquisition_value": text_amount(row["acquisition_value"]),
            "current_value": text_amount(row["current_value"]),
        }
        for row in sorted(grouped.values(), key=lambda item: (-item["count"], item["category"]))
    ]
    return {
        "total_assets": totals["total_assets"] or 0,
        "total_acquisition_value": text_amount(totals["total_acquisition_value"] or 0),
        "total_current_value": text_amount(open_totals["current"] or 0),
        "total_net_book_value": text_amount(open_totals["nbv"] or 0),
        "under_maintenance": totals["under_maintenance"] or 0,
        "disposed_or_written_off": totals["disposed_or_written_off"] or 0,
        "by_category": categories,
        "note": "Acquisition cost, current value and net book value are asset-register figures. They are not operating expenses and are not posted to the ledger by this summary.",
    }
