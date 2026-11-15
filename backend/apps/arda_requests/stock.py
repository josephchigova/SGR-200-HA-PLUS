"""Request batch stock: what each batch holds, and every change to it.

Every change to a batch input's balance goes through move(), which locks the row,
checks the balance and writes a BatchStockMovement. Nothing else edits
allocated_quantity, so the ledger and the balance always agree.
"""

from decimal import Decimal

from django.db import transaction

from .models import ARDARequestBatch, BatchStockMovement, RequestBatchInput

FOUR = Decimal("0.0001")
# Batches that hold stock which can be allocated. A draft or rejected request has nothing to give out.
ALLOCATABLE_BATCH_STATUSES = (ARDARequestBatch.STATUS_SUBMITTED, ARDARequestBatch.STATUS_APPROVED)


class StockError(ValueError):
    pass


def _quantity(value):
    return Decimal(str(value or 0)).quantize(FOUR)


def lock(batch_input_ids):
    """Lock batch inputs in id order, so two allocations never wait on each other in a cycle."""
    rows = RequestBatchInput.objects.select_for_update().select_related("batch", "input_product").filter(pk__in=sorted(set(batch_input_ids)))
    return {row.pk: row for row in rows.order_by("pk")}


@transaction.atomic
def open_line(*, batch, input_product, input_category, requested_quantity, unit="", notes="", user=None):
    """Add an input product to a batch with the quantity requested for it."""
    requested = _quantity(requested_quantity)
    if requested <= 0:
        raise StockError("Enter a requested quantity greater than zero.")
    if RequestBatchInput.objects.filter(batch=batch, input_product=input_product).exists():
        raise StockError(f"{input_product.name} is already in batch {batch.request_number}. Change its quantity instead.")
    line = RequestBatchInput.objects.create(
        batch=batch, input_product=input_product, input_category=input_category,
        unit=unit or input_product.unit, requested_quantity=requested, notes=notes,
    )
    BatchStockMovement.objects.create(
        batch_input=line, kind=BatchStockMovement.KIND_OPENING, quantity=requested,
        available_after=requested, reason=notes, created_by=user,
    )
    return line


@transaction.atomic
def change_requested(*, batch_input_id, requested_quantity, reason="", user=None):
    """Change the quantity a batch holds. It can never drop below what is already allocated."""
    line = lock([batch_input_id])[batch_input_id]
    requested = _quantity(requested_quantity)
    if requested < line.allocated_quantity:
        raise StockError(
            f"{line.input_product.name}: {line.allocated_quantity.normalize():f} {line.unit} is already allocated, "
            "so the requested quantity cannot be lower than that."
        )
    delta = requested - line.requested_quantity
    if delta == 0:
        return line
    line.requested_quantity = requested
    line.save(update_fields=["requested_quantity", "updated_at"])
    BatchStockMovement.objects.create(
        batch_input=line, kind=BatchStockMovement.KIND_ADJUSTMENT, quantity=delta,
        available_after=line.available_quantity, reason=reason or "Requested quantity changed", created_by=user,
    )
    return line


def allocate(line, quantity, *, allocation, allocation_line, user=None):
    """Take stock out of a locked batch input for one allocation line."""
    amount = _quantity(quantity)
    if amount <= 0:
        return None
    if line.batch.status not in ALLOCATABLE_BATCH_STATUSES:
        raise StockError(f"Batch {line.batch.request_number} is {line.batch.get_status_display().lower()}, so its inputs cannot be allocated.")
    if amount > line.available_quantity:
        raise StockError(
            f"Not enough {line.input_product.name} in batch {line.batch.request_number}: "
            f"{amount.normalize():f} {line.unit} needed, {line.available_quantity.normalize():f} {line.unit} available."
        )
    line.allocated_quantity += amount
    line.save(update_fields=["allocated_quantity", "updated_at"])
    return BatchStockMovement.objects.create(
        batch_input=line, kind=BatchStockMovement.KIND_ALLOCATION, quantity=-amount,
        available_after=line.available_quantity, allocation=allocation, allocation_line=allocation_line, created_by=user,
    )


def reverse(line, quantity, *, allocation, allocation_line, reason, user=None):
    """Return stock to a locked batch input when an allocation is cancelled."""
    amount = _quantity(quantity)
    if amount <= 0:
        return None
    line.allocated_quantity = max(line.allocated_quantity - amount, Decimal("0"))
    line.save(update_fields=["allocated_quantity", "updated_at"])
    return BatchStockMovement.objects.create(
        batch_input=line, kind=BatchStockMovement.KIND_REVERSAL, quantity=amount,
        available_after=line.available_quantity, allocation=allocation, allocation_line=allocation_line,
        reason=reason, created_by=user,
    )
