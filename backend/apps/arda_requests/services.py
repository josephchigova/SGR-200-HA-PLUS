from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.farmers.models import Farm
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.programmes.models import Programme, Season

from .models import ARDAFarmerRequest, ARDARequestBatch, RequestBatchLine

INPUT_TYPES = [("SEED", "Seed"), ("FERTILIZER", "Fertilizer"), ("CHEMICALS", "Chemicals")]


def allocations_using(*, programme, season, crop_label="", input_category="", exclude_allocation_id=None, unlinked_only=False):
    """Live allocations that take hectares from this programme's request batches.

    An allocation sourced per category uses a programme's hectares for each of Seed, Fertilizer
    or Chemicals that programme supplies. An older allocation took every input from its one
    programme, so it counts against every input type. With input_category, only allocations
    that took that input type from the programme count.
    """
    from apps.inputs.models import InputAllocation

    allocations = InputAllocation.objects.exclude(status=InputAllocation.STATUS_CANCELLED)
    if unlinked_only:
        # Allocations made before they were linked to an approved request.
        allocations = allocations.filter(request_batch__isnull=True)
    if season is None:
        allocations = allocations.filter(season__isnull=True, programme__season__isnull=True)
    else:
        allocations = allocations.filter(Q(season=season) | Q(season__isnull=True, programme__season=season))
    per_category = Q(sourced_by_category=True, calculation_lines__programme=programme)
    if input_category:
        per_category &= Q(calculation_lines__input_category=input_category)
    allocations = allocations.filter(Q(sourced_by_category=False, programme=programme) | per_category)
    if crop_label:
        allocations = allocations.filter(
            Q(crop_reference__name__iexact=crop_label)
            | Q(crop_reference__isnull=True, crop__iexact=crop_label)
        )
    if exclude_allocation_id is not None:
        allocations = allocations.exclude(pk=exclude_allocation_id)
    return InputAllocation.objects.filter(pk__in=allocations.values("pk"))


def batches_for(*, programme, season, crop_label="", input_category=""):
    """Request batches that give hectares to allocations of this programme, crop, input type and year.

    A batch without an input type (made before input types existed) covers every input.
    """
    batches = ARDARequestBatch.objects.filter(programme=programme, status__in=ARDARequestBatchService.ACTIVE_BATCH_STATUSES)
    if input_category:
        batches = batches.filter(input_category__in=[input_category, ""])
    batches = batches.filter(season__isnull=True) if season is None else batches.filter(Q(season=season) | Q(season__isnull=True))
    if crop_label:
        batches = batches.filter(Q(crop__iexact=crop_label) | Q(crop="") | Q(crop__isnull=True))
    return batches


def programme_hectares(*, programme, season, crop_label="", input_category="", exclude_allocation_id=None):
    """Hectares requested in this programme's batches for an input type, hectares already allocated and hectares left."""
    batches = list(batches_for(programme=programme, season=season, crop_label=crop_label, input_category=input_category).order_by("date_created", "pk"))
    requested = sum((Decimal(batch.requested_hectares or 0) for batch in batches), Decimal("0.00"))
    allocated = allocations_using(
        programme=programme, season=season, crop_label=crop_label, input_category=input_category,
        exclude_allocation_id=exclude_allocation_id,
    ).aggregate(total=Sum("hectares"))["total"] or Decimal("0.00")
    return {
        "requested_hectares": requested,
        "allocated_hectares": allocated,
        "available_hectares": max(requested - allocated, Decimal("0.00")),
        "batches": [batch.request_number for batch in batches],
    }


def batch_allocations(batch, *, exclude_allocation_id=None):
    """Live allocations that use this request's hectares.

    Allocations linked to the request count, plus older allocations that were never linked to
    a request and match its programme, crop, input type and year.
    """
    from apps.inputs.models import InputAllocation

    linked = InputAllocation.objects.filter(request_batch=batch).exclude(status=InputAllocation.STATUS_CANCELLED)
    older = allocations_using(
        programme=batch.programme, season=batch.season, crop_label=(batch.crop or "").strip(),
        input_category=batch.input_category, unlinked_only=True,
    )
    allocations = InputAllocation.objects.filter(Q(pk__in=linked.values("pk")) | Q(pk__in=older.values("pk")))
    if exclude_allocation_id is not None:
        allocations = allocations.exclude(pk=exclude_allocation_id)
    return allocations


def batch_figures(batch, *, exclude_allocation_id=None):
    """Requested, approved, allocated and remaining hectares of one input request.

    Every page and report reads these figures from here, so they always agree. Only an approved
    request has hectares to allocate; a draft, submitted or rejected one has none.
    """
    allocations = batch_allocations(batch, exclude_allocation_id=exclude_allocation_id)
    allocated = allocations.aggregate(total=Sum("hectares"))["total"] or Decimal("0.00")
    approved = Decimal(batch.approved_hectares or 0) if batch.status == ARDARequestBatch.STATUS_APPROVED else Decimal("0.00")
    return {
        "requested_hectares": Decimal(batch.requested_hectares or 0),
        "approved_hectares": approved,
        "allocated_hectares": allocated,
        "available_hectares": max(approved - allocated, Decimal("0.00")),
        "unique_farmers": allocations.values("farmer_id").distinct().count(),
    }


class RequestWorkflowError(ValueError):
    pass


def _hectares(value, label):
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception as error:
        raise RequestWorkflowError(f"Enter {label} as a number.") from error
    return number


def line_allocations(line, *, exclude_allocation_id=None):
    """Live allocations that took this product or variety from the request."""
    from apps.inputs.models import InputAllocation

    allocations = InputAllocation.objects.filter(calculation_lines__request_line=line).exclude(status=InputAllocation.STATUS_CANCELLED)
    if exclude_allocation_id is not None:
        allocations = allocations.exclude(pk=exclude_allocation_id)
    return InputAllocation.objects.filter(pk__in=allocations.values("pk"))


def line_figures(line, *, exclude_allocation_id=None):
    """Requested, approved, allocated and remaining hectares of one product or variety in a request."""
    allocations = line_allocations(line, exclude_allocation_id=exclude_allocation_id)
    allocated = allocations.aggregate(total=Sum("hectares"))["total"] or Decimal("0.00")
    approved = Decimal(line.approved_hectares or 0) if line.batch.status == ARDARequestBatch.STATUS_APPROVED else Decimal("0.00")
    return {
        "requested_hectares": Decimal(line.requested_hectares),
        "approved_hectares": approved,
        "allocated_hectares": allocated,
        "available_hectares": max(approved - allocated, Decimal("0.00")),
        "farmers": allocations.values("farmer_id").distinct().count(),
    }


def prepare_request_lines(*, programme, crop_label, input_category, lines):
    """Check the products and varieties of a request and work out its total hectares.

    Each line names a line of the programme's own catalogue for the crop and the hectares
    wanted for it. Products of one input type cover different land (Mbizi on 8,000 ha and
    Shumba on 7,000 ha is 15,000 ha), so their hectares are added up. Different input types go
    on the same land, so the request's hectares are the largest of those sums.
    Returns ([(catalogue line, hectares)], total hectares).
    """
    from apps.programmes.models import Crop, CropInputRequirement

    crop = Crop.objects.filter(name__iexact=(crop_label or "").strip()).first()
    seen = set()
    rows = []
    by_type = {}
    for item in lines or []:
        requirement = CropInputRequirement.objects.select_related("input_product").filter(pk=item.get("requirement")).first()
        if requirement is None or requirement.programme_id != programme.pk or crop is None or requirement.crop_id != crop.pk:
            raise RequestWorkflowError(f"Choose products from {programme.name}'s {crop_label} catalogue.")
        name = requirement.input_product.name if requirement.input_product_id else requirement.item_name
        if not requirement.active:
            raise RequestWorkflowError(f"{name} is switched off in the catalogue.")
        if input_category and requirement.input_category != input_category:
            raise RequestWorkflowError(f"{name} is not {dict(INPUT_TYPES).get(input_category, input_category).lower()}, which this request is for.")
        if requirement.pk in seen:
            raise RequestWorkflowError(f"{name} is listed twice.")
        seen.add(requirement.pk)
        hectares = _hectares(item.get("requested_hectares"), f"the hectares for {name}")
        if hectares <= 0:
            raise RequestWorkflowError(f"Enter hectares greater than zero for {name}, or leave it out.")
        rows.append((requirement, hectares))
        by_type[requirement.input_category] = by_type.get(requirement.input_category, Decimal("0.00")) + hectares
    total = max(by_type.values()) if by_type else Decimal("0.00")
    return rows, total


def apply_request_lines(batch, rows):
    """Save a request's products and varieties without breaking allocations already made from it.

    A product keeps its line, so allocations stay linked to it. Its hectares cannot drop below
    what is already allocated, and a product given to a farmer cannot be removed.
    """
    from apps.inputs.models import InputAllocationLine

    existing = {line.requirement_id: line for line in batch.lines.select_related("requirement__input_product")}
    wanted = {requirement.pk for requirement, _hectares in rows}
    for requirement, hectares in rows:
        line = existing.get(requirement.pk)
        if line is None:
            RequestBatchLine.objects.create(batch=batch, requirement=requirement, requested_hectares=hectares, approved_hectares=hectares)
            continue
        allocated = line_figures(line)["allocated_hectares"]
        if hectares < allocated:
            raise RequestWorkflowError(
                f"{requirement.input_product.name if requirement.input_product_id else requirement.item_name}: "
                f"{allocated.normalize():f} ha is already allocated to farmers, so it cannot be set below that."
            )
        line.requested_hectares = hectares
        line.approved_hectares = hectares
        line.save(update_fields=["requested_hectares", "approved_hectares"])
    for requirement_id, line in existing.items():
        if requirement_id in wanted:
            continue
        if line_allocations(line).exists():
            name = line.requirement.input_product.name if line.requirement.input_product_id else line.requirement.item_name
            raise RequestWorkflowError(f"{name} is already allocated to farmers, so it cannot be removed. Cancel those allocations first.")
        # Cancelled allocations keep their own copy of the product and price.
        InputAllocationLine.objects.filter(request_line=line).update(request_line=None)
        line.delete()


class ARDARequestBatchService:
    ACTIVE_BATCH_STATUSES = [
        ARDARequestBatch.STATUS_PENDING,
        ARDARequestBatch.STATUS_SUBMITTED,
        ARDARequestBatch.STATUS_APPROVED,
    ]

    @staticmethod
    def _normalize_crop(crop):
        return (crop or "").strip()

    @classmethod
    def _ensure_active_season(cls, season):
        if season is None:
            raise ValueError("Select an active season for this ARDA request.")
        if season.status != Season.STATUS_ACTIVE:
            raise ValueError("ARDA requests can only be created or edited for the active season.")

    @classmethod
    def _active_duplicate_queryset(cls, *, programme, season, crop_label, input_category="", exclude_batch=None):
        # One request per programme, crop and agricultural year, whatever its input type.
        queryset = ARDARequestBatch.objects.filter(
            programme=programme,
            season=season,
            status__in=cls.ACTIVE_BATCH_STATUSES,
        )
        if exclude_batch is not None:
            queryset = queryset.exclude(pk=exclude_batch.pk)
        if crop_label:
            return queryset.filter(crop__iexact=crop_label)
        return queryset.filter(Q(crop__isnull=True) | Q(crop=""))

    @classmethod
    def _ensure_no_duplicate_active_request(cls, *, programme, season, crop_label, input_category="", exclude_batch=None):
        duplicate = cls._active_duplicate_queryset(
            programme=programme,
            season=season,
            crop_label=crop_label,
            input_category=input_category,
            exclude_batch=exclude_batch,
        ).first()
        if duplicate is None:
            return

        readable_crop = crop_label or "Unspecified crop"
        raise ValueError(
            f"{programme.name} already has a request for {readable_crop} in {season.name} ({duplicate.request_number}). "
            "Please edit the existing request instead."
        )

    @classmethod
    def _allocation_queryset_for_scope(cls, *, programme, season, crop_label, input_category=""):
        return allocations_using(programme=programme, season=season, crop_label=crop_label, input_category=input_category)

    @classmethod
    def allocation_snapshot(cls, *, programme, season, crop_label, input_category=""):
        allocations = allocations_using(programme=programme, season=season, crop_label=crop_label, input_category=input_category)
        allocated_hectares = allocations.aggregate(total=Sum("hectares"))["total"] or Decimal("0.00")
        unique_farmers = allocations.values("farmer_id").distinct().count()
        return {
            "allocated_hectares": allocated_hectares,
            "unique_farmers": unique_farmers,
        }

    @classmethod
    def batch_snapshot(cls, batch):
        return batch_figures(batch)

    @staticmethod
    def _next_request_number(sequence):
        highest_existing = 999
        request_numbers = ARDARequestBatch.objects.filter(request_number__startswith="SGR").values_list(
            "request_number", flat=True
        )
        for request_number in request_numbers:
            suffix = request_number[3:]
            if suffix.isdecimal():
                highest_existing = max(highest_existing, int(suffix))
        number = max(sequence.next_number, highest_existing + 1, 1000)
        while ARDARequestBatch.objects.filter(request_number=f"SGR{number}").exists():
            number += 1
        return number

    @staticmethod
    def _validate_batch_capacity(programme, requested_hectares, exclude_batch=None, input_category=""):
        # Seed, Fertilizer and Chemicals for the same field are separate requests, so each input
        # type is checked against the programme's capacity on its own.
        active_batches = ARDARequestBatch.objects.filter(
            programme=programme,
            status__in=ARDARequestBatchService.ACTIVE_BATCH_STATUSES,
        )
        if input_category:
            active_batches = active_batches.filter(input_category__in=[input_category, ""])
        if exclude_batch is not None:
            active_batches = active_batches.exclude(pk=exclude_batch.pk)
        if requested_hectares <= 0:
            raise ValueError("Requested hectares must be greater than zero.")
        # Older programmes carry a hectare capacity. Programmes without one are limited by approval alone.
        if programme.announced_hectares and programme.announced_hectares > 0:
            previously_requested = active_batches.aggregate(total=Sum("requested_hectares"))["total"] or Decimal("0.00")
            if previously_requested + requested_hectares > programme.announced_hectares:
                raise ValueError("Requested hectares exceed the remaining programme capacity.")

    @staticmethod
    def _validate_programme_fit(*, programme, season, crop_label, input_category):
        """A request must match its programme: active, same agricultural year, a crop and input type it supports."""
        from apps.programmes.models import Crop

        if not programme.is_active:
            raise ValueError(f"{programme.name} is inactive. Activate it before requesting inputs from it.")
        if programme.season_id and season is not None and programme.season_id != season.pk:
            raise ValueError(f"{programme.name} belongs to {programme.season.name}, not {season.name}.")
        if not crop_label:
            raise ValueError("Select the crop this request is for.")
        crop = Crop.objects.filter(name__iexact=crop_label).first()
        if crop is None or not programme.supports_crop(crop):
            raise ValueError(f"{programme.name} does not support {crop_label}. Add the crop to the programme first.")
        if input_category and programme.input_categories and input_category not in programme.input_categories:
            label = dict(INPUT_TYPES).get(input_category, input_category).lower()
            raise ValueError(f"{programme.name} does not supply {label}.")

    @classmethod
    @transaction.atomic
    def create_batch(cls, *, validated_data, created_by=None):
        from .models import ARDARequestNumberSequence

        sequence, _ = ARDARequestNumberSequence.objects.select_for_update().get_or_create(
            pk=1,
            defaults={"next_number": 1000},
        )
        number = cls._next_request_number(sequence)
        programme = Programme.objects.select_for_update().get(pk=validated_data["programme"].pk)
        season = validated_data.get("season") or programme.season
        cls._ensure_active_season(season)
        crop_label = cls._normalize_crop(validated_data.get("crop"))
        input_category = validated_data.get("input_category", "")
        cls._validate_programme_fit(programme=programme, season=season, crop_label=crop_label, input_category=input_category)
        lines = validated_data.pop("lines", None)
        rows, total = prepare_request_lines(programme=programme, crop_label=crop_label, input_category=input_category, lines=lines)
        if rows:
            requested_hectares = total
        elif validated_data.get("requested_hectares"):
            # Requests made without products give their hectares directly.
            requested_hectares = Decimal(str(validated_data["requested_hectares"]))
        else:
            raise RequestWorkflowError("Enter hectares for at least one product or variety.")
        cls._ensure_no_duplicate_active_request(
            programme=programme,
            season=season,
            crop_label=crop_label,
            input_category=input_category,
        )
        cls._validate_batch_capacity(programme, requested_hectares, input_category=input_category)

        batch_data = {
            key: value
            for key, value in validated_data.items()
            if key not in {"instance", "request_number", "created_by"}
        }
        batch_data.update(
            {
                "programme": programme,
                "request_number": f"SGR{number}",
                "season": season,
                "requested_hectares": requested_hectares,
                "created_by": created_by or validated_data.get("created_by"),
                # Making the request means the programme has agreed to it: it is approved at once.
                "status": ARDARequestBatch.STATUS_APPROVED,
                "approved_hectares": requested_hectares if requested_hectares > 0 else None,
                "approved_by": created_by or validated_data.get("created_by"),
                "decided_at": timezone.now(),
            }
        )
        batch = ARDARequestBatch.objects.create(**batch_data)
        apply_request_lines(batch, rows)
        sequence.next_number = number + 1
        sequence.save(update_fields=["next_number"])
        return batch

    @classmethod
    @transaction.atomic
    def update_batch(cls, *, instance, validated_data):
        """Change a request while keeping every allocation made from it valid."""
        batch = ARDARequestBatch.objects.select_for_update().get(pk=instance.pk)
        if batch.status == ARDARequestBatch.STATUS_REJECTED:
            raise ValueError(f"{batch.request_number} was rejected, so it can no longer be changed.")
        lines = validated_data.pop("lines", None)
        programme = validated_data.get("programme", batch.programme)
        programme = Programme.objects.select_for_update().get(pk=programme.pk)
        season = validated_data.get("season", batch.season or programme.season)
        cls._ensure_active_season(season)
        crop_label = cls._normalize_crop(validated_data.get("crop", batch.crop))
        input_category = validated_data.get("input_category", batch.input_category)
        cls._validate_programme_fit(programme=programme, season=season, crop_label=crop_label, input_category=input_category)
        same_place = (
            programme.pk == batch.programme_id and (season is None or season.pk == batch.season_id)
            and crop_label.lower() == cls._normalize_crop(batch.crop).lower()
        )
        if not same_place:
            # Two requests made before this rule may share a programme and crop; they stay editable.
            cls._ensure_no_duplicate_active_request(
                programme=programme,
                season=season,
                crop_label=crop_label,
                input_category=input_category,
                exclude_batch=batch,
            )
        figures = batch_figures(batch)
        moved = (
            programme.pk != batch.programme_id or (season and season.pk != batch.season_id)
            or input_category != batch.input_category or crop_label.lower() != cls._normalize_crop(batch.crop).lower()
        )
        if figures["allocated_hectares"] > 0 and moved:
            raise ValueError("Hectares from this request are already allocated, so its programme, crop, year and input type cannot change.")

        if lines is None:
            # Keep the products already asked for; they must still fit the request.
            lines = [{"requirement": line.requirement_id, "requested_hectares": line.requested_hectares} for line in batch.lines.all()]
        rows, total = prepare_request_lines(programme=programme, crop_label=crop_label, input_category=input_category, lines=lines)
        if rows:
            requested_hectares = total
        elif batch.lines.exists():
            raise RequestWorkflowError("Enter hectares for at least one product or variety.")
        else:
            requested_hectares = Decimal(str(validated_data.get("requested_hectares", batch.requested_hectares)))
        cls._validate_batch_capacity(programme, requested_hectares, exclude_batch=batch, input_category=input_category)
        if figures["allocated_hectares"] > requested_hectares:
            raise ValueError(
                "Requested hectares cannot be less than the hectares already allocated. "
                f"Already allocated: {figures['allocated_hectares']:.2f} ha."
            )

        for field, value in validated_data.items():
            if field not in {"created_by", "request_number", "requested_hectares"}:
                setattr(batch, field, value)
        batch.programme = programme
        batch.season = season
        batch.requested_hectares = requested_hectares
        if batch.status != ARDARequestBatch.STATUS_APPROVED:
            batch.status = ARDARequestBatch.STATUS_APPROVED
            batch.decided_at = timezone.now()
        batch.approved_hectares = requested_hectares if requested_hectares > 0 else None
        batch.save()
        if rows or batch.lines.exists():
            apply_request_lines(batch, rows)
        return batch


class ARDARequestService:
    @staticmethod
    @transaction.atomic
    def add_farmer(*, batch: ARDARequestBatch, farmer, requested_hectares, farm=None):
        batch = ARDARequestBatch.objects.select_for_update().get(pk=batch.pk)
        hectares = Decimal(str(requested_hectares))
        if batch.status == ARDARequestBatch.STATUS_REJECTED:
            raise ValueError("A rejected request batch cannot be changed.")
        if hectares <= 0:
            raise ValueError("Requested hectares must be greater than zero.")
        eligibility_season = batch.season or batch.programme.season
        eligibility = FarmerApprovalEligibilityService.evaluate_for_arda(farmer, eligibility_season)
        if not eligibility["eligible"]:
            raise ValueError("Farmer is ineligible: " + " ".join(eligibility["reasons"]))
        selected_farm = farm or Farm.objects.filter(farmer=farmer).first()
        if selected_farm is None or selected_farm.farmer_id != farmer.pk:
            raise ValueError("Select a farm belonging to this farmer.")
        if hectares > selected_farm.arable_hectares:
            raise ValueError("Requested hectares exceed the farm's arable hectares.")
        if ARDAFarmerRequest.objects.filter(request_batch=batch, farmer=farmer).exists():
            raise ValueError("Farmer is already included in this request batch.")

        batch_current_requests = batch.farmer_requests.exclude(
            status__in=[ARDAFarmerRequest.STATUS_REJECTED, ARDAFarmerRequest.STATUS_CANCELLED]
        ).aggregate(total=Sum("requested_hectares"))["total"] or Decimal("0.00")
        if batch_current_requests + hectares > batch.requested_hectares:
            raise ValueError("Requested hectares exceed this batch's remaining requested hectares.")

        programme = Programme.objects.select_for_update().get(pk=batch.programme_id)
        included_batch_statuses = [ARDARequestBatch.STATUS_PENDING, ARDARequestBatch.STATUS_SUBMITTED, ARDARequestBatch.STATUS_APPROVED]
        current_requests = sum(
            ARDAFarmerRequest.objects.filter(
                request_batch__programme=programme,
                request_batch__status__in=included_batch_statuses,
            ).exclude(
                status__in=[ARDAFarmerRequest.STATUS_REJECTED, ARDAFarmerRequest.STATUS_CANCELLED]
            ).values_list("requested_hectares", flat=True),
            Decimal("0.00"),
        )
        if programme.announced_hectares > 0 and current_requests + hectares > programme.announced_hectares:
            raise ValueError("Requested hectares exceed the remaining programme capacity.")

        request_line = ARDAFarmerRequest.objects.create(
            request_batch=batch,
            farmer=farmer,
            farm=selected_farm,
            requested_hectares=hectares,
        )
        batch.total_farmers = batch.farmer_requests.count()
        batch.total_requested_hectares = sum(
            batch.farmer_requests.values_list("requested_hectares", flat=True), Decimal("0.00")
        )
        batch.save(update_fields=["total_farmers", "total_requested_hectares"])
        return request_line