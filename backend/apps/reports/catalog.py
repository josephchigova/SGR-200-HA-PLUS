from apps.accounts.models import User

OPERATIONS = "operations"
FINANCE = "finance"
USERS = "users"

READERS = {
    User.ROLE_SUPER_ADMIN,
    User.ROLE_SGR_EXECUTIVE,
    User.ROLE_VERIFICATION_OFFICER,
    User.ROLE_FINANCE_OFFICER,
    User.ROLE_PROGRAMME_OFFICER,
    User.ROLE_RECOVERY_OFFICER,
    User.ROLE_PROVINCIAL_COORDINATOR,
    User.ROLE_DISTRICT_COORDINATOR,
    User.ROLE_LEAD_FARMER,
    User.ROLE_AUDITOR,
    User.ROLE_VIEWER,
}
FINANCE_ROLES = {
    User.ROLE_SUPER_ADMIN,
    User.ROLE_SGR_EXECUTIVE,
    User.ROLE_FINANCE_OFFICER,
    User.ROLE_AUDITOR,
}
USER_ROLES = {
    User.ROLE_SUPER_ADMIN,
    User.ROLE_SGR_EXECUTIVE,
    User.ROLE_AUDITOR,
}
AUDIENCES = {OPERATIONS: READERS, FINANCE: FINANCE_ROLES, USERS: USER_ROLES}

CATEGORIES = [
    ("farmers", "Farmer management"),
    ("verification", "Verification"),
    ("subscriptions", "Subscriptions"),
    ("crops", "Crop catalogue"),
    ("programmes", "Programmes"),
    ("arda", "ARDA requests"),
    ("allocations", "Input allocations"),
    ("production", "Production"),
    ("planting", "Seasonal planting"),
    ("deliveries", "GMB deliveries"),
    ("recovery", "Recovery"),
    ("finance", "Finance"),
    ("users", "Users and activity"),
]

FILTER_LABELS = {
    "start_date": "Start date",
    "end_date": "End date",
    "agricultural_year": "Agricultural year",
    "season": "Season",
    "province": "Province",
    "district": "District",
    "ward": "Ward",
    "cluster": "Cluster",
    "crop": "Crop",
    "programme": "Programme",
    "farmer": "Farmer",
    "membership": "Membership number",
    "status": "Status",
    "payment_status": "Payment status",
    "officer": "Responsible officer",
}

LIMITATIONS = [
    "Asset quantity is not stored. Asset reports list each asset once and do not invent a quantity.",
    "Farmer registration is not stored against an agricultural season. The seasonal farmer report uses production records and subscription participation.",
    "Subscription rows store the agricultural year in a text field. Summer and Winter filtering applies to crop-linked records, not to subscription rows.",
    "Expected recovery tonnes are the current outstanding input debt divided by that delivery's stored price. The same position is not added again for every ticket.",
    "ARDA reports list recorded requests and allocated hectares. They do not calculate a separate approval total.",
    "Income and expenditure come from posted journal lines. Asset-register purchases and disposals are reported separately and are not added to operational expenditure.",
    "There is no system-wide audit log. Activity reports use finance audit events, asset audit events, and modules that store the user who created the record.",
    "PDF uses a standard Latin font, so characters outside that set are replaced. CSV keeps the original text.",
]


class Column:
    def __init__(self, key, label, kind="text", total=False):
        self.key = key
        self.label = label
        self.kind = kind
        self.total = total


def C(key, label, kind="text", total=False):
    return Column(key, label, kind, total)


class ReportSpec:
    def __init__(self, code, category, title, description, audience, orientation, filters, columns, builder, **extra):
        self.code = code
        self.category = category
        self.title = title
        self.description = description
        self.audience = audience
        self.orientation = orientation
        self.filters = tuple(filters)
        self.columns = tuple(columns)
        self.builder = builder
        self.preset = extra.get("preset", {})
        self.mode = extra.get("mode", "")
        self.group_field = extra.get("group_field", "")
        self.gap = extra.get("gap", "")
        self.chart_label = extra.get("chart_label", "")
        self.chart_value = extra.get("chart_value", "")
        self.status_options = extra.get("status_options", [])
        self.date_field = extra.get("date_field", "")
        self.province_field = extra.get("province_field", "")
        self.district_field = extra.get("district_field", "")
        self.ward_field = extra.get("ward_field", "")
        self.cluster_field = extra.get("cluster_field", "")
        self.season_field = extra.get("season_field", "")
        self.season_name_field = extra.get("season_name_field", "")
        self.crop_field = extra.get("crop_field", "")
        self.crop_category_field = extra.get("crop_category_field", "")
        self.programme_field = extra.get("programme_field", "")
        self.farmer_field = extra.get("farmer_field", "-")
        self.membership_field = extra.get("membership_field", "")
        self.status_field = extra.get("status_field", "")
        self.payment_status_field = extra.get("payment_status_field", "")
        self.officer_field = extra.get("officer_field", "")


def _spec(*args, **kwargs):
    return ReportSpec(*args, **kwargs)


FARMER_COLUMNS = [
    C("membership_number", "Membership number"),
    C("first_name", "First name"),
    C("surname", "Surname"),
    C("national_id", "National ID"),
    C("phone_primary", "Phone"),
    C("province_name", "Province"),
    C("district_name", "District"),
    C("ward_name", "Ward"),
    C("cluster_name", "Cluster"),
    C("farm_name", "Farm name"),
    C("total_hectares", "Total hectares", "qty", True),
    C("arable_hectares", "Arable hectares", "qty", True),
    C("verification_status", "Verification status"),
    C("registration_date", "Registration date", "date"),
]
FARMER_GEO = dict(
    date_field="registration_date",
    province_field="province_id",
    district_field="district_id",
    ward_field="ward_id",
    cluster_field="cluster_id",
    farmer_field="",
    membership_field="membership_number",
    status_field="verification_status",
    officer_field="verified_by",
)
FARMER_FILTERS = ("start_date", "end_date", "province", "district", "ward", "cluster", "farmer", "membership", "status", "officer")
VERIFY_OPTIONS = [["VERIFIED", "Verified"], ["APPROVED", "Approved"], ["PENDING", "Pending"], ["REJECTED", "Rejected"], ["DRAFT", "Draft"]]
GROUP_COLUMNS = [C("label", "Group"), C("farmers", "Farmers", "qty", True), C("hectares", "Hectares", "qty", True)]
LINKED = dict(
    province_field="farmer__province_id",
    district_field="farmer__district_id",
    ward_field="farmer__ward_id",
    cluster_field="farmer__cluster_id",
    farmer_field="farmer",
    membership_field="farmer__membership_number",
)


def _reports():
    reports = [
        _spec("farmers-register", "farmers", "Complete farmer register", "Every farmer record, with farm area where a farm is registered.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS, "farmers", status_options=VERIFY_OPTIONS, **FARMER_GEO),
        _spec("farmers-by-province", "farmers", "Farmers by province", "Farmer counts and registered hectares grouped by province.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="province__name", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("farmers-by-district", "farmers", "Farmers by district", "Farmer counts and registered hectares grouped by district.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="district__name", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("farmers-by-ward", "farmers", "Farmers by ward", "Farmer counts and registered hectares grouped by ward.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="ward__name", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("farmers-by-cluster", "farmers", "Farmers by cluster", "Farmer counts and registered hectares grouped by cluster.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="cluster__name", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("farmers-verified", "farmers", "Verified farmers", "Farmers whose verification status is verified or approved.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS, "farmers", preset={"verification_status__in": ["VERIFIED", "APPROVED"]}, **FARMER_GEO),
        _spec("farmers-unverified", "farmers", "Unverified farmers", "Farmers who are not verified or approved.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS, "farmers", mode="unverified", **FARMER_GEO),
        _spec("farmers-active", "farmers", "Active farmers", "Farmers with an active membership.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS, "farmers", preset={"membership_status": "ACTIVE", "is_active": True}, **FARMER_GEO),
        _spec("farmers-inactive", "farmers", "Inactive farmers", "Farmers who are inactive, archived, or marked inactive.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS, "farmers", mode="inactive", **FARMER_GEO),
        _spec("farmers-by-gender", "farmers", "Farmers by gender", "Farmer counts grouped by the gender recorded on the farmer.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="gender", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("farmers-by-season", "farmers", "Farmers by agricultural year and season", "Farmers with production or a subscription in the selected period. Registration itself is not seasonal.", OPERATIONS, "landscape", ("start_date", "end_date", "agricultural_year", "season", "province", "district", "ward", "cluster", "farmer", "membership"), FARMER_COLUMNS, "farmers_by_participation", gap="A farmer with neither a production record nor a subscription is not listed here. Use the complete register for every farmer.", **{**FARMER_GEO, "date_field": "", "season_field": ""}),
        _spec("farmers-by-farm-size", "farmers", "Farmers by farm size and arable hectares", "One row for each registered farm.", OPERATIONS, "landscape", ("province", "district", "ward", "farmer", "membership"), [
            C("farm_name", "Farm name"), C("farmer_name", "Farmer"), C("membership_number", "Membership number"),
            C("province_name", "Province"), C("district_name", "District"), C("ward_name", "Ward"),
            C("total_hectares", "Total hectares", "qty", True), C("arable_hectares", "Arable hectares", "qty", True),
            C("ownership_type", "Ownership"), C("verification_status", "Verification status"),
        ], "farms", province_field="province_id", district_field="district_id", ward_field="ward_id", farmer_field="farmer", membership_field="farmer__membership_number"),
        _spec("farmers-multiple-farms", "farmers", "Farmers with multiple farms", "Farmers who have more than one farm record.", OPERATIONS, "landscape", FARMER_FILTERS, FARMER_COLUMNS + [C("farm_count", "Farms", "qty", True)], "farmers", mode="multiple", **FARMER_GEO),
        _spec("farmers-registration-trends", "farmers", "Farmer registration trends", "Registrations grouped by month.", OPERATIONS, "portrait", ("start_date", "end_date", "province", "district", "ward", "cluster"), [C("label", "Month", "month"), C("farmers", "Farmers", "qty", True)], "farmer_groups", mode="trends", chart_label="label", chart_value="farmers", **FARMER_GEO),
    ]
    verification_columns = FARMER_COLUMNS + [
        C("verification_date", "Verification date", "datetime"),
        C("officer_name", "Officer"),
        C("rejection_reason", "Remarks"),
    ]
    reports += [
        _spec("verification-all", "verification", "All verification records", "Verification position recorded on each farmer.", OPERATIONS, "landscape", FARMER_FILTERS, verification_columns, "farmers", status_options=VERIFY_OPTIONS, **FARMER_GEO),
        _spec("verification-verified", "verification", "Verified farmers", "Farmers verified or approved, with the officer and date where recorded.", OPERATIONS, "landscape", FARMER_FILTERS, verification_columns, "farmers", preset={"verification_status__in": ["VERIFIED", "APPROVED"]}, **FARMER_GEO),
        _spec("verification-pending", "verification", "Pending verification", "Draft, pending, submitted, and under-review farmers.", OPERATIONS, "landscape", FARMER_FILTERS, verification_columns, "farmers", preset={"verification_status__in": ["DRAFT", "PENDING", "SUBMITTED", "UNDER_REVIEW"]}, **FARMER_GEO),
        _spec("verification-rejected", "verification", "Rejected verification", "Farmers whose verification was rejected, including the recorded remark.", OPERATIONS, "landscape", FARMER_FILTERS, verification_columns, "farmers", preset={"verification_status": "REJECTED"}, **FARMER_GEO),
        _spec("verification-by-officer", "verification", "Verification by officer", "Farmer counts grouped by the officer who verified the record.", OPERATIONS, "portrait", FARMER_FILTERS, GROUP_COLUMNS, "farmer_groups", group_field="officer", chart_label="label", chart_value="farmers", **FARMER_GEO),
        _spec("verification-by-location", "verification", "Verification by province and district", "Verification counts by province and district.", OPERATIONS, "portrait", FARMER_FILTERS, [C("province_name", "Province"), C("district_name", "District"), C("farmers", "Farmers", "qty", True)], "verification_locations", chart_label="district_name", chart_value="farmers", **FARMER_GEO),
        _spec("verification-trends", "verification", "Verification trends", "Verified farmers grouped by the month of the verification date.", OPERATIONS, "portrait", ("start_date", "end_date", "province", "district", "officer"), [C("label", "Month", "month"), C("farmers", "Farmers", "qty", True)], "farmer_groups", mode="trends", group_field="officer", chart_label="label", chart_value="farmers", gap="Months use the verification date. Farmers without a verification date are omitted from this trend.", preset={"verification_status__in": ["VERIFIED", "APPROVED"], "verification_date__isnull": False}, **{**FARMER_GEO, "date_field": "verification_date"}),
    ]
    subscription_columns = [
        C("farmer_name", "Farmer"), C("membership_number", "Membership number"), C("province_name", "Province"),
        C("district_name", "District"), C("season", "Agricultural year"), C("expected_amount", "Amount expected", "money", True),
        C("paid_amount", "Amount paid", "money", True), C("outstanding_amount", "Outstanding balance", "money", True),
        C("payment_status", "Payment status"), C("payment_date", "Payment date", "date"),
    ]
    subscription_filters = ("start_date", "end_date", "agricultural_year", "province", "district", "farmer", "membership", "payment_status")
    subscription_scope = dict(
        date_field="payment_date", season_name_field="season", province_field="farmer__province_id",
        district_field="farmer__district_id", cluster_field="farmer__cluster_id", farmer_field="farmer",
        membership_field="farmer__membership_number", payment_status_field="payment_status",
    )
    payment_options = [["PAID", "Fully paid"], ["PARTIAL", "Partially paid"], ["UNPAID", "Unpaid"]]
    reports += [
        _spec("subscriptions-all", "subscriptions", "All subscription records", "Farmer subscription balances stored for each agricultural year.", OPERATIONS, "landscape", subscription_filters, subscription_columns, "subscriptions", status_options=payment_options, **subscription_scope),
        _spec("subscriptions-paid", "subscriptions", "Fully paid subscriptions", "Subscriptions whose stored payment status is paid.", OPERATIONS, "landscape", subscription_filters, subscription_columns, "subscriptions", preset={"payment_status": "PAID"}, **subscription_scope),
        _spec("subscriptions-partial", "subscriptions", "Partially paid subscriptions", "Subscriptions whose stored payment status is partial.", OPERATIONS, "landscape", subscription_filters, subscription_columns, "subscriptions", preset={"payment_status": "PARTIAL"}, **subscription_scope),
        _spec("subscriptions-unpaid", "subscriptions", "Unpaid subscriptions", "Subscriptions whose stored payment status is unpaid.", OPERATIONS, "landscape", subscription_filters, subscription_columns, "subscriptions", preset={"payment_status": "UNPAID"}, **subscription_scope),
        _spec("subscriptions-outstanding", "subscriptions", "Outstanding subscription balances", "Subscriptions that still have an outstanding amount.", OPERATIONS, "landscape", subscription_filters, subscription_columns, "subscriptions", preset={"outstanding_amount__gt": 0}, **subscription_scope),
        _spec("subscriptions-by-location", "subscriptions", "Collections by province and district", "Expected, collected, and outstanding subscription amounts by location.", OPERATIONS, "landscape", subscription_filters, [
            C("province_name", "Province"), C("district_name", "District"), C("subscriptions", "Subscriptions", "qty", True),
            C("expected", "Amount expected", "money", True), C("collected", "Amount paid", "money", True), C("outstanding", "Outstanding balance", "money", True),
        ], "subscription_locations", chart_label="district_name", chart_value="collected", **subscription_scope),
        _spec("subscription-payments", "subscriptions", "Subscription collections and payment history", "Each recorded subscription payment, including the reference and method.", OPERATIONS, "landscape", ("start_date", "end_date", "agricultural_year", "province", "district", "farmer", "membership"), [
            C("farmer_name", "Farmer"), C("membership_number", "Membership number"), C("province_name", "Province"),
            C("district_name", "District"), C("agricultural_year", "Agricultural year"), C("payment_date", "Payment date", "date"),
            C("amount", "Amount paid", "money", True), C("method", "Payment method"), C("reference", "Payment reference"),
            C("payment_status", "Payment status"),
        ], "subscription_payments", date_field="payment_date", season_name_field="subscription__season", province_field="subscription__farmer__province_id", district_field="subscription__farmer__district_id", cluster_field="subscription__farmer__cluster_id", farmer_field="subscription__farmer", membership_field="subscription__farmer__membership_number"),
    ]
    crop_filters = ("season", "crop", "status")
    reports += [
        _spec("crops-configured", "crops", "Configured crops", "Crops configured in the catalogue.", OPERATIONS, "portrait", ("season", "status"), [C("name", "Crop"), C("category", "Season"), C("active", "Active", "bool")], "crops", crop_category_field="category", status_field="active", status_options=[["true", "Active"], ["false", "Inactive"]], gap="The active filter accepts true or false. Crop rows are not tied to an agricultural year."),
        _spec("crop-inputs", "crops", "Crop input requirements", "Input groups, items, rates, and costs configured for each crop.", OPERATIONS, "landscape", ("season", "crop", "status"), [
            C("crop_name", "Crop"), C("crop_category", "Season"), C("group_name", "Input group"), C("item_name", "Item"),
            C("rate_per_hectare", "Rate per hectare", "rate"), C("unit", "Unit"), C("cost_per_unit", "Cost per unit", "money"),
            C("cost_per_hectare", "Cost per hectare", "money", True), C("include_in_input_cost", "Included in input cost", "bool"), C("active", "Active", "bool"),
        ], "crop_requirements", crop_field="crop__name", crop_category_field="crop__category", status_field="active", status_options=[["true", "Active"], ["false", "Inactive"]]),
        _spec("crop-costs", "crops", "Total configured input cost by crop", "Active input requirements that are included in the input cost, totalled per crop.", OPERATIONS, "portrait", ("season",), [
            C("name", "Crop"), C("category", "Season"), C("active", "Active", "bool"), C("inputs", "Inputs", "qty", True),
            C("total_cost_per_hectare", "Total input cost per hectare", "money", True),
        ], "crop_costs", crop_category_field="category"),
    ]
    programme_filters = ("agricultural_year", "season", "crop", "status", "province", "district")
    reports += [
        _spec("programmes-all", "programmes", "All programmes", "Programmes with announced capacity, allocated hectares, and the remaining capacity.", OPERATIONS, "landscape", ("agricultural_year", "season", "crop", "status"), [
            C("name", "Programme"), C("code", "Code"), C("crop", "Crop"), C("season_name", "Agricultural year"),
            C("institution", "Institution"), C("announced_hectares", "Announced hectares", "qty", True),
            C("total_allocated_hectares", "Allocated hectares", "qty", True), C("remaining_hectares", "Remaining hectares", "qty", True),
            C("status", "Status"), C("start_date", "Start date", "date"), C("end_date", "End date", "date"),
        ], "programmes", season_field="season_id", crop_field="crop", status_field="status", status_options=[["DRAFT", "Draft"], ["OPEN", "Open"], ["CLOSED", "Closed"], ["ARCHIVED", "Archived"]]),
        _spec("programmes-by-year", "programmes", "Programmes by agricultural year", "Programme capacity grouped by agricultural year.", OPERATIONS, "portrait", ("agricultural_year", "season", "crop"), [
            C("label", "Agricultural year"), C("programmes", "Programmes", "qty", True),
            C("announced", "Announced hectares", "qty", True), C("allocated", "Allocated hectares", "qty", True),
        ], "programme_groups", season_field="season_id", crop_field="crop", chart_label="label", chart_value="announced"),
        _spec("programme-allocations", "programmes", "Programme allocations and participation", "Inputs allocated to farmers through a programme.", OPERATIONS, "landscape", programme_filters + ("farmer", "membership"), [
            C("allocation_date", "Allocation date", "datetime"), C("programme_name", "Programme"), C("season_name", "Agricultural year"),
            C("crop_name", "Crop"), C("farmer_name", "Farmer"), C("membership_number", "Membership number"),
            C("province_name", "Province"), C("district_name", "District"), C("input_type", "Input"),
            C("quantity", "Quantity", "qty", True), C("unit", "Unit"), C("allocated_by", "Allocated by"),
        ], "programme_allocations", date_field="allocation_date", season_field="programme__season_id", crop_field="programme__crop", programme_field="programme_id", **LINKED),
        _spec("programme-participation", "programmes", "Programme participation", "Distinct farmers and quantities allocated to each programme.", OPERATIONS, "portrait", ("agricultural_year", "season", "crop", "programme"), [
            C("programme_name", "Programme"), C("season_name", "Agricultural year"), C("farmers", "Farmers", "qty", True), C("quantity", "Quantity", "qty", True),
        ], "programme_participation", season_field="programme__season_id", crop_field="programme__crop", programme_field="programme_id", **LINKED, chart_label="programme_name", chart_value="farmers"),
    ]
    arda_filters = ("start_date", "end_date", "agricultural_year", "season", "crop", "programme", "province", "district", "farmer", "membership")
    reports += [
        _spec("arda-requests", "arda", "ARDA requests", "Recorded ARDA request batches, request numbers, and requested hectares. This report does not calculate a separate approval total.", OPERATIONS, "landscape", ("start_date", "end_date", "agricultural_year", "season", "crop", "programme"), [
            C("request_number", "Request number"), C("date_created", "Created", "datetime"), C("programme_name", "Programme"),
            C("season_name", "Agricultural year"), C("crop", "Crop"), C("total_farmers", "Farmers", "qty", True),
            C("total_requested_hectares", "Requested hectares", "qty", True),
        ], "arda_batches", date_field="date_created", season_field="season_id", crop_field="crop", programme_field="programme_id"),
        _spec("arda-farmers", "arda", "Farmers included in ARDA requests", "Farmer-level requested and allocated hectares for each recorded request.", OPERATIONS, "landscape", arda_filters, [
            C("request_number", "Request number"), C("created_at", "Created", "datetime"), C("programme_name", "Programme"),
            C("season_name", "Agricultural year"), C("crop_name", "Crop"), C("farmer_name", "Farmer"),
            C("membership_number", "Membership number"), C("province_name", "Province"), C("district_name", "District"),
            C("farm_name", "Farm"), C("requested_hectares", "Requested hectares", "qty", True),
            C("allocated_hectares", "Allocated hectares", "qty", True),
        ], "arda_lines", date_field="created_at", season_field="request_batch__season_id", crop_field="request_batch__crop", programme_field="request_batch__programme_id", **LINKED),
        _spec("arda-by-crop", "arda", "ARDA requests by crop", "Requested hectares grouped by the crop stored on the request.", OPERATIONS, "portrait", ("agricultural_year", "season", "programme"), [
            C("label", "Crop"), C("requests", "Requests", "qty", True), C("hectares", "Requested hectares", "qty", True),
        ], "arda_groups", group_field="crop", season_field="season_id", programme_field="programme_id", chart_label="label", chart_value="hectares"),
        _spec("arda-by-location", "arda", "ARDA requests by province and district", "Farmer lines in recorded requests, grouped by the farmer's province and district.", OPERATIONS, "landscape", arda_filters, [
            C("province_name", "Province"), C("district_name", "District"), C("requests", "Farmer lines", "qty", True),
            C("hectares", "Requested hectares", "qty", True),
        ], "arda_locations", chart_label="district_name", chart_value="hectares", date_field="created_at", season_field="request_batch__season_id", crop_field="request_batch__crop", programme_field="request_batch__programme_id", **LINKED),
    ]
    return reports


def _more(reports):
    allocation_filters = ("start_date", "end_date", "agricultural_year", "season", "crop", "programme", "province", "district", "farmer", "membership", "status")
    allocation_scope = dict(date_field="allocation_date", season_field="programme__season_id", crop_field="crop", programme_field="programme_id", status_field="status", **LINKED)
    reports += [
        _spec("allocations-all", "allocations", "All input allocations", "Input allocations issued to farmers, including cost and quantity.", OPERATIONS, "landscape", allocation_filters, [
            C("allocation_reference", "Reference"), C("allocation_date", "Date", "date"), C("farmer_name", "Farmer"),
            C("membership_number", "Membership number"), C("province_name", "Province"), C("district_name", "District"),
            C("programme_name", "Programme"), C("season_name", "Agricultural year"), C("crop", "Crop"),
            C("hectares", "Hectares", "qty", True), C("quantity", "Quantity", "qty", True), C("unit", "Unit"),
            C("calculated_input_cost_per_hectare", "Cost per hectare", "money"), C("total_input_cost", "Total cost", "money", True),
            C("status", "Status"),
        ], "allocations", status_options=[["PENDING", "Pending"], ["COLLECTED", "Collected"], ["CANCELLED", "Cancelled"]], **allocation_scope),
        _spec("allocation-lines", "allocations", "Input allocation breakdown", "Every input line issued on an allocation, with quantity, unit, and cost.", OPERATIONS, "landscape", allocation_filters, [
            C("allocation_reference", "Reference"), C("allocation_date", "Date", "date"), C("farmer_name", "Farmer"),
            C("membership_number", "Membership number"), C("crop_name", "Crop"), C("group_name", "Input group"),
            C("item_name", "Item"), C("unit", "Unit"), C("rate_per_hectare", "Rate per hectare", "rate"),
            C("required_quantity", "Quantity", "qty", True), C("cost_per_unit", "Cost per unit", "money"),
            C("cost_per_hectare", "Cost per hectare", "money"), C("calculated_cost", "Cost", "money", True),
        ], "allocation_lines", date_field="allocation__allocation_date", season_field="allocation__programme__season_id", crop_field="allocation__crop", programme_field="allocation__programme_id", province_field="allocation__farmer__province_id", district_field="allocation__farmer__district_id", cluster_field="allocation__farmer__cluster_id", farmer_field="allocation__farmer", membership_field="allocation__farmer__membership_number"),
        _spec("allocations-by-crop", "allocations", "Input allocations by crop", "Allocation cost and hectares grouped by crop.", OPERATIONS, "portrait", ("agricultural_year", "season", "programme", "province", "district"), [
            C("label", "Crop"), C("allocations", "Allocations", "qty", True), C("hectares", "Hectares", "qty", True), C("cost", "Total cost", "money", True),
        ], "allocation_groups", group_field="crop", chart_label="label", chart_value="cost", **allocation_scope),
        _spec("allocations-by-location", "allocations", "Input allocations by province and district", "Allocation cost grouped by the farmer's province and district.", OPERATIONS, "landscape", allocation_filters, [
            C("label", "District"), C("allocations", "Allocations", "qty", True), C("hectares", "Hectares", "qty", True), C("cost", "Total cost", "money", True),
        ], "allocation_groups", group_field="farmer__district__name", chart_label="label", chart_value="cost", **allocation_scope),
    ]
    production_filters = ("start_date", "end_date", "agricultural_year", "season", "crop", "province", "district", "farmer", "membership", "status")
    production_scope = dict(date_field="planting_date", season_field="season_id", crop_field="crop", status_field="status", **LINKED)
    production_columns = [
        C("farmer_name", "Farmer"), C("membership_number", "Membership number"), C("province_name", "Province"),
        C("district_name", "District"), C("season_name", "Agricultural year"), C("crop", "Crop"),
        C("contracted_hectares", "Contracted hectares", "qty", True), C("planted_hectares", "Hectares planted", "qty", True),
        C("planting_date", "Planting date", "date"), C("expected_yield", "Expected yield", "qty", True),
        C("estimated_production", "Expected production", "qty", True), C("actual_production", "Harvested quantity", "qty", True),
        C("yield_per_hectare", "Yield per hectare", "qty3"), C("harvest_date", "Harvest date", "date"), C("status", "Status"),
    ]
    reports += [
        _spec("production-records", "production", "Farmer production records", "Contracted area, planted area, expected production, harvest, and yield per hectare.", OPERATIONS, "landscape", production_filters, production_columns, "production", status_options=[["PENDING", "Pending"], ["PLANTED", "Planted"], ["HARVESTED", "Harvested"], ["COMPLETED", "Completed"]], **production_scope),
        _spec("production-by-crop", "production", "Production by crop", "Planted hectares and harvested quantity grouped by crop.", OPERATIONS, "portrait", production_filters, [
            C("label", "Crop"), C("records", "Records", "qty", True), C("planted", "Hectares planted", "qty", True), C("actual", "Harvested quantity", "qty", True),
        ], "production_groups", group_field="crop", chart_label="label", chart_value="actual", **production_scope),
        _spec("production-by-location", "production", "Production by province and district", "Planted hectares and harvested quantity grouped by district.", OPERATIONS, "portrait", production_filters, [
            C("label", "District"), C("records", "Records", "qty", True), C("planted", "Hectares planted", "qty", True), C("actual", "Harvested quantity", "qty", True),
        ], "production_groups", group_field="farmer__district__name", chart_label="label", chart_value="planted", **production_scope),
        _spec("planting-planted", "planting", "Farmers who planted", "Production records with planted hectares greater than zero.", OPERATIONS, "landscape", production_filters, production_columns, "production", mode="planted", **production_scope),
        _spec("planting-not-planted", "planting", "Farmers who have not planted", "Farmers with no planted-hectare record for the selected year and season.", OPERATIONS, "landscape", ("agricultural_year", "season", "crop", "province", "district", "ward", "cluster", "farmer", "membership"), FARMER_COLUMNS, "planting_missing", gap="A farmer is listed when no production record in the selected period has planted hectares above zero.", **FARMER_GEO),
        _spec("planting-progress", "planting", "Planting progress by district", "Planted hectares grouped by district.", OPERATIONS, "portrait", production_filters, [
            C("label", "District"), C("records", "Records", "qty", True), C("planted", "Hectares planted", "qty", True), C("actual", "Harvested quantity", "qty", True),
        ], "production_groups", group_field="farmer__district__name", mode="planted", chart_label="label", chart_value="planted", **production_scope),
    ]
    delivery_filters = ("start_date", "end_date", "agricultural_year", "season", "crop", "province", "district", "farmer", "membership")
    delivery_scope = dict(date_field="delivery_date", season_field="season_id", crop_field="crop", **LINKED)
    delivery_columns = [
        C("delivery_date", "Delivery date", "date"), C("farmer_name", "Farmer"), C("membership_number", "Membership number"),
        C("province_name", "Province"), C("district_name", "District"), C("season_name", "Agricultural year"), C("crop", "Crop"),
        C("gmb_depot", "GMB depot"), C("delivery_reference", "Delivery reference"), C("ticket_number", "Ticket number"),
        C("tonnes", "Tonnes delivered", "qty", True), C("price", "Price per tonne", "money"), C("value", "Value", "money", True),
        C("recovery_tonnes", "Actual recovery tonnes", "qty", True), C("amount_recovered", "Amount recovered", "money", True),
        C("expected_tonnes", "Expected tonnes to recover", "qty3", True),
    ]
    reports += [
        _spec("deliveries-all", "deliveries", "All GMB deliveries", "Delivered tonnes stay distinct from actual recovery tonnes and from the calculated expected recovery position.", OPERATIONS, "landscape", delivery_filters, delivery_columns, "deliveries", gap="Expected tonnes use the outstanding debt for the same farmer, season, and crop, divided by the price stored on the delivery. Blank means that debt or price is not available. The total counts each farmer, season, and crop once.", **delivery_scope),
        _spec("deliveries-by-depot", "deliveries", "Deliveries by GMB depot", "Delivered and recovered tonnes grouped by depot.", OPERATIONS, "portrait", delivery_filters, [
            C("label", "GMB depot"), C("deliveries", "Deliveries", "qty", True), C("tonnes", "Tonnes delivered", "qty", True),
            C("recovered_tonnes", "Actual recovery tonnes", "qty", True), C("value", "Value", "money", True),
        ], "delivery_groups", group_field="gmb_depot", chart_label="label", chart_value="tonnes", **delivery_scope),
        _spec("deliveries-by-farmer", "deliveries", "Delivery history by farmer", "Delivered and recovered tonnes grouped by farmer.", OPERATIONS, "landscape", delivery_filters, [
            C("label", "Farmer"), C("deliveries", "Deliveries", "qty", True), C("tonnes", "Tonnes delivered", "qty", True),
            C("recovered_tonnes", "Actual recovery tonnes", "qty", True), C("value", "Value", "money", True),
        ], "delivery_groups", group_field="farmer__full_name", chart_label="label", chart_value="tonnes", **delivery_scope),
        _spec("deliveries-by-location", "deliveries", "Deliveries by district and province", "Delivered tonnes grouped by the farmer's district.", OPERATIONS, "portrait", delivery_filters, [
            C("label", "District"), C("deliveries", "Deliveries", "qty", True), C("tonnes", "Tonnes delivered", "qty", True),
            C("recovered_tonnes", "Actual recovery tonnes", "qty", True), C("value", "Value", "money", True),
        ], "delivery_groups", group_field="farmer__district__name", chart_label="label", chart_value="tonnes", **delivery_scope),
    ]
    debt_filters = ("agricultural_year", "season", "crop", "programme", "province", "district", "farmer", "membership", "status")
    debt_scope = dict(
        season_field="programme__season_id", crop_field="crop", programme_field="programme_id", status_field="status",
        province_field="farmer__province_id", district_field="farmer__district_id", cluster_field="farmer__cluster_id",
        farmer_field="farmer", membership_field="farmer__membership_number",
    )
    debt_columns = [
        C("farmer_name", "Farmer"), C("membership_number", "Membership number"), C("province_name", "Province"),
        C("district_name", "District"), C("programme_name", "Programme"), C("season_name", "Agricultural year"), C("crop", "Crop"),
        C("input_value", "Input debt", "money", True), C("amount_recovered", "Amount recovered", "money", True),
        C("outstanding_monetary_balance", "Outstanding balance", "money", True),
        C("required_recovery_tonnes", "Required tonnes", "qty", True), C("recovered_tonnes", "Recovered tonnes", "qty", True),
        C("outstanding_tonnes", "Outstanding tonnes", "qty", True), C("recovery_percentage", "Recovery %", "qty"), C("status", "Status"),
    ]
    debt_status = [["NOT_RECOVERED", "Not recovered"], ["PARTIALLY_RECOVERED", "Partially recovered"], ["FULLY_RECOVERED", "Fully recovered"]]
    reports += [
        _spec("recovery-statement", "recovery", "Farmer debt and recovery statement", "Input debt, recovered amount, and outstanding balance for each farmer and crop.", OPERATIONS, "landscape", debt_filters, debt_columns, "debts", status_options=debt_status, **debt_scope),
        _spec("recovery-outstanding", "recovery", "Farmers with outstanding debts", "Debts whose stored status is not recovered.", OPERATIONS, "landscape", debt_filters, debt_columns, "debts", preset={"status": "NOT_RECOVERED"}, **debt_scope),
        _spec("recovery-partial", "recovery", "Farmers with partially recovered debts", "Debts whose stored status is partially recovered.", OPERATIONS, "landscape", debt_filters, debt_columns, "debts", preset={"status": "PARTIALLY_RECOVERED"}, **debt_scope),
        _spec("recovery-full", "recovery", "Farmers with fully recovered debts", "Debts whose stored status is fully recovered.", OPERATIONS, "landscape", debt_filters, debt_columns, "debts", preset={"status": "FULLY_RECOVERED"}, **debt_scope),
        _spec("recovery-by-crop", "recovery", "Recovery by crop", "Outstanding and recovered amounts grouped by crop.", OPERATIONS, "portrait", debt_filters, [
            C("label", "Crop"), C("debts", "Debts", "qty", True), C("outstanding", "Outstanding balance", "money", True), C("recovered", "Amount recovered", "money", True),
        ], "debt_groups", group_field="crop", chart_label="label", chart_value="outstanding", **debt_scope),
        _spec("recovery-by-location", "recovery", "Recovery by province and district", "Outstanding balances grouped by district.", OPERATIONS, "portrait", debt_filters, [
            C("label", "District"), C("debts", "Debts", "qty", True), C("outstanding", "Outstanding balance", "money", True), C("recovered", "Amount recovered", "money", True),
        ], "debt_groups", group_field="farmer__district__name", chart_label="label", chart_value="outstanding", **debt_scope),
    ]
    return reports


def _finance(reports):
    journal_filters = ("start_date", "end_date", "agricultural_year", "status")
    journal_columns = [
        C("entry_date", "Date", "date"), C("reference", "Reference"), C("description", "Description"),
        C("account_code", "Account"), C("account_name", "Account name"), C("account_type", "Account type"),
        C("account_category", "Category"), C("debit", "Debit", "money", True), C("credit", "Credit", "money", True),
        C("entry_status", "Status"), C("source_module", "Source"), C("season_name", "Agricultural year"),
    ]
    journal_scope = dict(date_field="entry__entry_date", season_field="entry__season_id", status_field="entry__status", status_options=[["DRAFT", "Draft"], ["POSTED", "Posted"], ["REVERSED", "Reversed"]])
    reports += [
        _spec("finance-transactions", "finance", "Financial transaction register", "Journal lines stored in the ledger. Draft, posted, and reversed lines remain distinguishable.", FINANCE, "landscape", journal_filters, journal_columns, "journal_lines", **journal_scope),
        _spec("finance-income", "finance", "Income", "Posted journal lines on revenue accounts. This is not a recalculated cash total.", FINANCE, "landscape", ("start_date", "end_date", "agricultural_year"), journal_columns, "journal_lines", preset={"entry__status": "POSTED", "account__account_type": "REVENUE"}, **journal_scope),
        _spec("finance-expenditure", "finance", "Expenditure", "Posted journal lines on operational expense accounts. Asset purchases recorded on the asset register are not included.", FINANCE, "landscape", ("start_date", "end_date", "agricultural_year"), journal_columns, "journal_lines", preset={"entry__status": "POSTED", "account__account_type": "EXPENSE", "account__category": "EXPENSE"}, **journal_scope),
        _spec("finance-by-category", "finance", "Transactions by category", "Posted debit and credit totals grouped by ledger category.", FINANCE, "portrait", ("start_date", "end_date", "agricultural_year"), [
            C("label", "Category"), C("debit", "Debit", "money", True), C("credit", "Credit", "money", True),
        ], "journal_groups", group_field="category", chart_label="label", chart_value="debit", **journal_scope),
        _spec("finance-position", "finance", "Financial position summary", "Posted debit and credit totals grouped by account type. This reconciles to journal lines and does not invent an opening balance.", FINANCE, "portrait", ("start_date", "end_date", "agricultural_year"), [
            C("label", "Account type"), C("debit", "Debit", "money", True), C("credit", "Credit", "money", True),
        ], "journal_groups", group_field="type", **journal_scope),
        _spec("finance-assets", "finance", "Asset register", "Assets stored on the register. Quantity is not a captured field, so it is not shown.", FINANCE, "landscape", ("start_date", "end_date", "status"), [
            C("asset_id", "Asset ID"), C("name", "Asset name"), C("category_name", "Category"), C("description", "Description"),
            C("purchase_date", "Acquisition date", "date"), C("cost", "Purchase cost", "money", True),
            C("current_value", "Current value", "money", True), C("location", "Location"), C("department", "Department"),
            C("responsible_person", "Responsible person"), C("condition", "Condition"), C("status", "Status"),
        ], "assets", date_field="purchase_date", status_field="status", status_options=[["ACTIVE", "Active"], ["UNDER_MAINTENANCE", "Under maintenance"], ["DISPOSED", "Disposed"], ["WRITTEN_OFF", "Written off"]], gap="Quantity is not stored on an asset. Each row is one asset record."),
        _spec("finance-acquisitions", "finance", "Asset acquisitions", "Assets with a recorded acquisition date and purchase cost.", FINANCE, "landscape", ("start_date", "end_date",), [
            C("asset_id", "Asset ID"), C("name", "Asset name"), C("category_name", "Category"), C("description", "Description"),
            C("purchase_date", "Acquisition date", "date"), C("cost", "Purchase cost", "money", True), C("location", "Location"), C("status", "Status"),
        ], "assets", preset={"purchase_date__isnull": False}, date_field="purchase_date", gap="Assets without an acquisition date stay on the asset register and are omitted here."),
        _spec("finance-disposals", "finance", "Asset disposals", "Disposal and write-off records. These are not reported as operating expenses.", FINANCE, "landscape", ("start_date", "end_date",), [
            C("disposed_on", "Disposal date", "date"), C("asset_code", "Asset ID"), C("asset_name", "Asset name"),
            C("category_name", "Category"), C("kind", "Disposal type"), C("reason", "Reason"), C("proceeds", "Proceeds", "money", True),
        ], "disposals", date_field="disposed_on"),
        _spec("finance-cashbook", "finance", "Cashbook", "Cash, bank, and transfer movements stored in the cashbook.", FINANCE, "landscape", ("start_date", "end_date", "status"), [
            C("movement_date", "Date", "date"), C("account_name", "Account"), C("kind", "Movement"), C("amount", "Amount", "money", True),
            C("counterparty", "Counterparty"), C("reference", "Reference"), C("description", "Description"), C("status", "Status"),
        ], "cashbook", date_field="movement_date", status_field="status", status_options=[["DRAFT", "Draft"], ["POSTED", "Posted"]]),
        _spec("finance-receipts-payments", "finance", "Receipts and payments", "Cashbook receipts and payments. Transfers remain in the cashbook report.", FINANCE, "landscape", ("start_date", "end_date",), [
            C("movement_date", "Date", "date"), C("account_name", "Account"), C("kind", "Movement"), C("amount", "Amount", "money", True),
            C("counterparty", "Counterparty"), C("reference", "Reference"), C("description", "Description"), C("status", "Status"),
        ], "cashbook", mode="receipts", date_field="movement_date"),
        _spec("finance-by-method", "finance", "Transactions by payment method", "Subscription collections, expense claims, and cashbook movements, each with the method stored on that record.", FINANCE, "landscape", ("start_date", "end_date",), [
            C("txn_date", "Date", "date"), C("source", "Source"), C("method", "Payment method"), C("amount", "Amount", "money", True),
            C("party", "Party"), C("reference", "Reference"), C("detail", "Detail"),
        ], "payment_methods"),
        _spec("finance-receivables", "finance", "Outstanding receivables", "Trade and programme receivables that are open or partly settled.", FINANCE, "landscape", ("start_date", "end_date", "status"), [
            C("party", "Party"), C("reference", "Reference"), C("kind", "Kind"), C("issue_date", "Issue date", "date"),
            C("due_date", "Due date", "date"), C("original_amount", "Original amount", "money", True),
            C("amount_received", "Amount received", "money", True), C("outstanding", "Outstanding", "money", True), C("status", "Status"),
        ], "obligations", preset={"status__in": ["OPEN", "PARTIAL"]}, date_field="issue_date", status_field="status"),
        _spec("finance-payables", "finance", "Outstanding payables", "Trade payables that are open or partly settled. Asset and expense classifications stay separate.", FINANCE, "landscape", ("start_date", "end_date", "status"), [
            C("supplier", "Supplier"), C("invoice_number", "Invoice"), C("invoice_date", "Invoice date", "date"),
            C("due_date", "Due date", "date"), C("classification", "Classification"), C("amount", "Amount", "money", True),
            C("amount_paid", "Amount paid", "money", True), C("outstanding", "Outstanding", "money", True), C("status", "Status"),
        ], "obligations", mode="payables", preset={"status__in": ["OPEN", "PARTIAL"]}, date_field="invoice_date", status_field="status"),
    ]
    reports += [
        _spec("users-register", "users", "Registered system users", "User accounts and roles. Passwords and tokens are never included.", USERS, "landscape", ("status",), [
            C("email", "Email"), C("first_name", "First name"), C("last_name", "Surname"), C("role", "Role"),
            C("is_active", "Active", "bool"), C("province_name", "Province"), C("district_name", "District"), C("date_joined", "Joined", "datetime"),
        ], "users", status_field="is_active", status_options=[["true", "Active"], ["false", "Inactive"]]),
        _spec("users-by-role", "users", "Users by role", "Active and total user counts grouped by role.", USERS, "portrait", (), [
            C("role", "Role"), C("users", "Users", "qty", True), C("active", "Active users", "qty", True),
        ], "user_groups", chart_label="role", chart_value="users"),
        _spec("users-active", "users", "Active users", "User accounts that can sign in.", USERS, "landscape", (), [
            C("email", "Email"), C("first_name", "First name"), C("last_name", "Surname"), C("role", "Role"), C("date_joined", "Joined", "datetime"),
        ], "users", preset={"is_active": True}),
        _spec("users-inactive", "users", "Inactive users", "User accounts marked inactive.", USERS, "landscape", (), [
            C("email", "Email"), C("first_name", "First name"), C("last_name", "Surname"), C("role", "Role"), C("date_joined", "Joined", "datetime"),
        ], "users", preset={"is_active": False}),
        _spec("activity-finance", "users", "Finance audit history", "Audit events recorded by the finance module.", USERS, "landscape", ("start_date", "end_date", "officer"), [
            C("created_at", "When", "datetime"), C("action", "Action"), C("actor_email", "User"), C("journal_reference", "Journal"), C("detail", "Detail"),
        ], "finance_audit", date_field="created_at", officer_field="actor"),
        _spec("activity-assets", "users", "Asset audit history", "Audit events recorded against assets.", USERS, "landscape", ("start_date", "end_date", "officer"), [
            C("created_at", "When", "datetime"), C("action", "Action"), C("actor_email", "User"), C("asset_code", "Asset"), C("detail", "Detail"),
        ], "asset_audit", date_field="created_at", officer_field="actor"),
        _spec("activity-records", "users", "Records created by each user", "Counts from modules that store the creating or verifying user. Modules that do not store an author are not guessed.", USERS, "landscape", (), [
            C("email", "User"), C("role", "Role"), C("verified_farmers", "Farmers verified", "qty", True),
            C("arda_batches", "ARDA batches created", "qty", True), C("deliveries", "Deliveries recorded", "qty", True),
            C("journal_entries", "Journal entries created", "qty", True), C("assets", "Assets created", "qty", True),
        ], "records_by_user", gap="This is not a complete audit trail. It counts only records that store the responsible user."),
    ]
    return reports


def all_specs():
    return _finance(_more(_reports()))


def specs_for(user):
    if user.is_superuser:
        return all_specs()
    allowed = []
    for spec in all_specs():
        if user.role in AUDIENCES[spec.audience]:
            allowed.append(spec)
    return allowed


def spec_by_code(code):
    for spec in all_specs():
        if spec.code == code:
            return spec
    return None
