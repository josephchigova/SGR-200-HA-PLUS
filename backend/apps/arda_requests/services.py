from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from apps.farmers.models import Farm
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.programmes.models import Programme
from apps.programmes.models import Season

from .models import ARDAFarmerRequest, ARDARequestBatch


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
    def _active_duplicate_queryset(cls, *, programme, season, crop_label, exclude_batch=None):
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
    def _ensure_no_duplicate_active_request(cls, *, programme, season, crop_label, exclude_batch=None):
        duplicate = cls._active_duplicate_queryset(
            programme=programme,
            season=season,
            crop_label=crop_label,
            exclude_batch=exclude_batch,
        ).first()
        if duplicate is None:
            return

        readable_crop = crop_label or "Unspecified crop"
        raise ValueError(
            f"An ARDA request for {readable_crop} under {programme.name} already exists for the {season.name} season. "
            "Please edit the existing request instead."
        )

    @classmethod
    def _allocation_queryset_for_scope(cls, *, programme, season, crop_label):
        from apps.inputs.models import InputAllocation

        allocations = InputAllocation.objects.filter(
            programme=programme,
        ).exclude(status=InputAllocation.STATUS_CANCELLED)
        if season is None:
            allocations = allocations.filter(programme__season__isnull=True)
        else:
            allocations = allocations.filter(programme__season=season)
        if crop_label:
            allocations = allocations.filter(
                Q(crop_reference__name__iexact=crop_label)
                | Q(crop_reference__isnull=True, crop__iexact=crop_label)
            )
        return allocations

    @classmethod
    def allocation_snapshot(cls, *, programme, season, crop_label):
        allocations = cls._allocation_queryset_for_scope(
            programme=programme,
            season=season,
            crop_label=crop_label,
        )
        allocated_hectares = allocations.aggregate(total=Sum("hectares"))["total"] or Decimal("0.00")
        unique_farmers = allocations.values("farmer_id").distinct().count()
        return {
            "allocated_hectares": allocated_hectares,
            "unique_farmers": unique_farmers,
        }

    @classmethod
    def batch_snapshot(cls, batch):
        crop_label = cls._normalize_crop(batch.crop)
        snapshot = cls.allocation_snapshot(
            programme=batch.programme,
            season=batch.season,
            crop_label=crop_label,
        )
        available_hectares = max(Decimal(str(batch.requested_hectares or 0)) - snapshot["allocated_hectares"], Decimal("0.00"))
        return {
            **snapshot,
            "available_hectares": available_hectares,
        }

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
    def _validate_batch_capacity(programme, requested_hectares, exclude_batch=None):
        active_batches = ARDARequestBatch.objects.filter(
            programme=programme,
            status__in=ARDARequestBatchService.ACTIVE_BATCH_STATUSES,
        )
        if exclude_batch is not None:
            active_batches = active_batches.exclude(pk=exclude_batch.pk)
        previously_requested = active_batches.aggregate(total=Sum("requested_hectares"))["total"] or Decimal("0.00")
        if requested_hectares <= 0 or previously_requested + requested_hectares > programme.announced_hectares:
            raise ValueError("Requested hectares exceed the remaining programme capacity.")

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
        requested_hectares = Decimal(str(validated_data["requested_hectares"]))
        season = validated_data.get("season") or programme.season
        cls._ensure_active_season(season)
        crop_label = cls._normalize_crop(validated_data.get("crop"))
        cls._ensure_no_duplicate_active_request(
            programme=programme,
            season=season,
            crop_label=crop_label,
        )
        cls._validate_batch_capacity(programme, requested_hectares)

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
            }
        )
        batch = ARDARequestBatch.objects.create(**batch_data)
        sequence.next_number = number + 1
        sequence.save(update_fields=["next_number"])
        return batch

    @classmethod
    @transaction.atomic
    def update_batch(cls, *, instance, validated_data):
        batch = ARDARequestBatch.objects.select_for_update().get(pk=instance.pk)
        programme = validated_data.get("programme", batch.programme)
        programme = Programme.objects.select_for_update().get(pk=programme.pk)
        season = validated_data.get("season", batch.season or programme.season)
        cls._ensure_active_season(season)
        crop_label = cls._normalize_crop(validated_data.get("crop", batch.crop))
        cls._ensure_no_duplicate_active_request(
            programme=programme,
            season=season,
            crop_label=crop_label,
            exclude_batch=batch,
        )
        requested_hectares = Decimal(str(validated_data.get("requested_hectares", batch.requested_hectares)))
        cls._validate_batch_capacity(programme, requested_hectares, exclude_batch=batch)

        allocated_snapshot = cls.allocation_snapshot(
            programme=programme,
            season=season,
            crop_label=crop_label,
        )
        if allocated_snapshot["allocated_hectares"] > requested_hectares:
            raise ValueError(
                "Requested hectares cannot be less than the hectares already allocated. "
                f"Already allocated: {allocated_snapshot['allocated_hectares']:.2f} ha."
            )

        for field, value in validated_data.items():
            if field not in {"created_by", "request_number"}:
                setattr(batch, field, value)
        batch.programme = programme
        batch.season = season
        batch.requested_hectares = requested_hectares
        batch.save()
        return batch


class ARDARequestService:
    @staticmethod
    @transaction.atomic
    def add_farmer(*, batch: ARDARequestBatch, farmer, requested_hectares, farm=None):
        batch = ARDARequestBatch.objects.select_for_update().get(pk=batch.pk)
        hectares = Decimal(str(requested_hectares))
        if batch.status in {ARDARequestBatch.STATUS_APPROVED, ARDARequestBatch.STATUS_REJECTED}:
            raise ValueError("A finalized request batch cannot be changed.")
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
        if current_requests + hectares > programme.announced_hectares:
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