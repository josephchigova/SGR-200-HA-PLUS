from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.farmers.models import Farmer
from apps.programmes.models import Programme, Season


class ARDARequestBatch(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"

    # PENDING is a draft: it can still be edited and has not been sent for approval.
    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    request_number = models.CharField(max_length=80, unique=True)
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="request_batches")
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True, related_name="request_batches")
    crop = models.CharField(max_length=80, blank=True)
    # Seed, Fertilizer or Chemicals. Blank on batches made before input types: those cover every input.
    input_category = models.CharField(
        max_length=20, blank=True, default="",
        choices=[("SEED", "Seed"), ("FERTILIZER", "Fertilizer"), ("CHEMICALS", "Chemicals")],
    )
    requested_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    # Only approved hectares can be allocated to farmers. Approval may grant fewer than requested.
    approved_hectares = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True)
    date_created = models.DateTimeField(auto_now_add=True)
    date_submitted = models.DateTimeField(null=True, blank=True)
    total_farmers = models.PositiveIntegerField(default=0)
    total_requested_hectares = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_arda_batches")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_arda_batches")
    submission_reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-date_created"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(approved_hectares__isnull=True) | models.Q(approved_hectares__gt=0),
                name="batch_approved_hectares_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_hectares__isnull=True) | models.Q(approved_hectares__lte=models.F("requested_hectares")),
                name="batch_approved_within_requested",
            ),
        ]

    def __str__(self):
        return self.request_number


class RequestBatchLine(models.Model):
    """One product or variety in an input request, taken from the programme's crop catalogue.

    Only the hectares are stored here. The product, its input type, unit, quantity per hectare
    and price are read from the catalogue line, so they are never typed in twice. For example
    a SEEDCO maize request for 20,000 ha may ask for Mbizi on 8,000 ha and Shumba on 7,000 ha.
    """

    batch = models.ForeignKey(ARDARequestBatch, on_delete=models.CASCADE, related_name="lines")
    requirement = models.ForeignKey("programmes.CropInputRequirement", on_delete=models.PROTECT, related_name="request_lines")
    requested_hectares = models.DecimalField(max_digits=14, decimal_places=2)
    # Set when the request is approved. Only approved hectares can be allocated to farmers.
    approved_hectares = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["batch_id", "requirement__input_category", "requirement__input_product__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "requirement"], name="unique_request_batch_line"),
            models.CheckConstraint(condition=models.Q(requested_hectares__gt=0), name="request_line_requested_positive"),
            models.CheckConstraint(
                condition=models.Q(approved_hectares__isnull=True) | models.Q(approved_hectares__gte=0),
                name="request_line_approved_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(approved_hectares__isnull=True) | models.Q(approved_hectares__lte=models.F("requested_hectares")),
                name="request_line_approved_within_requested",
            ),
        ]

    def __str__(self):
        return f"{self.batch.request_number} - {self.requirement.item_name}"


class ARDARequestNumberSequence(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_number = models.PositiveIntegerField(default=1000)


class ARDAFarmerRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    request_batch = models.ForeignKey(ARDARequestBatch, on_delete=models.CASCADE, related_name="farmer_requests")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="arda_farmer_requests")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, related_name="arda_requests", null=True, blank=True)
    requested_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    approved_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.request_batch.request_number}"


class ARDARequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_IN_PROGRESS, "In Progress"),
    ]

    REQUEST_FERTILIZER = "FERTILIZER"
    REQUEST_SEED = "SEED"
    REQUEST_PESTICIDE = "PESTICIDE"
    REQUEST_SPRAYER = "SPRAYER"
    REQUEST_OTHER = "OTHER"

    REQUEST_TYPE_CHOICES = [
        (REQUEST_FERTILIZER, "Fertilizer"),
        (REQUEST_SEED, "Seed"),
        (REQUEST_PESTICIDE, "Pesticide"),
        (REQUEST_SPRAYER, "Sprayer"),
        (REQUEST_OTHER, "Other"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="arda_requests")
    request_type = models.CharField(max_length=40, choices=REQUEST_TYPE_CHOICES, default=REQUEST_SEED)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=40, default="bags")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.farmer.full_name} - {self.get_request_type_display()}"


class RequestBatchInput(models.Model):
    """One input product in a request batch: how much was requested and how much is allocated.

    Stock belongs to its batch, so the same product in another programme's batch is a
    separate balance. allocated_quantity is only changed by the stock ledger, under a lock.
    """

    batch = models.ForeignKey(ARDARequestBatch, on_delete=models.PROTECT, related_name="inputs")
    input_product = models.ForeignKey("inputs.Input", on_delete=models.PROTECT, related_name="batch_lines")
    input_category = models.CharField(max_length=20, choices=[("SEED", "Seed"), ("FERTILIZER", "Fertilizer"), ("CHEMICALS", "Chemicals")])
    unit = models.CharField(max_length=40, blank=True, default="")
    requested_quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0.0000"))
    allocated_quantity = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0.0000"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["batch_id", "input_category", "input_product__name"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "input_product"], name="unique_batch_input_product"),
            models.CheckConstraint(condition=models.Q(allocated_quantity__gte=0), name="batch_input_allocated_not_negative"),
            models.CheckConstraint(condition=models.Q(allocated_quantity__lte=models.F("requested_quantity")), name="batch_input_within_requested"),
        ]

    @property
    def available_quantity(self):
        return self.requested_quantity - self.allocated_quantity

    def __str__(self):
        return f"{self.batch.request_number} - {self.input_product.name}"


class BatchStockMovement(models.Model):
    """The audit trail of a batch input's balance. Rows are only ever added."""

    KIND_OPENING = "OPENING"
    KIND_ADJUSTMENT = "ADJUSTMENT"
    KIND_ALLOCATION = "ALLOCATION"
    KIND_REVERSAL = "REVERSAL"
    KIND_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (KIND_OPENING, "Quantity requested"),
        (KIND_ADJUSTMENT, "Requested quantity changed"),
        (KIND_ALLOCATION, "Allocated to a farmer"),
        (KIND_REVERSAL, "Allocation reversed"),
    ]

    batch_input = models.ForeignKey(RequestBatchInput, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    # The change to the available balance: positive adds stock, negative takes it away.
    quantity = models.DecimalField(max_digits=16, decimal_places=4)
    available_after = models.DecimalField(max_digits=16, decimal_places=4)
    allocation = models.ForeignKey("inputs.InputAllocation", on_delete=models.PROTECT, related_name="stock_movements", null=True, blank=True)
    allocation_line = models.ForeignKey("inputs.InputAllocationLine", on_delete=models.PROTECT, related_name="stock_movements", null=True, blank=True)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="batch_stock_movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} ({self.batch_input})"


class LeadRequest(models.Model):
    """One consolidated input request from a lead farmer for a programme, year and season."""

    STATUS_DRAFT = "DRAFT"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]
    SEASON_SUMMER = "SUMMER"
    SEASON_WINTER = "WINTER"
    SEASON_CHOICES: ClassVar[list[tuple[str, str]]] = [
        (SEASON_SUMMER, "Summer"),
        (SEASON_WINTER, "Winter"),
    ]

    cluster = models.ForeignKey("clusters.Cluster", on_delete=models.PROTECT, related_name="input_requests")
    programme = models.ForeignKey(Programme, on_delete=models.PROTECT, related_name="lead_requests")
    season = models.ForeignKey(Season, on_delete=models.PROTECT, related_name="lead_requests")
    crop_season = models.CharField(max_length=10, choices=SEASON_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    decision_notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_requests_created",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_requests_submitted",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_requests_decided",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=("cluster", "programme", "season", "crop_season"),
                name="one_lead_request_per_programme_year_season",
            ),
        ]

    def __str__(self):
        return f"{self.cluster} {self.programme} {self.season} {self.get_crop_season_display()}"


class LeadRequestLine(models.Model):
    """One farmer, crop and set of products inside a lead farmer's request."""

    request = models.ForeignKey(LeadRequest, on_delete=models.CASCADE, related_name="lines")
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="lead_request_lines")
    farm = models.ForeignKey("farmers.Farm", on_delete=models.PROTECT, null=True, blank=True, related_name="lead_request_lines")
    crop = models.ForeignKey("programmes.Crop", on_delete=models.PROTECT, related_name="lead_request_lines")
    hectares = models.DecimalField(max_digits=12, decimal_places=2)
    batch = models.ForeignKey(ARDARequestBatch, on_delete=models.PROTECT, related_name="lead_request_lines")
    products = models.ManyToManyField(RequestBatchLine, related_name="lead_request_lines")
    allocation = models.OneToOneField(
        "inputs.InputAllocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="lead_request_line",
    )

    class Meta:
        ordering = ["request_id", "farmer__full_name", "crop__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=("request", "farmer", "crop"), name="one_lead_request_line_per_farmer_crop"),
            models.CheckConstraint(condition=models.Q(hectares__gt=0), name="lead_request_line_hectares_positive"),
        ]

    def __str__(self):
        return f"{self.farmer} {self.crop} {self.hectares} ha"
