from decimal import Decimal
from typing import ClassVar

from django.db import models

from apps.farmers.models import Farmer
from apps.programmes.models import Crop, Programme, Season


class Input(models.Model):
    CATEGORY_SEED = "SEED"
    CATEGORY_FERTILIZER = "FERTILIZER"
    CATEGORY_CHEMICALS = "CHEMICALS"
    # Older names. Pesticides are now part of Chemicals.
    CATEGORY_PESTICIDE = "PESTICIDE"
    CATEGORY_TOOLKIT = "TOOLKIT"
    CATEGORY_OTHER = "OTHER"

    CATEGORY_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (CATEGORY_SEED, "Seed"),
        (CATEGORY_FERTILIZER, "Fertilizer"),
        (CATEGORY_CHEMICALS, "Chemicals"),
        (CATEGORY_PESTICIDE, "Pesticide"),
        (CATEGORY_TOOLKIT, "Toolkit"),
        (CATEGORY_OTHER, "Other"),
    ]

    name = models.CharField(max_length=160, unique=True)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default=CATEGORY_SEED)
    unit = models.CharField(max_length=40, default="bags")
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InputIssue(models.Model):
    STATUS_ISSUED = "ISSUED"
    STATUS_PENDING = "PENDING"
    STATUS_COLLECTED = "COLLECTED"
    STATUS_RETURNED = "RETURNED"

    STATUS_CHOICES = [
        (STATUS_ISSUED, "Issued"),
        (STATUS_PENDING, "Pending"),
        (STATUS_COLLECTED, "Collected"),
        (STATUS_RETURNED, "Returned"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="input_issues")
    input_name = models.CharField(max_length=180)
    batch_number = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, default="bags")
    issue_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    issue_date = models.DateTimeField(auto_now_add=True)
    collected_date = models.DateTimeField(null=True, blank=True)
    issued_by = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"{self.input_name} - {self.farmer.full_name}"


class InputAllocation(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_ALLOCATED = "ALLOCATED"
    STATUS_COLLECTED = "COLLECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ALLOCATED, "Allocated"),
        (STATUS_COLLECTED, "Collected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="input_allocations")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="input_allocations", null=True, blank=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="input_allocations")
    crop_reference = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="input_allocations", null=True, blank=True)
    input = models.ForeignKey(Input, on_delete=models.PROTECT, related_name="allocations", null=True, blank=True)
    crop = models.CharField(max_length=80, blank=True)
    hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), blank=True)
    unit = models.CharField(max_length=40, default="", blank=True)
    calculated_input_cost_per_hectare = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    total_input_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    allocation_date = models.DateField(auto_now_add=True)
    allocation_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    collection_date = models.DateField(null=True, blank=True)
    # Allocations made per input category name their agricultural year here, because each
    # category can come from a different programme. Older allocations use programme.season.
    season = models.ForeignKey("programmes.Season", on_delete=models.PROTECT, related_name="input_allocations", null=True, blank=True)
    sourced_by_category = models.BooleanField(default=False)
    # The approved input request whose hectares this allocation uses. Allocations made before
    # requests were approved have none and are matched to their programme, crop and year instead.
    request_batch = models.ForeignKey(
        "arda_requests.ARDARequestBatch", on_delete=models.PROTECT, related_name="allocations", null=True, blank=True,
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_allocations")
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_allocations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-allocation_date"]

    def __str__(self):
        return f"{self.crop or (self.crop_reference.name if self.crop_reference_id else 'Allocation')} - {self.farmer.full_name}"


class InputAllocationLine(models.Model):
    allocation = models.ForeignKey(InputAllocation, on_delete=models.CASCADE, related_name="calculation_lines")
    source_requirement = models.ForeignKey("programmes.CropInputRequirement", on_delete=models.SET_NULL, null=True, blank=True, related_name="allocation_lines")
    # Where this line's input comes from. The price below is a snapshot taken when the
    # allocation was made, so later catalogue price changes do not alter it.
    input_category = models.CharField(max_length=20, blank=True, default="")
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="allocation_lines", null=True, blank=True)
    input_product = models.ForeignKey(Input, on_delete=models.PROTECT, related_name="allocation_lines", null=True, blank=True)
    batch_input = models.ForeignKey(
        "arda_requests.RequestBatchInput", on_delete=models.PROTECT, related_name="allocation_lines", null=True, blank=True,
    )
    # The approved request line (product or variety) this input was allocated from.
    request_line = models.ForeignKey(
        "arda_requests.RequestBatchLine", on_delete=models.PROTECT, related_name="allocation_lines", null=True, blank=True,
    )
    group_name = models.CharField(max_length=140)
    item_name = models.CharField(max_length=180)
    unit = models.CharField(max_length=40, blank=True, default="")
    rate_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    cost_per_unit = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    pack_label = models.CharField(max_length=60, blank=True, default="")
    pack_size = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    pack_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    cost_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    required_quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0.0000"))
    calculated_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    included_in_total = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["allocation_id", "id"]

    def __str__(self):
        return f"{self.item_name} ({self.allocation_id})"


class ProgrammeVarietyCap(models.Model):
    """Retired quantity cap. Hectare limits on a lead farmer's submission replaced this.

    The table stays so databases created with the earlier workflow still migrate. New
    allocations do not read or write it, and there is no stock balance behind it.
    """

    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="variety_caps")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="variety_caps")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="variety_caps")
    requirement = models.ForeignKey(
        "programmes.CropInputRequirement", on_delete=models.PROTECT, related_name="variety_caps",
    )
    cap_quantity = models.DecimalField(max_digits=16, decimal_places=4)
    # The catalogue unit this cap is measured in (kg, litres, bags). It is not a stock balance.
    unit = models.CharField(max_length=40)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="variety_caps_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["programme__name", "crop__name", "requirement__input_category", "requirement__item_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["programme", "season", "crop", "requirement"],
                name="unique_programme_variety_cap",
            ),
            models.CheckConstraint(condition=models.Q(cap_quantity__gt=0), name="variety_cap_positive"),
        ]

    def __str__(self):
        return f"{self.programme_id} {self.crop_id} {self.requirement_id}"


class InputSupplyRequest(models.Model):
    """A lead farmer's consolidated input submission for one programme, year, season and crop.

    The lead farmer first submits the hectares they want. Admin then sets the maximum
    hectares that lead farmer may use. The lead farmer distributes those hectares among
    their own farmers and submits that distribution. Only Admin's final approval confirms it.
    """

    STATUS_DRAFT = "DRAFT"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_LIMITS_SET = "LIMITS_SET"
    STATUS_CONFIRMATION = "CONFIRMATION"
    STATUS_APPROVED = "APPROVED"
    STATUS_RETURNED = "RETURNED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_LIMITS_SET, "Hectares approved"),
        (STATUS_CONFIRMATION, "Awaiting confirmation"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_RETURNED, "Returned for corrections"),
        (STATUS_REJECTED, "Rejected"),
    ]
    # A submission is open until Admin confirms it or rejects it. Approved and rejected
    # rows stay as history and do not block a later submission for the same crop.
    OPEN_STATUSES = (
        STATUS_DRAFT, STATUS_SUBMITTED, STATUS_RETURNED, STATUS_LIMITS_SET, STATUS_CONFIRMATION,
    )
    STAGE_REQUEST = "REQUEST"
    STAGE_DISTRIBUTION = "DISTRIBUTION"
    STAGE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STAGE_REQUEST, "Hectare request"),
        (STAGE_DISTRIBUTION, "Farmer distribution"),
    ]

    reference = models.CharField(max_length=40, unique=True, blank=True)
    lead_farmer = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="input_supply_requests",
    )
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="input_supply_requests")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="input_supply_requests")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, related_name="input_supply_requests")
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=STAGE_REQUEST)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="input_supply_reviews",
    )
    decision_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at", "-updated_at", "-id"]
        constraints = [
            # One open submission per lead farmer, programme, agricultural year and crop.
            # The crop's summer or winter category is the season. Approved and rejected
            # submissions stay as history and do not block a later one.
            models.UniqueConstraint(
                fields=["lead_farmer", "programme", "season", "crop"],
                condition=models.Q(status__in=["DRAFT", "SUBMITTED", "RETURNED", "LIMITS_SET", "CONFIRMATION"]),
                name="one_open_input_supply_request",
            ),
        ]

    def __str__(self):
        return self.reference or f"Request {self.pk}"


class InputSupplyFarmer(models.Model):
    """The hectares of one farmer that a request covers. Varieties hang off this row."""

    request = models.ForeignKey(InputSupplyRequest, on_delete=models.CASCADE, related_name="farmers")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="input_supply_rows")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="input_supply_rows")
    hectares = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["farmer__surname", "farmer__first_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["request", "farmer"], name="unique_supply_request_farmer"),
            models.CheckConstraint(condition=models.Q(hectares__gt=0), name="supply_farmer_hectares_positive"),
        ]


class InputSupplyLine(models.Model):
    """One variety allocated to one farmer.

    Hectares are entered for this variety. Quantity and cost are calculated from the
    programme catalogue and stored here so a later price change does not rewrite history.
    """

    farmer_entry = models.ForeignKey(InputSupplyFarmer, on_delete=models.CASCADE, related_name="lines")
    requirement = models.ForeignKey(
        "programmes.CropInputRequirement", on_delete=models.PROTECT, related_name="supply_lines",
    )
    # Unused. Kept so rows written by the retired quantity-cap workflow still load.
    cap = models.ForeignKey(ProgrammeVarietyCap, on_delete=models.PROTECT, related_name="supply_lines", null=True, blank=True)
    hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    rate_per_hectare = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0.0000"))
    unit = models.CharField(max_length=40, blank=True, default="")
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["requirement__input_category", "requirement__item_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["farmer_entry", "requirement"], name="unique_supply_farmer_variety"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="supply_line_quantity_positive"),
        ]


class InputSupplyEvent(models.Model):
    SUBMITTED = "SUBMITTED"
    RESUBMITTED = "RESUBMITTED"
    LIMITS_APPROVED = "LIMITS_APPROVED"
    LIMITS_DISTRIBUTED = "LIMITS_DISTRIBUTED"
    LIMITS_ADJUSTED = "LIMITS_ADJUSTED"
    FINAL_SUBMITTED = "FINAL_SUBMITTED"
    FINAL_RESUBMITTED = "FINAL_RESUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    REVERSED = "REVERSED"
    CORRECTED = "CORRECTED"
    SAVED = "SAVED"
    ACTION_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (SAVED, "Draft saved"),
        (CORRECTED, "Corrections saved"),
        (SUBMITTED, "Submitted"),
        (RESUBMITTED, "Resubmitted"),
        (LIMITS_APPROVED, "Requested hectares approved"),
        (LIMITS_DISTRIBUTED, "Hectares distributed"),
        (LIMITS_ADJUSTED, "Approved hectares adjusted"),
        (FINAL_SUBMITTED, "Final distribution submitted"),
        (FINAL_RESUBMITTED, "Final distribution resubmitted"),
        (APPROVED, "Approved"),
        (REJECTED, "Rejected"),
        (RETURNED, "Returned for corrections"),
        (REVERSED, "Approval reversed"),
    ]

    request = models.ForeignKey(InputSupplyRequest, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="input_supply_events",
    )
    actor_name = models.CharField(max_length=180, blank=True)
    remarks = models.TextField(blank=True)
    # Requested and approved hectares, or the previous and new limits, for this decision.
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class InputSupplyLimit(models.Model):
    """The maximum hectares Admin has allowed one lead farmer to allocate.

    This is not an allocation to an individual farmer and it is not a stock balance.
    The lead farmer decides which of their farmers receive the hectares, up to these maximums.
    A limit can sit on the crop, on one input category, or on one variety.
    """

    SCOPE_CROP = "CROP"
    SCOPE_CATEGORY = "CATEGORY"
    SCOPE_VARIETY = "VARIETY"
    SCOPE_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (SCOPE_CROP, "Crop"),
        (SCOPE_CATEGORY, "Input category"),
        (SCOPE_VARIETY, "Variety"),
    ]

    request = models.ForeignKey(InputSupplyRequest, on_delete=models.CASCADE, related_name="limits")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    input_category = models.CharField(max_length=20, blank=True, default="")
    requirement = models.ForeignKey(
        "programmes.CropInputRequirement", on_delete=models.PROTECT, related_name="supply_limits", null=True, blank=True,
    )
    requested_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    approved_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    updated_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="supply_limits_set",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["request_id", "scope", "input_category", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["request"], condition=models.Q(scope="CROP"), name="unique_supply_crop_limit",
            ),
            models.UniqueConstraint(
                fields=["request", "input_category"], condition=models.Q(scope="CATEGORY"), name="unique_supply_category_limit",
            ),
            models.UniqueConstraint(
                fields=["request", "requirement"], condition=models.Q(scope="VARIETY"), name="unique_supply_variety_limit",
            ),
            models.CheckConstraint(condition=models.Q(approved_hectares__gte=0), name="supply_limit_approved_nonnegative"),
            models.CheckConstraint(condition=models.Q(requested_hectares__gte=0), name="supply_limit_requested_nonnegative"),
        ]

    def __str__(self):
        return f"{self.scope} {self.approved_hectares} ha ({self.request_id})"


class InputSupplyAllocation(models.Model):
    """The official allocation created when Admin approves a request. Reversal cancels it."""

    request = models.ForeignKey(InputSupplyRequest, on_delete=models.PROTECT, related_name="allocations")
    allocation = models.ForeignKey(InputAllocation, on_delete=models.PROTECT, related_name="supply_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "allocation"], name="unique_supply_allocation_link"),
        ]
