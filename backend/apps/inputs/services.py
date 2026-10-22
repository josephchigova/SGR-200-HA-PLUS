from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.services import FarmerApprovalEligibilityService
from apps.farmers.models import Farm
from apps.inputs.models import InputAllocation, InputAllocationLine
from apps.programmes.models import Crop, CropInputRequirement
from apps.programmes.services import CropPricingService
from apps.recovery.services import RecoveryCalculationService


class InputAllocationService:
    @staticmethod
    def _resolve_crop(crop_reference, crop_name):
        if crop_reference is not None:
            return crop_reference
        if crop_name:
            return Crop.objects.filter(name__iexact=crop_name.strip()).first()
        return None

    @staticmethod
    def _scoped_arda_batches(*, programme, crop_label):
        included_statuses = [
            ARDARequestBatch.STATUS_PENDING,
            ARDARequestBatch.STATUS_SUBMITTED,
            ARDARequestBatch.STATUS_APPROVED,
        ]
        queryset = ARDARequestBatch.objects.filter(
            programme_id=programme.pk,
            status__in=included_statuses,
        )
        if programme.season_id is None:
            queryset = queryset.filter(season__isnull=True)
        else:
            queryset = queryset.filter(Q(season_id=programme.season_id) | Q(season__isnull=True))

        if crop_label:
            generic_crop = Q(crop__isnull=True) | Q(crop="")
            queryset = queryset.filter(Q(crop__iexact=crop_label) | generic_crop)
        return queryset

    @staticmethod
    def _scoped_allocations(*, programme, crop_label):
        allocations = InputAllocation.objects.filter(programme=programme).exclude(status=InputAllocation.STATUS_CANCELLED)
        if crop_label:
            allocations = allocations.filter(
                Q(crop_reference__name__iexact=crop_label)
                | Q(crop_reference__isnull=True, crop__iexact=crop_label)
            )
        return allocations

    @staticmethod
    def _scope_capacity(*, programme, crop_label, exclude_allocation_id=None):
        capacity_batches = InputAllocationService._scoped_arda_batches(programme=programme, crop_label=crop_label)
        requested_hectares = sum(capacity_batches.values_list("requested_hectares", flat=True), Decimal("0.00"))

        scoped_allocations = InputAllocationService._scoped_allocations(programme=programme, crop_label=crop_label)
        if exclude_allocation_id is not None:
            scoped_allocations = scoped_allocations.exclude(pk=exclude_allocation_id)
        allocated_hectares = sum(scoped_allocations.values_list("hectares", flat=True), Decimal("0.00"))
        available_hectares = max(requested_hectares - allocated_hectares, Decimal("0.00"))
        return {
            "requested_hectares": requested_hectares,
            "allocated_hectares": allocated_hectares,
            "available_hectares": available_hectares,
        }

    @staticmethod
    def _validate_hectares(*, farmer, farm, programme, hectares, crop_reference=None, crop_name="", allocation_id=None):
        allocation_hectares = Decimal(str(hectares))
        if allocation_hectares <= 0:
            raise ValueError("Allocation hectares must be greater than zero.")

        eligibility = FarmerApprovalEligibilityService.evaluate_for_arda(farmer, programme.season)
        if not eligibility["eligible"]:
            raise ValueError("Farmer is ineligible for ARDA input allocation: " + " ".join(eligibility["reasons"]))

        selected_farm = farm or Farm.objects.filter(farmer=farmer).first()
        if selected_farm is None or selected_farm.farmer_id != farmer.pk:
            raise ValueError("Select a farm belonging to this farmer.")
        farm_arable_hectares = Decimal(str(selected_farm.arable_hectares or 0))
        if allocation_hectares > farm_arable_hectares:
            raise ValueError("Allocation hectares exceed the farm's arable hectares.")

        crop_label = (crop_name or getattr(crop_reference, "name", "")).strip()

        capacity = InputAllocationService._scope_capacity(
            programme=programme,
            crop_label=crop_label,
            exclude_allocation_id=allocation_id,
        )
        total_batch_requested_hectares = capacity["requested_hectares"]
        if total_batch_requested_hectares <= 0:
            raise ValueError(
                "No ARDA request hectares were found for the selected programme, season, and crop. "
                "Create an ARDA request batch with requested hectares first."
            )

        total_allocated_scope = capacity["allocated_hectares"]
        if total_allocated_scope + allocation_hectares > total_batch_requested_hectares:
            remaining_scope = max(total_batch_requested_hectares - total_allocated_scope, Decimal("0.00"))
            raise ValueError(
                "Allocation exceeds the ARDA request batch capacity. "
                f"Requested in ARDA batches: {total_batch_requested_hectares:.2f} ha, "
                f"already allocated: {total_allocated_scope:.2f} ha, "
                f"requested now: {allocation_hectares:.2f} ha, "
                f"remaining: {remaining_scope:.2f} ha."
            )

        approved_queryset = ARDAFarmerRequest.objects.filter(
            farmer_id=farmer.pk,
            request_batch__programme_id=programme.pk,
            status=ARDAFarmerRequest.STATUS_APPROVED,
        )
        if programme.season_id is None:
            approved_queryset = approved_queryset.filter(request_batch__season__isnull=True)
        else:
            approved_queryset = approved_queryset.filter(
                Q(request_batch__season_id=programme.season_id)
                | Q(request_batch__season__isnull=True)
            )

        if crop_label:
            generic_crop = Q(request_batch__crop__isnull=True) | Q(request_batch__crop="")
            approval_scopes = [
                approved_queryset.filter(farm_id=selected_farm.pk, request_batch__crop__iexact=crop_label),
                approved_queryset.filter(farm__isnull=True, request_batch__crop__iexact=crop_label),
                approved_queryset.filter(farm_id=selected_farm.pk).filter(generic_crop),
                approved_queryset.filter(farm__isnull=True).filter(generic_crop),
            ]
        else:
            approval_scopes = [
                approved_queryset.filter(farm_id=selected_farm.pk),
                approved_queryset.filter(farm__isnull=True),
            ]

        matching_approvals = next((scope for scope in approval_scopes if scope.exists()), None)
        if matching_approvals is not None:
            farmer_capacity_hectares = sum(matching_approvals.values_list("approved_hectares", flat=True), Decimal("0.00"))
            if farmer_capacity_hectares <= 0:
                raise ValueError(
                    "The matching approved ARDA farmer request has no positive approved hectares. "
                    "Verify its approved hectares value."
                )
            capacity_label = "approved ARDA"
        else:
            # When no farmer-level ARDA approvals exist, use verified+paid farmer eligibility and farm arable hectares.
            farmer_capacity_hectares = farm_arable_hectares
            capacity_label = "eligible"

        allocations = InputAllocation.objects.filter(
            farmer=farmer,
            farm=selected_farm,
            programme=programme,
        ).exclude(status=InputAllocation.STATUS_CANCELLED)
        if crop_label:
            allocations = allocations.filter(
                Q(crop_reference__name__iexact=crop_label)
                | Q(crop_reference__isnull=True, crop__iexact=crop_label)
            )
        if allocation_id is not None:
            allocations = allocations.exclude(pk=allocation_id)
        if allocation_id is None and allocations.exists():
            raise ValueError(
                "An input allocation for this farmer, farm, programme, crop, and season already exists. "
                "Edit the existing allocation instead of creating a duplicate."
            )
        already_allocated = sum(allocations.values_list("hectares", flat=True), Decimal("0.00"))
        if already_allocated + allocation_hectares > farmer_capacity_hectares:
            remaining = max(farmer_capacity_hectares - already_allocated, Decimal("0.00"))
            raise ValueError(
                f"Allocation exceeds the farmer's {capacity_label} hectares. "
                f"Limit: {farmer_capacity_hectares:.2f} ha, "
                f"already allocated: {already_allocated:.2f} ha, "
                f"requested: {allocation_hectares:.2f} ha, "
                f"remaining: {remaining:.2f} ha."
            )
        return selected_farm, allocation_hectares

    @staticmethod
    def _calculate_lines(*, crop, hectares):
        requirements = CropInputRequirement.objects.filter(crop=crop, active=True).order_by("group_name", "item_name", "id")
        if not requirements.exists():
            raise ValueError(f"No active crop input requirements are configured for {crop.name}.")

        lines = []
        total_input_cost = Decimal("0.00")
        total_input_cost_per_hectare = Decimal("0.00")
        hectares_decimal = Decimal(str(hectares))

        for requirement in requirements:
            required_quantity = (hectares_decimal * requirement.rate_per_hectare).quantize(Decimal("0.0001"))
            if requirement.cost_per_unit is not None:
                calculated_cost = (required_quantity * requirement.cost_per_unit).quantize(Decimal("0.01"))
            else:
                calculated_cost = (hectares_decimal * requirement.cost_per_hectare).quantize(Decimal("0.01"))

            group_name = (requirement.group_name or "").lower()
            item_name = (requirement.item_name or "").lower()
            blocked = any(term in group_name or term in item_name for term in ("transport", "labour", "combine"))
            included = (
                requirement.include_in_input_cost
                and requirement.cost_type == CropInputRequirement.COST_TYPE_INPUT
                and not blocked
            )
            if included:
                total_input_cost += calculated_cost
                total_input_cost_per_hectare += requirement.cost_per_hectare

            lines.append({
                "source_requirement": requirement,
                "group_name": requirement.group_name,
                "item_name": requirement.item_name,
                "unit": requirement.unit,
                "rate_per_hectare": requirement.rate_per_hectare,
                "cost_per_unit": requirement.cost_per_unit,
                "cost_per_hectare": requirement.cost_per_hectare,
                "required_quantity": required_quantity,
                "calculated_cost": calculated_cost,
                "included_in_total": included,
            })

        return {
            "lines": lines,
            "total_input_cost": total_input_cost.quantize(Decimal("0.01")),
            "calculated_input_cost_per_hectare": total_input_cost_per_hectare.quantize(Decimal("0.01")),
        }

    @staticmethod
    def _assert_crop_season(crop, crop_season):
        if not crop_season or crop is None:
            return
        if crop.category != crop_season:
            label = "Summer" if crop_season == "SUMMER" else "Winter"
            raise ValueError(f"{crop.name} is not a {label} crop. Select a crop for the current season.")

    @staticmethod
    def preview_allocation(*, farmer, farm, programme, crop_reference=None, crop_name="", hectares=0, crop_season=None):
        crop = InputAllocationService._resolve_crop(crop_reference, crop_name)
        if crop is None:
            raise ValueError("Select a crop from the crop catalogue.")
        InputAllocationService._assert_crop_season(crop, crop_season)

        selected_farm, allocation_hectares = InputAllocationService._validate_hectares(
            farmer=farmer,
            farm=farm,
            programme=programme,
            hectares=hectares,
            crop_reference=crop,
            crop_name=crop.name,
        )
        calculation = InputAllocationService._calculate_lines(crop=crop, hectares=allocation_hectares)
        selling_price = CropPricingService.resolve_price_per_tonne(crop=crop, season=programme.season)
        required_recovery_tonnes = (calculation["total_input_cost"] / selling_price).quantize(Decimal("0.01"))
        capacity = InputAllocationService._scope_capacity(programme=programme, crop_label=crop.name)
        return {
            "farmer_id": farmer.pk,
            "farm_id": selected_farm.pk,
            "programme_id": programme.pk,
            "crop": crop.name,
            "hectares": allocation_hectares,
            "calculated_input_cost_per_hectare": calculation["calculated_input_cost_per_hectare"],
            "total_input_cost": calculation["total_input_cost"],
            "selling_price_per_tonne": selling_price,
            "required_recovery_tonnes": required_recovery_tonnes,
            "arda_requested_hectares": capacity["requested_hectares"],
            "arda_allocated_hectares": capacity["allocated_hectares"],
            "arda_available_hectares": capacity["available_hectares"],
            "lines": calculation["lines"],
        }

    @staticmethod
    @transaction.atomic
    def create_allocation(*, farmer, farm, programme, crop_reference=None, crop="", hectares=0, allocation_id=None, crop_season=None, **extra):
        crop_season = extra.pop("crop_season", crop_season)
        crop_obj = InputAllocationService._resolve_crop(crop_reference, crop)
        if crop_obj is None:
            raise ValueError("Select a crop from the crop catalogue.")
        InputAllocationService._assert_crop_season(crop_obj, crop_season)

        selected_farm, allocation_hectares = InputAllocationService._validate_hectares(
            farmer=farmer,
            farm=farm,
            programme=programme,
            hectares=hectares,
            crop_reference=crop_obj,
            crop_name=crop_obj.name,
            allocation_id=allocation_id,
        )
        calculation = InputAllocationService._calculate_lines(crop=crop_obj, hectares=allocation_hectares)

        values = {
            "farmer": farmer,
            "farm": selected_farm,
            "programme": programme,
            "crop_reference": crop_obj,
            "crop": crop_obj.name,
            "hectares": allocation_hectares,
            "quantity": Decimal("0.00"),
            "unit": "",
            "input": None,
            "calculated_input_cost_per_hectare": calculation["calculated_input_cost_per_hectare"],
            "total_input_cost": calculation["total_input_cost"],
            **extra,
        }
        if allocation_id is None:
            allocation = InputAllocation.objects.create(**values)
        else:
            allocation = InputAllocation.objects.select_for_update().get(pk=allocation_id)
            for field, value in values.items():
                setattr(allocation, field, value)
            allocation.save()

        allocation.calculation_lines.all().delete()
        InputAllocationLine.objects.bulk_create([
            InputAllocationLine(allocation=allocation, **line)
            for line in calculation["lines"]
        ])

        selling_price = CropPricingService.resolve_price_per_tonne(crop=crop_obj, season=programme.season)
        RecoveryCalculationService.create_or_update_from_allocation(
            allocation=allocation,
            selling_price_per_tonne=selling_price,
        )

        return allocation
