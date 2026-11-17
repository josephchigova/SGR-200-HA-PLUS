"""Hectare figures for a programme and each crop it supports.

Programmes, input requests, allocations and reports all read these numbers from here and from
apps.arda_requests.services.batch_figures, so the same figure is never worked out two ways.
"""

from decimal import Decimal

from django.db.models import Sum

ZERO = Decimal("0.00")


def _allocations(programme, crop=None):
    from apps.inputs.models import InputAllocation

    allocations = InputAllocation.objects.filter(programme=programme).exclude(status=InputAllocation.STATUS_CANCELLED)
    if crop is not None:
        allocations = allocations.filter(crop_reference=crop) | allocations.filter(crop_reference__isnull=True, crop__iexact=crop.name)
    return allocations


def programme_figures(programme):
    from apps.arda_requests.models import ARDARequestBatch
    from apps.arda_requests.services import batch_figures

    from .models import CropInputRequirement

    batches = list(programme.request_batches.exclude(status=ARDARequestBatch.STATUS_REJECTED))
    per_batch = {batch.pk: batch_figures(batch) for batch in batches}
    rows = []
    for crop in programme.supported_crops().order_by("name"):
        crop_batches = [batch for batch in batches if (batch.crop or "").strip().lower() == crop.name.lower()]
        allocations = _allocations(programme, crop)
        approved = sum((per_batch[batch.pk]["approved_hectares"] for batch in crop_batches), ZERO)
        allocated = allocations.aggregate(total=Sum("hectares"))["total"] or ZERO
        rows.append({
            "crop": crop.pk,
            "crop_name": crop.name,
            "season": crop.get_category_display(),
            "requested_hectares": str(sum((per_batch[batch.pk]["requested_hectares"] for batch in crop_batches), ZERO)),
            "approved_hectares": str(approved),
            "allocated_hectares": str(allocated),
            "remaining_hectares": str(max(approved - allocated, ZERO)),
            "farmers": allocations.values("farmer_id").distinct().count(),
            "inputs_configured": CropInputRequirement.objects.filter(programme=programme, crop=crop, active=True).count(),
        })
    allocations = _allocations(programme)
    approved = sum((figures["approved_hectares"] for figures in per_batch.values()), ZERO)
    allocated = allocations.aggregate(total=Sum("hectares"))["total"] or ZERO
    return {
        "totals": {
            "crops": len(rows),
            "input_types": len(programme.input_categories or []),
            "requested_hectares": str(sum((figures["requested_hectares"] for figures in per_batch.values()), ZERO)),
            "approved_hectares": str(approved),
            "allocated_hectares": str(allocated),
            "remaining_hectares": str(max(approved - allocated, ZERO)),
            "farmers": allocations.values("farmer_id").distinct().count(),
        },
        "crops": rows,
    }
