from datetime import datetime
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_date

from .catalog import FILTER_LABELS, LIMITATIONS, specs_for
from .formatting import format_value
from .pdf import build_pdf
from .queries import attach_expected, build, expected_total, payment_method_total


class ReportParams:
    def __init__(self, user, data):
        self.user = user
        self.start = _date_value(data.get("start_date"))
        self.end = _date_value(data.get("end_date"))
        self.year_id = _int_value(data.get("agricultural_year"))
        self.crop_season = (data.get("season") or "").strip().upper()
        self.province_id = _int_value(data.get("province"))
        self.district_id = _int_value(data.get("district"))
        self.ward_id = _int_value(data.get("ward"))
        self.cluster_id = _int_value(data.get("cluster"))
        self.crop = (data.get("crop") or "").strip()
        self.programme_id = _int_value(data.get("programme"))
        self.farmer = (data.get("farmer") or "").strip()
        self.membership = (data.get("membership") or "").strip()
        self.status = (data.get("status") or "").strip()
        self.payment_status = (data.get("payment_status") or "").strip()
        self.officer = (data.get("officer") or "").strip()
        self.page = max(_int_value(data.get("page")) or 1, 1)
        self.page_size = min(max(_int_value(data.get("page_size")) or 25, 1), 100)

    def described(self):
        labels = {
            "start_date": self.start.isoformat() if self.start else "",
            "end_date": self.end.isoformat() if self.end else "",
            "agricultural_year": _year_label(self.year_id),
            "season": {"SUMMER": "Summer", "WINTER": "Winter"}.get(self.crop_season, self.crop_season),
            "province": str(self.province_id or ""),
            "district": str(self.district_id or ""),
            "ward": str(self.ward_id or ""),
            "cluster": str(self.cluster_id or ""),
            "crop": self.crop,
            "programme": str(self.programme_id or ""),
            "farmer": self.farmer,
            "membership": self.membership,
            "status": self.status,
            "payment_status": self.payment_status,
            "officer": self.officer,
        }
        return [f"{FILTER_LABELS[key]}: {value}" for key, value in labels.items() if value]


def _year_label(year_id):
    if not year_id:
        return ""
    from .queries import _year_name

    return _year_name(year_id) or str(year_id)


def export_filename(spec, params, extension):
    import re

    acronyms = {"ARDA", "GMB", "SGR", "CSV", "PDF"}

    def token(word):
        if word.upper() in acronyms:
            return word.upper()
        return word[:1].upper() + word[1:].lower()

    words = re.sub(r"[^A-Za-z0-9]+", " ", spec.title).split()
    parts = ["SGR", "_".join(token(word) for word in words)]
    year = _year_label(params.year_id).replace("/", "-")
    if year:
        parts.append(year)
    if params.crop_season in {"SUMMER", "WINTER"}:
        parts.append(params.crop_season.title())
    return "_".join(part for part in parts if part) + f".{extension}"


def _date_value(raw):
    if not raw:
        return None
    parsed = parse_date(str(raw))
    if parsed is None:
        raise ValueError(f"{raw} is not a valid date. Use YYYY-MM-DD.")
    return parsed


def _int_value(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("A numeric filter was not a whole number.") from error


def visible_spec(user, code):
    for spec in specs_for(user):
        if spec.code == code:
            return spec
    return None


def _is_sequence(rows):
    return isinstance(rows, list)


def _count(rows):
    return len(rows) if _is_sequence(rows) else rows.count()


def _slice(rows, start, end):
    if _is_sequence(rows):
        return rows[start:end]
    return list(rows[start:end])


def _iterate(rows):
    if _is_sequence(rows):
        yield from rows
        return
    try:
        yield from rows.iterator(chunk_size=400)
    except (NotImplementedError, TypeError):
        yield from rows


def _prepare(spec, rows):
    if not any(column.key == "expected_tonnes" for column in spec.columns):
        return rows if _is_sequence(rows) else list(rows)
    materialized = rows if _is_sequence(rows) else list(rows)
    if materialized and "price" in materialized[0]:
        return attach_expected(materialized)
    return materialized


def _summaries(spec, rows, params):
    summaries = [{"label": "Records", "value": str(_count(rows))}]
    for column in spec.columns:
        if not column.total:
            continue
        if spec.builder == "arda_batches" and column.key == "farmer_count" and _is_sequence(rows):
            farmer_ids = set()
            for row in rows:
                farmer_ids.update(row.get("_farmer_ids") or [])
            amount = len(farmer_ids)
        elif column.key == "expected_tonnes" and not _is_sequence(rows):
            amount = expected_total(rows)
        elif spec.builder == "payment_methods" and column.key == "amount":
            amount = payment_method_total(params)
        elif _is_sequence(rows):
            amount = sum((Decimal(str(row.get(column.key) or 0)) for row in rows), Decimal("0"))
        else:
            from django.db.models import Sum
            amount = rows.aggregate(total=Sum(column.key))["total"]
        summaries.append({"label": f"Total {column.label}", "value": format_value(amount, column.kind)})
    return summaries


def _chart(spec, rows):
    if not spec.chart_label or not spec.chart_value:
        return []
    chart = []
    for row in rows:
        label_kind = next((column.kind for column in spec.columns if column.key == spec.chart_label), "text")
        label = format_value(row.get(spec.chart_label), label_kind) or "Not recorded"
        value = row.get(spec.chart_value) or 0
        chart.append({
            "label": label,
            "value": str(value),
            "display": format_value(value, next(column.kind for column in spec.columns if column.key == spec.chart_value)),
        })
    return chart[:30]


def _public_rows(spec, rows):
    prepared = _prepare(spec, rows)
    return [{column.key: format_value(row.get(column.key), column.kind) for column in spec.columns} for row in prepared]


def preview(spec, params):
    rows = build(spec, params)
    count = _count(rows)
    start = (params.page - 1) * params.page_size
    page_rows = _public_rows(spec, _slice(rows, start, start + params.page_size))
    pages = max((count + params.page_size - 1) // params.page_size, 1)
    return {
        "code": spec.code,
        "title": spec.title,
        "description": spec.description,
        "category": spec.category,
        "orientation": spec.orientation,
        "gap": spec.gap,
        "filters": params.described(),
        "count": count,
        "page": params.page,
        "page_size": params.page_size,
        "pages": pages,
        "columns": [{"key": column.key, "label": column.label, "kind": column.kind} for column in spec.columns],
        "summaries": _report_summaries(spec, rows, params),
        "chart": _chart(spec, _slice(rows, start, start + params.page_size) if not _is_sequence(rows) else rows[:30]),
        "rows": page_rows,
    }


def export_rows(spec, params):
    rows = build(spec, params)
    if any(column.key == "expected_tonnes" for column in spec.columns) and not _is_sequence(rows):
        batch = []
        for row in _iterate(rows):
            batch.append(row)
            if len(batch) >= 400:
                yield from attach_expected(batch)
                batch = []
        if batch:
            yield from attach_expected(batch)
        return
    yield from _iterate(rows)


def csv_rows(spec, params):
    for row in export_rows(spec, params):
        yield row


def render_pdf(spec, params):
    generated = timezone.localdate().isoformat()
    period = "All available records"
    described = params.described()
    if described:
        period = "; ".join(described)
    meta = [
        f"Generated: {generated}",
        f"Reporting period and filters: {period}",
    ]
    if spec.gap:
        meta.append(spec.gap)
    summaries = _report_summaries(spec, build(spec, params), params)
    meta.extend(f"{item['label']}: {item['value']}" for item in summaries)
    table = []
    for row in export_rows(spec, params):
        table.append([format_value(row.get(column.key), column.kind) for column in spec.columns])
    return build_pdf(
        title=spec.title,
        meta_lines=meta,
        headers=[column.label for column in spec.columns],
        rows=table,
        orientation=spec.orientation,
    )


def _report_summaries(spec, rows, params):
    summaries = _summaries(spec, rows, params)
    if spec.builder != "subscriptions" or spec.mode:
        return summaries
    counts = {"UNPAID": 0, "PARTIAL": 0, "PAID": 0}
    if _is_sequence(rows):
        for row in rows:
            status = row.get("payment_status")
            if status in counts:
                counts[status] += 1
    else:
        from django.db.models import Count

        for row in rows.order_by().values("payment_status").annotate(total=Count("id")):
            if row["payment_status"] in counts:
                counts[row["payment_status"]] = row["total"]
    summaries.extend([
        {"label": "Unpaid farmers", "value": str(counts["UNPAID"])},
        {"label": "Partially paid farmers", "value": str(counts["PARTIAL"])},
        {"label": "Fully paid farmers", "value": str(counts["PAID"])},
    ])
    return summaries


def _filter_spec(**kwargs):
    from .queries import _named_filter
    return _named_filter(**kwargs)


def analytics(user, params):
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth

    from apps.arda_requests.models import ARDARequestBatch
    from apps.farmers.models import Farmer
    from apps.finance.models import Asset, JournalLine
    from apps.inputs.models import InputAllocation
    from apps.production.models import FarmerProduction, GMBDelivery
    from apps.recovery.models import InputDebt
    from apps.subscriptions.models import FarmerSubscription

    from .queries import apply_common, scope_queryset

    cards = []
    charts = []
    allowed = {spec.audience for spec in specs_for(user)}
    linked = {"province_field": "farmer__province_id", "district_field": "farmer__district_id", "cluster_field": "farmer__cluster_id"}

    if "operations" in allowed:
        farmers = scope_queryset(Farmer.objects.all(), user, "province_id", "district_id", "cluster_id")
        cards.append({"label": "Registered farmers", "value": str(farmers.count())})
        cards.append({"label": "Verified farmers", "value": str(farmers.filter(verification_status__in=["VERIFIED", "APPROVED"]).count())})
        hectares = farmers.aggregate(total=Sum("farms__total_hectares"))["total"] or 0
        cards.append({"label": "Registered hectares", "value": format_value(hectares, "qty")})
        production = apply_common(FarmerProduction.objects.all(), _filter_spec(**linked, season_field="season_id", crop_field="crop", date_field="planting_date"), params)
        cards.append({"label": "Hectares planted", "value": format_value(production.aggregate(total=Sum("planted_hectares"))["total"] or 0, "qty")})
        allocations = apply_common(InputAllocation.objects.all(), _filter_spec(**linked, season_field="programme__season_id", crop_field="crop"), params)
        cards.append({"label": "Input costs allocated", "value": format_value(allocations.aggregate(total=Sum("total_input_cost"))["total"] or 0, "money")})
        requests = apply_common(ARDARequestBatch.objects.all(), _filter_spec(season_field="season_id", crop_field="crop"), params)
        cards.append({"label": "ARDA hectares requested", "value": format_value(requests.aggregate(total=Sum("requested_hectares"))["total"] or 0, "qty")})
        deliveries = apply_common(GMBDelivery.objects.all(), _filter_spec(**linked, season_field="season_id", crop_field="crop", date_field="delivery_date"), params)
        cards.append({"label": "Tonnes delivered to GMB", "value": format_value(deliveries.aggregate(total=Sum("tonnes"))["total"] or 0, "qty")})
        debts = apply_common(InputDebt.objects.all(), _filter_spec(**linked, season_field="programme__season_id", crop_field="crop"), params)
        cards.append({"label": "Outstanding input debt", "value": format_value(debts.aggregate(total=Sum("outstanding_monetary_balance"))["total"] or 0, "money")})
        cards.append({"label": "Recovered debt", "value": format_value(debts.aggregate(total=Sum("amount_recovered"))["total"] or 0, "money")})
        subscriptions = apply_common(FarmerSubscription.objects.all(), _filter_spec(**linked, season_name_field="season"), params)
        cards.append({"label": "Subscription collections", "value": format_value(subscriptions.aggregate(total=Sum("paid_amount"))["total"] or 0, "money")})

        def chart(title, query, label_key, kind):
            charts.append({
                "title": title,
                "rows": [{
                    "label": row[label_key].strftime("%Y-%m") if hasattr(row[label_key], "strftime") else (row[label_key] or "Not recorded"),
                    "value": str(row["total"] or 0),
                    "display": format_value(row["total"] or 0, kind),
                } for row in query],
            })

        chart("Farmers by province", farmers.values("province__name").annotate(total=Count("id")).order_by("-total")[:12], "province__name", "count")
        chart("Production by crop", production.values("crop").annotate(total=Sum("actual_production")).order_by("-total")[:12], "crop", "qty")
        chart("Planting progress by district", production.values("farmer__district__name").annotate(total=Sum("planted_hectares")).order_by("-total")[:12], "farmer__district__name", "qty")
        chart("Input allocation by crop", allocations.values("crop").annotate(total=Sum("total_input_cost")).order_by("-total")[:12], "crop", "money")
        chart("GMB deliveries over time", deliveries.annotate(month=TruncMonth("delivery_date")).values("month").annotate(total=Sum("tonnes")).order_by("month")[:18], "month", "qty")
        chart("Recovery performance", debts.values("status").annotate(total=Count("id")).order_by("status"), "status", "count")
        chart("Subscription collection performance", subscriptions.values("payment_status").annotate(total=Sum("paid_amount")).order_by("payment_status"), "payment_status", "money")
    if "finance" in allowed:
        assets = Asset.objects.all()
        if params.start:
            assets = assets.filter(purchase_date__gte=params.start)
        if params.end:
            assets = assets.filter(purchase_date__lte=params.end)
        cards.append({"label": "Asset purchase cost", "value": format_value(assets.aggregate(total=Sum("cost"))["total"] or 0, "money")})
        lines = JournalLine.objects.filter(entry__status="POSTED")
        if params.start:
            lines = lines.filter(entry__entry_date__gte=params.start)
        if params.end:
            lines = lines.filter(entry__entry_date__lte=params.end)
        if params.year_id:
            lines = lines.filter(entry__season_id=params.year_id)
        income = lines.filter(account__account_type="REVENUE").aggregate(credit=Sum("credit"), debit=Sum("debit"))
        expense = lines.filter(account__account_type="EXPENSE", account__category="EXPENSE").aggregate(debit=Sum("debit"), credit=Sum("credit"))
        cards.append({"label": "Posted income", "value": format_value((income["credit"] or 0) - (income["debit"] or 0), "money")})
        cards.append({"label": "Posted operational expenditure", "value": format_value((expense["debit"] or 0) - (expense["credit"] or 0), "money")})
    return {"cards": cards, "charts": charts, "limitations": LIMITATIONS, "generated": datetime.now().isoformat(timespec="minutes")}
