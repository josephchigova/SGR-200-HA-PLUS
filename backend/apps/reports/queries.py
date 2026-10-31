from decimal import Decimal

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Concat, TruncMonth

from apps.accounts.models import User
from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farm, Farmer
from apps.finance.models import (
    Asset,
    AssetAuditEvent,
    AssetDisposal,
    CashMovement,
    ExpenseClaim,
    FinanceAuditEvent,
    JournalLine,
    TradePayable,
    TradeReceivable,
)
from apps.inputs.models import InputAllocation, InputAllocationLine
from apps.production.models import FarmerProduction, GMBDelivery
from apps.programmes.models import Crop, CropInputRequirement, Programme, ProgrammeAllocation, Season
from apps.recovery.models import InputDebt
from apps.recovery.services import RecoveryCalculationService
from apps.subscriptions.models import FarmerSubscription, SubscriptionPayment

MONEY = DecimalField(max_digits=16, decimal_places=2)
QTY = DecimalField(max_digits=16, decimal_places=4)
ZERO = Decimal("0.00")


def scope_queryset(qs, user, province_field, district_field, cluster_field):
    if user.is_superuser or user.role in {
        User.ROLE_SUPER_ADMIN,
        User.ROLE_SGR_EXECUTIVE,
        User.ROLE_AUDITOR,
        User.ROLE_VIEWER,
    }:
        return qs
    if user.role == User.ROLE_DISTRICT_COORDINATOR:
        if not district_field or not user.district_id:
            return qs.none() if district_field else qs
        return qs.filter(**{district_field: user.district_id})
    if user.role == User.ROLE_PROVINCIAL_COORDINATOR:
        if not province_field or not user.province_id:
            return qs.none() if province_field else qs
        return qs.filter(**{province_field: user.province_id})
    if user.role == User.ROLE_LEAD_FARMER:
        if not cluster_field or not user.assigned_cluster_id:
            return qs.none() if cluster_field else qs
        return qs.filter(**{cluster_field: user.assigned_cluster_id})
    return qs


def _year_name(year_id):
    if not year_id:
        return ""
    return Season.objects.filter(pk=year_id).values_list("name", flat=True).first() or ""


def _crop_names(crop_season):
    if not crop_season:
        return None
    return list(Crop.objects.filter(category=crop_season).values_list("name", flat=True))


def apply_common(qs, spec, params):
    qs = scope_queryset(qs, params.user, spec.province_field, spec.district_field, spec.cluster_field)
    if spec.preset:
        qs = qs.filter(**spec.preset)
    include_blank_dates = getattr(spec, "include_blank_dates", False)
    if params.start and spec.date_field:
        lookup = {f"{spec.date_field}__gte": params.start}
        if include_blank_dates:
            qs = qs.filter(Q(**lookup) | Q(**{f"{spec.date_field}__isnull": True}))
        else:
            qs = qs.filter(**lookup)
    if params.end and spec.date_field:
        lookup = {f"{spec.date_field}__lte": params.end}
        if include_blank_dates:
            qs = qs.filter(Q(**lookup) | Q(**{f"{spec.date_field}__isnull": True}))
        else:
            qs = qs.filter(**lookup)
    if params.province_id and spec.province_field:
        qs = qs.filter(**{spec.province_field: params.province_id})
    if params.district_id and spec.district_field:
        qs = qs.filter(**{spec.district_field: params.district_id})
    if params.ward_id and spec.ward_field:
        qs = qs.filter(**{spec.ward_field: params.ward_id})
    if params.cluster_id and spec.cluster_field:
        qs = qs.filter(**{spec.cluster_field: params.cluster_id})
    if params.year_id and spec.season_field:
        qs = qs.filter(**{spec.season_field: params.year_id})
    if params.year_id and spec.season_name_field:
        name = _year_name(params.year_id)
        qs = qs.none() if not name else qs.filter(**{f"{spec.season_name_field}__iexact": name})
    if params.crop_season and spec.crop_category_field:
        qs = qs.filter(**{spec.crop_category_field: params.crop_season})
    if params.crop_season and spec.crop_field:
        qs = qs.filter(**{f"{spec.crop_field}__in": _crop_names(params.crop_season)})
    if params.crop and spec.crop_field:
        qs = qs.filter(**{f"{spec.crop_field}__iexact": params.crop})
    if params.programme_id and spec.programme_field:
        qs = qs.filter(**{spec.programme_field: params.programme_id})
    if params.farmer and spec.farmer_field is not None and spec.farmer_field != "-":
        qs = _filter_farmer(qs, spec.farmer_field, params.farmer)
    if params.membership and spec.membership_field:
        qs = qs.filter(**{f"{spec.membership_field}__iexact": params.membership})
    if params.status and spec.status_field:
        status = params.status
        if str(status).lower() in {"true", "false"}:
            status = str(status).lower() == "true"
        qs = qs.filter(**{spec.status_field: status})
    if params.payment_status and spec.payment_status_field:
        qs = qs.filter(**{spec.payment_status_field: params.payment_status})
    if params.officer and spec.officer_field:
        if str(params.officer).isdigit():
            qs = qs.filter(**{spec.officer_field: int(params.officer)})
        else:
            qs = qs.filter(**{f"{spec.officer_field}__email__iexact": params.officer})
    return qs


def _filter_farmer(qs, field, raw):
    prefix = f"{field}__" if field else ""
    query = Q(**{f"{prefix}membership_number__iexact": raw}) | Q(**{f"{prefix}full_name__icontains": raw})
    if str(raw).isdigit():
        query = query | Q(**{f"{prefix}id" if field else "id": int(raw)})
    return qs.filter(query)


def _group_label(field):
    blank = Q(**{field: ""}) | Q(**{f"{field}__isnull": True})
    return Case(When(blank, then=Value("Not recorded")), default=F(field), output_field=CharField())


def _officer_label():
    full = Concat(
        Coalesce(F("verified_by__first_name"), Value("")),
        Value(" "),
        Coalesce(F("verified_by__last_name"), Value("")),
        output_field=CharField(),
    )
    return Case(
        When(verified_by__isnull=True, then=Value("Not assigned")),
        When(verified_by__first_name="", verified_by__last_name="", then=Value("Not assigned")),
        default=full,
        output_field=CharField(),
    )


def _farmer_queryset(qs):
    first_farm = Farm.objects.filter(farmer=OuterRef("pk")).order_by("farm_name")
    return qs.annotate(
        province_name=Coalesce(F("province__name"), Value("Not recorded")),
        district_name=Coalesce(F("district__name"), Value("Not recorded")),
        ward_name=Coalesce(F("ward__name"), Value("Not recorded")),
        cluster_name=Coalesce(F("cluster__name"), Value("Not recorded")),
        farm_name=Subquery(first_farm.values("farm_name")[:1]),
        total_hectares=Coalesce(Sum("farms__total_hectares", filter=Q(farms__is_active=True)), Value(ZERO), output_field=MONEY),
        arable_hectares=Coalesce(Sum("farms__arable_hectares", filter=Q(farms__is_active=True)), Value(ZERO), output_field=MONEY),
        farm_count=Count("farms", filter=Q(farms__is_active=True), distinct=True),
        officer_name=_officer_label(),
    )


FARMER_FIELDS = [
    "id", "membership_number", "first_name", "surname", "national_id", "phone_primary", "gender",
    "province_name", "district_name", "ward_name", "cluster_name", "farm_name", "total_hectares",
    "arable_hectares", "farm_count", "verification_status", "membership_status", "is_active",
    "registration_date", "verification_date", "officer_name", "rejection_reason",
]


def farmers(spec, params):
    qs = apply_common(Farmer.objects.all(), spec, params)
    if spec.mode == "unverified":
        qs = qs.exclude(verification_status__in=[Farmer.STATUS_VERIFIED, Farmer.STATUS_APPROVED])
    if spec.mode == "inactive":
        qs = qs.filter(Q(membership_status=Farmer.MEMBERSHIP_INACTIVE) | Q(is_active=False) | Q(membership_status=Farmer.MEMBERSHIP_ARCHIVED))
    qs = _farmer_queryset(qs)
    if spec.mode == "multiple":
        qs = qs.filter(farm_count__gt=1)
    return qs.values(*FARMER_FIELDS).order_by("surname", "first_name", "id")


def farmer_groups(spec, params):
    qs = apply_common(Farmer.objects.all(), spec, params)
    if spec.mode == "trends":
        return (
            qs.annotate(label=TruncMonth(spec.date_field or "registration_date"))
            .values("label")
            .annotate(farmers=Count("id"))
            .order_by("label")
        )
    label = _officer_label() if spec.group_field == "officer" else _group_label(spec.group_field)
    return (
        qs.annotate(label=label)
        .values("label")
        .annotate(
            farmers=Count("id", distinct=True),
            hectares=Coalesce(Sum("farms__total_hectares"), Value(ZERO), output_field=MONEY),
        )
        .order_by("label")
    )


def farmers_by_participation(spec, params):
    production = apply_common(FarmerProduction.objects.all(), _production_filter(), params)
    subscriptions = FarmerSubscription.objects.all()
    if params.year_id:
        name = _year_name(params.year_id)
        subscriptions = subscriptions.none() if not name else subscriptions.filter(season__iexact=name)
    if params.start:
        production = production.filter(planting_date__gte=params.start)
        subscriptions = subscriptions.filter(payment_date__gte=params.start)
    if params.end:
        production = production.filter(planting_date__lte=params.end)
        subscriptions = subscriptions.filter(payment_date__lte=params.end)
    ids = set(production.values_list("farmer_id", flat=True)) | set(subscriptions.values_list("farmer_id", flat=True))
    qs = apply_common(Farmer.objects.filter(pk__in=ids), spec, params)
    return _farmer_queryset(qs).values(*FARMER_FIELDS).order_by("surname", "first_name", "id")


def farms(spec, params):
    qs = apply_common(Farm.objects.select_related("farmer", "province", "district", "ward"), spec, params)
    return qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("province__name"), Value("Not recorded")),
        district_name=Coalesce(F("district__name"), Value("Not recorded")),
        ward_name=Coalesce(F("ward__name"), Value("Not recorded")),
    ).values(
        "id", "farm_name", "farmer_name", "membership_number", "province_name", "district_name",
        "ward_name", "total_hectares", "arable_hectares", "ownership_type", "verification_status",
    ).order_by("province_name", "farm_name", "id")


def verification_locations(spec, params):
    qs = apply_common(Farmer.objects.all(), spec, params)
    return qs.values(
        province_name=Coalesce(F("province__name"), Value("Not recorded")),
        district_name=Coalesce(F("district__name"), Value("Not recorded")),
    ).annotate(farmers=Count("id", distinct=True)).order_by("province_name", "district_name")


def _subscription_status_expression(paid_field, expected_field):
    return Case(
        When(**{f"{paid_field}__lte": 0}, then=Value("UNPAID")),
        When(**{f"{paid_field}__gte": F(expected_field)}, then=Value("PAID")),
        default=Value("PARTIAL"),
        output_field=CharField(),
    )


def _apply_subscription_mode(qs, mode, outstanding_field="outstanding_amount"):
    if mode == "UNPAID":
        return qs.filter(report_status="UNPAID")
    if mode == "PARTIAL":
        return qs.filter(report_status="PARTIAL")
    if mode == "PAID":
        return qs.filter(report_status="PAID")
    if mode == "OUTSTANDING":
        return qs.filter(**{f"{outstanding_field}__gt": 0})
    return qs


def _subscription_roster(spec, params, year_name):
    """Classify every farmer in scope for one agricultural year.

    This follows the subscription screen: the expected amount comes from active
    arable hectares, and a farmer with no payment record is unpaid. Geography
    filters are applied to the farmer before that classification.
    """
    from apps.production.seasonal_services import SeasonalSubscriptionService

    money = DecimalField(max_digits=14, decimal_places=2)
    arable = Farm.objects.filter(farmer_id=OuterRef("pk"), is_active=True).values("farmer_id").annotate(
        total=Sum("arable_hectares")
    ).values("total")[:1]
    paid = FarmerSubscription.objects.filter(farmer_id=OuterRef("pk"), season__iexact=year_name).order_by("pk")
    farmers = scope_queryset(Farmer.objects.all(), params.user, "province_id", "district_id", "cluster_id")
    if params.province_id:
        farmers = farmers.filter(province_id=params.province_id)
    if params.district_id:
        farmers = farmers.filter(district_id=params.district_id)
    if params.ward_id:
        farmers = farmers.filter(ward_id=params.ward_id)
    if params.cluster_id:
        farmers = farmers.filter(cluster_id=params.cluster_id)
    if params.membership:
        farmers = farmers.filter(membership_number__iexact=params.membership)
    if params.farmer:
        farmers = _filter_farmer(farmers, "", params.farmer)
    farmers = farmers.annotate(
        paid_amount=Coalesce(Subquery(paid.values("paid_amount")[:1], output_field=money), Value(Decimal("0.00")), output_field=money),
        payment_date=Subquery(paid.values("payment_date")[:1]),
        summary_arable=Coalesce(Subquery(arable, output_field=money), Value(Decimal("0.00")), output_field=money),
    ).annotate(
        expected_amount=Case(
            When(summary_arable__gte=SeasonalSubscriptionService.LARGE_FARM_THRESHOLD, then=Value(SeasonalSubscriptionService.LARGE_FARM_SUBSCRIPTION_AMOUNT)),
            default=Value(SeasonalSubscriptionService.STANDARD_SUBSCRIPTION_AMOUNT),
            output_field=money,
        ),
    ).annotate(
        outstanding_amount=Case(
            When(paid_amount__gte=F("expected_amount"), then=Value(Decimal("0.00"))),
            default=F("expected_amount") - F("paid_amount"),
            output_field=money,
        ),
        report_status=_subscription_status_expression("paid_amount", "expected_amount"),
    )
    if params.start or params.end:
        # A farmer who has never paid has no payment date. Keep that farmer in the
        # status report instead of treating the missing date as "outside the range".
        if params.start and params.end:
            dated = Q(payment_date__isnull=True) | Q(payment_date__gte=params.start, payment_date__lte=params.end)
        elif params.start:
            dated = Q(payment_date__isnull=True) | Q(payment_date__gte=params.start)
        else:
            dated = Q(payment_date__isnull=True) | Q(payment_date__lte=params.end)
        farmers = farmers.filter(dated)
    if params.payment_status:
        farmers = farmers.filter(report_status=params.payment_status)
    farmers = _apply_subscription_mode(farmers, spec.mode)
    return farmers.annotate(
        farmer_name=F("full_name"),
        province_name=Coalesce(F("province__name"), Value("Not recorded")),
        district_name=Coalesce(F("district__name"), Value("Not recorded")),
        season=Value(year_name),
        crop_season=Value("Shared by Summer and Winter"),
        payment_status=F("report_status"),
    ).values(
        "id", "farmer_name", "membership_number", "national_id", "phone_primary", "province_name",
        "district_name", "season", "crop_season", "expected_amount", "paid_amount", "outstanding_amount",
        "payment_status", "payment_date",
    ).order_by("farmer_name", "id")


def _stored_subscriptions(spec, params):
    saved_preset = spec.preset
    saved_status_field = spec.payment_status_field
    spec.preset = {}
    spec.payment_status_field = ""
    try:
        qs = apply_common(FarmerSubscription.objects.select_related("farmer"), spec, params)
    finally:
        spec.preset = saved_preset
        spec.payment_status_field = saved_status_field
    qs = qs.annotate(
        report_status=_subscription_status_expression("paid_amount", "expected_amount"),
    )
    if params.payment_status:
        qs = qs.filter(report_status=params.payment_status)
    qs = _apply_subscription_mode(qs, spec.mode)
    query = qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        national_id=F("farmer__national_id"),
        phone_primary=F("farmer__phone_primary"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
        crop_season=Value("Shared by Summer and Winter"),
        status_label=F("report_status"),
    ).values(
        "id", "farmer_name", "membership_number", "national_id", "phone_primary", "province_name",
        "district_name", "season", "crop_season", "expected_amount", "paid_amount", "outstanding_amount",
        "payment_date", "status_label",
    ).order_by("farmer_name", "season", "id")
    rows = []
    for row in query:
        row["payment_status"] = row.pop("status_label")
        rows.append(row)
    return rows


def subscriptions(spec, params):
    year_name = _year_name(params.year_id) if params.year_id else ""
    if year_name:
        return _subscription_roster(spec, params, year_name)
    return _stored_subscriptions(spec, params)


def subscription_payments(spec, params):
    qs = apply_common(SubscriptionPayment.objects.select_related("subscription__farmer"), spec, params)
    return qs.annotate(
        farmer_name=F("subscription__farmer__full_name"),
        membership_number=F("subscription__farmer__membership_number"),
        province_name=Coalesce(F("subscription__farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("subscription__farmer__district__name"), Value("Not recorded")),
        agricultural_year=F("subscription__season"),
        payment_status=F("subscription__payment_status"),
    ).values(
        "id", "farmer_name", "membership_number", "province_name", "district_name", "agricultural_year",
        "payment_date", "amount", "method", "reference", "payment_status",
    ).order_by("-payment_date", "-id")


def subscription_locations(spec, params):
    qs = apply_common(FarmerSubscription.objects.all(), spec, params)
    return qs.values(
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
    ).annotate(
        subscriptions=Count("id"),
        expected=Coalesce(Sum("expected_amount"), Value(ZERO), output_field=MONEY),
        collected=Coalesce(Sum("paid_amount"), Value(ZERO), output_field=MONEY),
        outstanding=Coalesce(Sum("outstanding_amount"), Value(ZERO), output_field=MONEY),
    ).order_by("province_name", "district_name")


def crops(spec, params):
    return apply_common(Crop.objects.all(), spec, params).values(
        "id", "name", "category", "active",
    ).order_by("category", "name")


def crop_requirements(spec, params):
    qs = apply_common(CropInputRequirement.objects.select_related("crop"), spec, params)
    return qs.annotate(crop_name=F("crop__name"), crop_category=F("crop__category")).values(
        "id", "crop_name", "crop_category", "group_name", "item_name", "rate_per_hectare", "unit",
        "cost_per_unit", "cost_per_hectare", "active", "include_in_input_cost",
    ).order_by("crop_name", "group_name", "item_name", "id")


def crop_costs(spec, params):
    included = Q(input_requirements__active=True, input_requirements__include_in_input_cost=True)
    qs = apply_common(Crop.objects.all(), spec, params)
    return qs.annotate(
        inputs=Count("input_requirements", filter=included, distinct=True),
        total_cost_per_hectare=Coalesce(Sum("input_requirements__cost_per_hectare", filter=included), Value(ZERO), output_field=QTY),
    ).values("id", "name", "category", "active", "inputs", "total_cost_per_hectare").order_by("category", "name")


def programmes(spec, params):
    qs = apply_common(Programme.objects.select_related("season"), spec, params)
    remaining = Case(
        When(announced_hectares__gte=F("total_allocated_hectares"), then=F("announced_hectares") - F("total_allocated_hectares")),
        default=Value(ZERO),
        output_field=MONEY,
    )
    return qs.annotate(season_name=F("season__name"), remaining_hectares=remaining).values(
        "id", "name", "code", "crop", "season_name", "institution", "announced_hectares",
        "total_allocated_hectares", "remaining_hectares", "status", "start_date", "end_date",
    ).order_by("name", "id")


def programme_groups(spec, params):
    qs = apply_common(Programme.objects.all(), spec, params)
    return qs.values(label=Coalesce(F("season__name"), Value("Not recorded"))).annotate(
        programmes=Count("id"),
        announced=Coalesce(Sum("announced_hectares"), Value(ZERO), output_field=MONEY),
        allocated=Coalesce(Sum("total_allocated_hectares"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def programme_allocations(spec, params):
    qs = apply_common(ProgrammeAllocation.objects.select_related("programme", "farmer"), spec, params)
    return qs.annotate(
        programme_name=F("programme__name"),
        season_name=F("programme__season__name"),
        crop_name=F("programme__crop"),
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
    ).values(
        "id", "programme_name", "season_name", "crop_name", "farmer_name", "membership_number",
        "province_name", "district_name", "input_type", "quantity", "unit", "allocation_date", "allocated_by",
    ).order_by("-allocation_date", "-id")


def programme_participation(spec, params):
    qs = apply_common(ProgrammeAllocation.objects.all(), spec, params)
    return qs.values(
        programme_name=F("programme__name"),
        season_name=Coalesce(F("programme__season__name"), Value("Not recorded")),
    ).annotate(
        farmers=Count("farmer", distinct=True),
        quantity=Coalesce(Sum("quantity"), Value(ZERO), output_field=MONEY),
    ).order_by("programme_name")


def arda_batches(spec, params):
    """Use the same requested, allocated, available and farmer figures as the ARDA page.

    The page reads batch.requested_hectares and a live allocation snapshot. The stored
    total_requested_hectares and total_farmers fields are farmer-line rollups and can
    stay at zero when the formal request has hectares but no farmer lines.
    """
    from apps.arda_requests.services import ARDARequestBatchService

    qs = apply_common(ARDARequestBatch.objects.select_related("programme", "season"), spec, params)
    if params.province_id:
        qs = qs.filter(
            Q(farmer_requests__farmer__province_id=params.province_id)
            | Q(programme__input_allocations__farmer__province_id=params.province_id, programme__input_allocations__status__in=["PENDING", "COLLECTED"])
        ).distinct()
    if params.district_id:
        qs = qs.filter(
            Q(farmer_requests__farmer__district_id=params.district_id)
            | Q(programme__input_allocations__farmer__district_id=params.district_id, programme__input_allocations__status__in=["PENDING", "COLLECTED"])
        ).distinct()
    crop_seasons = {name.lower(): category for name, category in Crop.objects.values_list("name", "category")}
    season_labels = {"SUMMER": "Summer", "WINTER": "Winter"}
    rows = []
    for batch in qs.order_by("-date_created", "-id"):
        snapshot = ARDARequestBatchService.batch_snapshot(batch)
        farmer_ids = set(ARDARequestBatchService._allocation_queryset_for_scope(
            programme=batch.programme,
            season=batch.season,
            crop_label=ARDARequestBatchService._normalize_crop(batch.crop),
        ).values_list("farmer_id", flat=True))
        rows.append({
            "id": batch.pk,
            "request_number": batch.request_number,
            "date_created": batch.date_created,
            "programme_name": batch.programme.name if batch.programme_id else "",
            "season_name": batch.season.name if batch.season_id else "",
            "crop_season": season_labels.get(crop_seasons.get((batch.crop or "").lower(), ""), ""),
            "crop": batch.crop,
            "requested_hectares": batch.requested_hectares,
            "allocated_hectares": snapshot["allocated_hectares"],
            "available_hectares": snapshot["available_hectares"],
            "farmer_count": snapshot["unique_farmers"],
            "_farmer_ids": farmer_ids,
        })
    return rows


def arda_lines(spec, params):
    qs = apply_common(ARDAFarmerRequest.objects.select_related("request_batch", "farmer", "farm"), spec, params)
    return qs.annotate(
        request_number=F("request_batch__request_number"),
        programme_name=F("request_batch__programme__name"),
        season_name=F("request_batch__season__name"),
        crop_name=F("request_batch__crop"),
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
        farm_name=F("farm__farm_name"),
        allocated_hectares=F("approved_hectares"),
    ).values(
        "id", "request_number", "programme_name", "season_name", "crop_name", "farmer_name",
        "membership_number", "province_name", "district_name", "farm_name", "requested_hectares",
        "allocated_hectares", "created_at",
    ).order_by("-created_at", "-id")


def arda_locations(spec, params):
    qs = apply_common(ARDAFarmerRequest.objects.all(), spec, params)
    return qs.values(
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
    ).annotate(
        requests=Count("id"),
        hectares=Coalesce(Sum("requested_hectares"), Value(ZERO), output_field=MONEY),
    ).order_by("province_name", "district_name")


def arda_groups(spec, params):
    qs = apply_common(ARDARequestBatch.objects.all(), spec, params)
    label = F("crop") if spec.group_field == "crop" else Coalesce(F(spec.group_field), Value("Not recorded"))
    return qs.annotate(label=label).values("label").annotate(
        requests=Count("id"),
        hectares=Coalesce(Sum("requested_hectares"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def allocations(spec, params):
    qs = apply_common(InputAllocation.objects.select_related("farmer", "programme"), spec, params)
    return qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
        programme_name=F("programme__name"),
        season_name=F("programme__season__name"),
    ).values(
        "id", "allocation_reference", "allocation_date", "farmer_name", "membership_number",
        "province_name", "district_name", "programme_name", "season_name", "crop", "hectares",
        "quantity", "unit", "calculated_input_cost_per_hectare", "total_input_cost", "status",
    ).order_by("-allocation_date", "-id")


def allocation_lines(spec, params):
    qs = apply_common(InputAllocationLine.objects.select_related("allocation__farmer"), spec, params)
    return qs.annotate(
        allocation_reference=F("allocation__allocation_reference"),
        allocation_date=F("allocation__allocation_date"),
        farmer_name=F("allocation__farmer__full_name"),
        membership_number=F("allocation__farmer__membership_number"),
        province_name=Coalesce(F("allocation__farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("allocation__farmer__district__name"), Value("Not recorded")),
        programme_name=F("allocation__programme__name"),
        season_name=F("allocation__programme__season__name"),
        crop_name=F("allocation__crop"),
    ).values(
        "id", "allocation_reference", "allocation_date", "farmer_name", "membership_number",
        "province_name", "district_name", "programme_name", "season_name", "crop_name", "group_name",
        "item_name", "unit", "rate_per_hectare", "required_quantity", "cost_per_unit",
        "cost_per_hectare", "calculated_cost",
    ).order_by("-allocation_date", "group_name", "item_name", "id")


def allocation_groups(spec, params):
    qs = apply_common(InputAllocation.objects.all(), spec, params)
    field = "crop" if spec.group_field == "crop" else spec.group_field
    return qs.annotate(label=Coalesce(F(field), Value("Not recorded"))).values("label").annotate(
        allocations=Count("id"),
        hectares=Coalesce(Sum("hectares"), Value(ZERO), output_field=MONEY),
        cost=Coalesce(Sum("total_input_cost"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def _named_filter(**kwargs):
    data = {
        "preset": {},
        "province_field": "",
        "district_field": "",
        "cluster_field": "",
        "ward_field": "",
        "date_field": "",
        "season_field": "",
        "season_name_field": "",
        "crop_field": "",
        "crop_category_field": "",
        "programme_field": "",
        "farmer_field": "-",
        "membership_field": "",
        "status_field": "",
        "payment_status_field": "",
        "officer_field": "",
    }
    data.update(kwargs)
    return type("Filter", (), data)


def _production_filter():
    return _named_filter(
        province_field="farmer__province_id",
        district_field="farmer__district_id",
        cluster_field="farmer__cluster_id",
        season_field="season_id",
        crop_field="crop",
        date_field="planting_date",
        farmer_field="farmer",
        membership_field="farmer__membership_number",
    )


def production(spec, params):
    qs = apply_common(FarmerProduction.objects.select_related("farmer", "season"), spec, params)
    if spec.mode == "planted":
        qs = qs.filter(planted_hectares__gt=0)
    yield_value = Case(
        When(
            planted_hectares__gt=0,
            then=ExpressionWrapper(F("actual_production") / F("planted_hectares"), output_field=QTY),
        ),
        default=Value(None),
        output_field=QTY,
    )
    return qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
        season_name=F("season__name"),
        yield_per_hectare=yield_value,
    ).values(
        "id", "farmer_name", "membership_number", "province_name", "district_name", "season_name",
        "crop", "contracted_hectares", "planted_hectares", "planting_date", "expected_yield",
        "estimated_production", "actual_production", "harvest_date", "status", "yield_per_hectare",
    ).order_by("-planting_date", "-id")


def production_groups(spec, params):
    qs = apply_common(FarmerProduction.objects.all(), spec, params)
    if spec.mode == "planted":
        qs = qs.filter(planted_hectares__gt=0)
    field = "crop" if spec.group_field == "crop" else spec.group_field
    return qs.annotate(label=Coalesce(F(field), Value("Not recorded"))).values("label").annotate(
        records=Count("id"),
        planted=Coalesce(Sum("planted_hectares"), Value(ZERO), output_field=MONEY),
        actual=Coalesce(Sum("actual_production"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def planting_missing(spec, params):
    planted = apply_common(FarmerProduction.objects.filter(planted_hectares__gt=0), _production_filter(), params)
    qs = apply_common(Farmer.objects.exclude(pk__in=planted.values("farmer_id")), spec, params)
    return _farmer_queryset(qs).values(*FARMER_FIELDS).order_by("surname", "first_name", "id")


def deliveries(spec, params):
    qs = apply_common(GMBDelivery.objects.select_related("farmer", "season"), spec, params)
    return qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("farmer__district__name"), Value("Not recorded")),
        season_name=F("season__name"),
    ).values(
        "id", "farmer_id", "season_id", "farmer_name", "membership_number", "province_name",
        "district_name", "season_name", "crop", "delivery_date", "gmb_depot", "delivery_reference",
        "ticket_number", "tonnes", "price", "value", "recovery_tonnes", "amount_recovered",
    ).order_by("-delivery_date", "-id")


def delivery_groups(spec, params):
    qs = apply_common(GMBDelivery.objects.all(), spec, params)
    field = spec.group_field
    return qs.annotate(label=Coalesce(F(field), Value("Not recorded"))).values("label").annotate(
        deliveries=Count("id"),
        tonnes=Coalesce(Sum("tonnes"), Value(ZERO), output_field=MONEY),
        recovered_tonnes=Coalesce(Sum("recovery_tonnes"), Value(ZERO), output_field=MONEY),
        value=Coalesce(Sum("value"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def debt_index(farmer_ids, season_ids):
    if not farmer_ids:
        return {}
    debts = InputDebt.objects.filter(farmer_id__in=farmer_ids, programme__season_id__in=season_ids).select_related("programme")
    index = {}
    for debt in debts:
        key = (debt.farmer_id, debt.programme.season_id, (debt.crop or "").lower())
        index[key] = index.get(key, Decimal("0.00")) + RecoveryCalculationService.outstanding_money(debt)
    return index


def attach_expected(rows):
    farmer_ids = {row.get("farmer_id") for row in rows if row.get("farmer_id")}
    season_ids = {row.get("season_id") for row in rows if row.get("season_id")}
    index = debt_index(farmer_ids, season_ids)
    for row in rows:
        price = Decimal(str(row.get("price") or 0))
        key = (row.get("farmer_id"), row.get("season_id"), (row.get("crop") or "").lower())
        money = index.get(key)
        if money is None or price <= 0:
            row["expected_tonnes"] = None
        else:
            row["expected_tonnes"] = (money / price).quantize(Decimal("0.001"))
    return rows


def expected_total(qs):
    seen = {}
    farmer_ids = set()
    season_ids = set()
    for row in qs.values("farmer_id", "season_id", "crop", "price").iterator(chunk_size=500):
        key = (row["farmer_id"], row["season_id"], (row["crop"] or "").lower())
        if key in seen:
            continue
        seen[key] = Decimal(str(row["price"] or 0))
        farmer_ids.add(row["farmer_id"])
        season_ids.add(row["season_id"])
    index = debt_index(farmer_ids, season_ids)
    total = Decimal("0.000")
    found = False
    for key, price in seen.items():
        money = index.get(key)
        if money is None or price <= 0:
            continue
        found = True
        total += (money / price).quantize(Decimal("0.001"))
    return total if found else None


def debts(spec, params):
    qs = apply_common(InputDebt.objects.select_related("farmer", "programme"), spec, params)
    return qs.annotate(
        farmer_name=F("farmer__full_name"),
        membership_number=F("farmer__membership_number"),
        province_name=Coalesce(F("province__name"), F("farmer__province__name"), Value("Not recorded")),
        district_name=Coalesce(F("district__name"), F("farmer__district__name"), Value("Not recorded")),
        programme_name=F("programme__name"),
        season_name=F("programme__season__name"),
    ).values(
        "id", "farmer_name", "membership_number", "province_name", "district_name", "programme_name",
        "season_name", "crop", "input_value", "amount_recovered", "outstanding_monetary_balance",
        "required_recovery_tonnes", "recovered_tonnes", "outstanding_tonnes", "recovery_percentage", "status",
    ).order_by("farmer_name", "crop", "id")


def debt_groups(spec, params):
    qs = apply_common(InputDebt.objects.all(), spec, params)
    field = "crop" if spec.group_field == "crop" else spec.group_field
    return qs.annotate(label=Coalesce(F(field), Value("Not recorded"))).values("label").annotate(
        debts=Count("id"),
        outstanding=Coalesce(Sum("outstanding_monetary_balance"), Value(ZERO), output_field=MONEY),
        recovered=Coalesce(Sum("amount_recovered"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def journal_lines(spec, params):
    qs = apply_common(JournalLine.objects.select_related("entry", "account"), spec, params)
    return qs.annotate(
        entry_date=F("entry__entry_date"),
        reference=F("entry__reference"),
        description=F("entry__description"),
        account_code=F("account__code"),
        account_name=F("account__name"),
        account_type=F("account__account_type"),
        account_category=F("account__category"),
        entry_status=F("entry__status"),
        source_module=F("entry__source_module"),
        season_name=F("entry__season__name"),
    ).values(
        "id", "entry_date", "reference", "description", "account_code", "account_name", "account_type",
        "account_category", "debit", "credit", "entry_status", "source_module", "season_name",
    ).order_by("-entry_date", "-id")


def journal_groups(spec, params):
    qs = apply_common(JournalLine.objects.filter(entry__status="POSTED"), spec, params)
    field = "account__category" if spec.group_field == "category" else "account__account_type"
    return qs.values(label=F(field)).annotate(
        debit=Coalesce(Sum("debit"), Value(ZERO), output_field=MONEY),
        credit=Coalesce(Sum("credit"), Value(ZERO), output_field=MONEY),
    ).order_by("label")


def assets(spec, params):
    qs = apply_common(Asset.objects.select_related("category_ref"), spec, params)
    return qs.annotate(category_name=Coalesce(F("category_ref__name"), F("category"), Value(""))).values(
        "id", "asset_id", "name", "category_name", "description", "purchase_date", "cost", "current_value",
        "location", "department", "responsible_person", "condition", "status",
    ).order_by("asset_id")


def disposals(spec, params):
    qs = apply_common(AssetDisposal.objects.select_related("asset"), spec, params)
    return qs.annotate(
        asset_code=F("asset__asset_id"),
        asset_name=Coalesce(F("asset__name"), F("asset__description")),
        category_name=Coalesce(F("asset__category_ref__name"), F("asset__category"), Value("")),
    ).values(
        "id", "asset_code", "asset_name", "category_name", "kind", "disposed_on", "reason", "proceeds",
    ).order_by("-disposed_on", "-id")


def cashbook(spec, params):
    qs = apply_common(CashMovement.objects.select_related("cash_account"), spec, params)
    if spec.mode == "receipts":
        qs = qs.filter(kind__in=[CashMovement.KIND_RECEIPT, CashMovement.KIND_PAYMENT])
    return qs.annotate(account_name=F("cash_account__name")).values(
        "id", "movement_date", "account_name", "kind", "amount", "counterparty", "reference", "description", "status",
    ).order_by("-movement_date", "-id")


def _payment_parts(params):
    cash = CashMovement.objects.all()
    payments = SubscriptionPayment.objects.all()
    claims = ExpenseClaim.objects.all()
    if params.start:
        cash = cash.filter(movement_date__gte=params.start)
        payments = payments.filter(payment_date__gte=params.start)
        claims = claims.filter(expense_date__gte=params.start)
    if params.end:
        cash = cash.filter(movement_date__lte=params.end)
        payments = payments.filter(payment_date__lte=params.end)
        claims = claims.filter(expense_date__lte=params.end)
    cash = cash.annotate(
        txn_date=F("movement_date"),
        source=Value("Cashbook", output_field=CharField()),
        method=F("kind"),
        party=F("counterparty"),
        detail=F("description"),
    ).values("txn_date", "source", "method", "amount", "reference", "party", "detail")
    payments = payments.annotate(
        txn_date=F("payment_date"),
        source=Value("Subscription", output_field=CharField()),
        party=F("subscription__farmer__full_name"),
        detail=Value("Subscription collection", output_field=CharField()),
    ).values("txn_date", "source", "method", "amount", "reference", "party", "detail")
    claims = claims.annotate(
        txn_date=F("expense_date"),
        source=Value("Expense claim", output_field=CharField()),
        party=F("payee"),
        detail=F("description"),
    ).values("txn_date", "source", "method", "amount", "reference", "party", "detail")
    return cash, payments, claims


def payment_methods(spec, params):
    cash, payments, claims = _payment_parts(params)
    return cash.union(payments, claims, all=True).order_by("txn_date")


def payment_method_total(params):
    cash, payments, claims = _payment_parts(params)
    total = Decimal("0.00")
    for part in (cash, payments, claims):
        total += part.aggregate(value=Coalesce(Sum("amount"), Value(ZERO), output_field=MONEY))["value"] or ZERO
    return total


def obligations(spec, params):
    if spec.mode == "payables":
        qs = apply_common(TradePayable.objects.all(), spec, params)
        outstanding = ExpressionWrapper(F("amount") - F("amount_paid"), output_field=MONEY)
        return qs.annotate(outstanding=outstanding).values(
            "id", "supplier", "invoice_number", "invoice_date", "due_date", "classification",
            "amount", "amount_paid", "outstanding", "status",
        ).order_by("due_date", "id")
    qs = apply_common(TradeReceivable.objects.all(), spec, params)
    outstanding = ExpressionWrapper(F("original_amount") - F("amount_received"), output_field=MONEY)
    return qs.annotate(outstanding=outstanding).values(
        "id", "party", "reference", "kind", "issue_date", "due_date", "original_amount",
        "amount_received", "outstanding", "status",
    ).order_by("due_date", "id")


def users(spec, params):
    qs = apply_common(User.objects.select_related("province", "district"), spec, params)
    return qs.annotate(
        province_name=Coalesce(F("province__name"), Value("")),
        district_name=Coalesce(F("district__name"), Value("")),
    ).values(
        "id", "email", "first_name", "last_name", "role", "is_active", "province_name", "district_name", "date_joined",
    ).order_by("email")


def user_groups(spec, params):
    qs = apply_common(User.objects.all(), spec, params)
    return qs.values("role").annotate(users=Count("id"), active=Count("id", filter=Q(is_active=True))).order_by("role")


def finance_audit(spec, params):
    qs = apply_common(FinanceAuditEvent.objects.select_related("actor", "journal"), spec, params)
    return qs.annotate(
        actor_email=F("actor__email"),
        journal_reference=F("journal__reference"),
    ).values("id", "created_at", "action", "actor_email", "journal_reference", "detail").order_by("-created_at", "-id")


def asset_audit(spec, params):
    qs = apply_common(AssetAuditEvent.objects.select_related("actor", "asset"), spec, params)
    return qs.annotate(
        actor_email=F("actor__email"),
        asset_code=F("asset__asset_id"),
    ).values("id", "created_at", "action", "actor_email", "asset_code", "detail").order_by("-created_at", "-id")


def records_by_user(spec, params):
    rows = []
    for person in User.objects.order_by("email"):
        rows.append({
            "email": person.email,
            "role": person.role,
            "verified_farmers": Farmer.objects.filter(verified_by=person).count(),
            "arda_batches": ARDARequestBatch.objects.filter(created_by=person).count(),
            "deliveries": GMBDelivery.objects.filter(recorded_by=person).count(),
            "journal_entries": person.journal_entries_created.count(),
            "assets": person.assets_created.count(),
        })
    return rows


BUILDERS = {
    "farmers": farmers,
    "farmer_groups": farmer_groups,
    "farmers_by_participation": farmers_by_participation,
    "farms": farms,
    "verification_locations": verification_locations,
    "subscriptions": subscriptions,
    "subscription_payments": subscription_payments,
    "subscription_locations": subscription_locations,
    "crops": crops,
    "crop_requirements": crop_requirements,
    "crop_costs": crop_costs,
    "programmes": programmes,
    "programme_groups": programme_groups,
    "programme_allocations": programme_allocations,
    "programme_participation": programme_participation,
    "arda_batches": arda_batches,
    "arda_lines": arda_lines,
    "arda_groups": arda_groups,
    "arda_locations": arda_locations,
    "allocations": allocations,
    "allocation_lines": allocation_lines,
    "allocation_groups": allocation_groups,
    "production": production,
    "production_groups": production_groups,
    "planting_missing": planting_missing,
    "deliveries": deliveries,
    "delivery_groups": delivery_groups,
    "debts": debts,
    "debt_groups": debt_groups,
    "journal_lines": journal_lines,
    "journal_groups": journal_groups,
    "assets": assets,
    "disposals": disposals,
    "cashbook": cashbook,
    "payment_methods": payment_methods,
    "obligations": obligations,
    "users": users,
    "user_groups": user_groups,
    "finance_audit": finance_audit,
    "asset_audit": asset_audit,
    "records_by_user": records_by_user,
}


def build(spec, params):
    return BUILDERS[spec.builder](spec, params)
