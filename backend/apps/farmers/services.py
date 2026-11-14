import re
from datetime import date

from django.db.models import Exists, OuterRef, Q

from apps.geography.models import District, Province, Ward
from apps.subscriptions.models import FarmerSubscription

from .models import Farm, Farmer


class DuplicateCheckService:
    @staticmethod
    def find_possible_duplicates(data):
        queries = []
        if data.get("national_id"):
            queries.append(Q(national_id=data["national_id"]))
        if data.get("phone_primary"):
            queries.append(Q(phone_primary=data["phone_primary"]))
        if data.get("first_name") and data.get("surname"):
            queries.append(
                Q(first_name__iexact=data["first_name"], surname__iexact=data["surname"])
            )
        if not queries:
            return Farmer.objects.none()

        combined = queries[0]
        for query in queries[1:]:
            combined |= query
        return Farmer.objects.filter(combined)


def _lead_name(farmer):
    cluster = getattr(farmer, "cluster", None)
    if cluster is None:
        return ""
    if cluster.lead_member_id and cluster.lead_member_id != farmer.pk:
        return cluster.lead_member.full_name
    if cluster.lead_member_id:
        return cluster.lead_member.full_name
    user = cluster.lead_farmer
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.email


class FarmerRegistrationService:
    @staticmethod
    def validate(data, farmer_id=None):
        errors = {}

        first_name = str(data.get("first_name") or "").strip()
        middle_name = str(data.get("middle_name") or "").strip()
        surname = str(data.get("surname") or "").strip()
        national_id = str(data.get("national_id") or "").strip()
        phone_primary = str(data.get("phone_primary") or "").strip()
        phone_secondary = str(data.get("phone_secondary") or "").strip()
        gender = str(data.get("gender") or "").strip()
        address = str(data.get("address") or "")
        farm_name = str(data.get("farm_name") or "").strip()
        province_id = data.get("province")
        district_id = data.get("district")
        ward_id = data.get("ward")

        name_pattern = re.compile(r"^[^\W\d_]+(?:[ '-][^\W\d_]+)*$", re.UNICODE)
        if not first_name:
            errors["first_name"] = ["First name is required."]
        elif not name_pattern.fullmatch(first_name):
            errors["first_name"] = ["Use letters, spaces, apostrophes, or hyphens only."]
        if not surname:
            errors["surname"] = ["Surname is required."]
        elif not name_pattern.fullmatch(surname):
            errors["surname"] = ["Use letters, spaces, apostrophes, or hyphens only."]
        if middle_name and not name_pattern.fullmatch(middle_name):
            errors["middle_name"] = ["Use letters, spaces, apostrophes, or hyphens only."]
        if not national_id:
            errors["national_id"] = ["National ID is required."]
        elif not re.fullmatch(r"[A-Za-z0-9/-]{5,30}", national_id):
            errors["national_id"] = ["Enter 5-30 letters or digits; hyphens and slashes are allowed."]
        elif Farmer.objects.filter(national_id=national_id).exclude(pk=farmer_id).exists():
            existing = (
                Farmer.objects.filter(national_id=national_id)
                .exclude(pk=farmer_id)
                .select_related("cluster__lead_member", "cluster__lead_farmer")
                .first()
            )
            leader = _lead_name(existing)
            errors["national_id"] = [
                f"This farmer is already registered. {leader} is the lead farmer for this farmer."
                if leader else "This farmer is already registered."
            ]

        if not phone_primary:
            errors["phone_primary"] = ["Phone number is required."]
        elif not re.fullmatch(r"\d{9,12}", phone_primary):
            errors["phone_primary"] = ["Enter 9-12 digits only; letters and symbols are not allowed."]
        if phone_secondary and not re.fullmatch(r"\d{9,12}", phone_secondary):
            errors["phone_secondary"] = ["Enter 9-12 digits only; letters and symbols are not allowed."]

        if gender and gender not in {"MALE", "FEMALE", "OTHER"}:
            errors["gender"] = ["Select Male, Female, or Other."]
        date_of_birth = data.get("date_of_birth")
        if date_of_birth:
            try:
                parsed_date = date.fromisoformat(str(date_of_birth)) if isinstance(date_of_birth, str) else date_of_birth
                if parsed_date > date.today():
                    errors["date_of_birth"] = ["Date of birth cannot be in the future."]
            except (TypeError, ValueError):
                errors["date_of_birth"] = ["Enter a valid date of birth."]
        if len(address) > 500:
            errors["address"] = ["Address must be 500 characters or fewer."]
        if len(farm_name) > 180:
            errors["farm_name"] = ["Farm name must be 180 characters or fewer."]

        if province_id:
            if not Province.objects.filter(pk=province_id).exists():
                errors["province"] = ["Province is invalid."]
        else:
            errors["province"] = ["Province is required."]

        if district_id:
            district = District.objects.filter(pk=district_id).select_related("province").first()
            if district is None:
                errors["district"] = ["District is invalid."]
            elif province_id and str(district.province_id) != str(province_id):
                errors["district"] = ["District does not belong to the selected province."]
        else:
            errors["district"] = ["District is required."]

        if ward_id:
            ward = Ward.objects.filter(pk=ward_id).select_related("district").first()
            if ward is None:
                errors["ward"] = ["Ward is invalid."]
            elif district_id and ward.district_id != int(district_id):
                errors["ward"] = ["Ward does not belong to the selected district."]

        return {"valid": not errors, "errors": errors}


QUALIFYING_SUBSCRIPTION_STATUSES = ("PAID", "PARTIAL", "PARTLY PAID", "PARTIALLY PAID")


def normalize_subscription_status(status):
    return " ".join((status or "").strip().upper().replace("_", " ").split())


def subscription_is_qualifying(status):
    return normalize_subscription_status(status) in QUALIFYING_SUBSCRIPTION_STATUSES


class FarmerApprovalEligibilityService:
    @staticmethod
    def evaluate(farmer, season=None):
        reasons = []

        if farmer.verification_status != Farmer.STATUS_VERIFIED:
            reasons.append("Farmer must be verified before approval.")

        if not farmer.is_active:
            reasons.append("Farmer account must be active.")

        farm_queryset = farmer.farms.all()
        if not farm_queryset.exists():
            reasons.append("At least one farm record is required.")
        elif not farm_queryset.filter(verification_status__in=["VERIFIED", "APPROVED"]).exists():
            reasons.append("Farm verification must be complete before approval.")

        season_name = getattr(season, "name", season)
        subscriptions = FarmerSubscription.objects.filter(farmer=farmer)
        if season_name:
            subscriptions = subscriptions.filter(season__iexact=str(season_name))
        subscription = subscriptions.order_by("-season").first()
        if subscription is None:
            reasons.append("A valid subscription record is required.")
        elif not subscription_is_qualifying(subscription.payment_status):
            reasons.append("Subscription payment is incomplete.")

        return {"eligible": not reasons, "reasons": reasons}

    @staticmethod
    def eligible_queryset(queryset, season=None):
        from apps.farmers.models import Farm

        verified_farms = Farm.objects.filter(
            farmer_id=OuterRef("pk"),
            verification_status__in=["VERIFIED", "APPROVED"],
        )
        return FarmerApprovalEligibilityService._eligible_farmers(
            queryset,
            season,
            farm_exists=Exists(verified_farms),
            farm_flag="has_verified_farm",
        )

    @staticmethod
    def evaluate_for_arda(farmer, season=None):
        reasons = []

        if farmer.verification_status != Farmer.STATUS_VERIFIED:
            reasons.append("Farmer must be verified in the Farmer module.")

        if not farmer.is_active:
            reasons.append("Farmer account must be active.")

        if not farmer.farms.exists():
            reasons.append("At least one farm record is required.")

        season_name = getattr(season, "name", season)
        subscriptions = FarmerSubscription.objects.filter(farmer=farmer)
        if season_name:
            subscriptions = subscriptions.filter(season__iexact=str(season_name))
        subscription = subscriptions.order_by("-season").first()
        if subscription is None:
            reasons.append("A valid subscription record is required.")
        elif not subscription_is_qualifying(subscription.payment_status):
            reasons.append("Subscription payment is incomplete.")

        return {"eligible": not reasons, "reasons": reasons}

    @staticmethod
    def eligible_queryset_for_arda(queryset, season=None):
        registered_farms = Farm.objects.filter(farmer_id=OuterRef("pk"))
        return FarmerApprovalEligibilityService._eligible_farmers(
            queryset,
            season,
            farm_exists=Exists(registered_farms),
            farm_flag="has_registered_farm",
        )

    @staticmethod
    def _eligible_farmers(queryset, season, *, farm_exists, farm_flag):
        from django.db.models import Case, CharField, OuterRef, Subquery, Value, When
        from django.db.models.functions import Replace, Upper

        from apps.subscriptions.models import FarmerSubscription

        subscriptions = FarmerSubscription.objects.filter(farmer_id=OuterRef("pk"))
        season_name = getattr(season, "name", season)
        if season_name:
            subscriptions = subscriptions.filter(season__iexact=str(season_name))
        subscriptions = subscriptions.order_by("-season").values("payment_status")[:1]
        annotated = queryset.annotate(
            **{farm_flag: farm_exists},
            raw_subscription_status=Subquery(subscriptions, output_field=CharField()),
        ).annotate(
            normalized_subscription_status=Upper(
                Replace("raw_subscription_status", Value("_"), Value(" ")),
            ),
        )
        return annotated.annotate(
            subscription_payment_status=Case(
                When(normalized_subscription_status="PAID", then=Value("PAID")),
                When(
                    normalized_subscription_status__in=["PARTIAL", "PARTLY PAID", "PARTIALLY PAID"],
                    then=Value("PARTIALLY_PAID"),
                ),
                default=Value(""),
                output_field=CharField(),
            ),
        ).filter(
            verification_status=Farmer.STATUS_VERIFIED,
            is_active=True,
            **{farm_flag: True},
            normalized_subscription_status__in=QUALIFYING_SUBSCRIPTION_STATUSES,
        )


def open_lead_cluster(farmer):
    """The lead farmer is the cluster. The cluster name is the lead farmer's name."""
    from apps.clusters.models import Cluster

    farmer.is_lead = True
    existing = Cluster.objects.filter(lead_member=farmer, active=True).first()
    if existing is None:
        name = farmer.full_name or f"Lead farmer {farmer.pk}"
        base = name
        suffix = 2
        while Cluster.objects.filter(name=name).exists():
            name = f"{base} ({suffix})"
            suffix += 1
        existing = Cluster.objects.create(
            name=name,
            province=farmer.province,
            district=None,
            lead_member=farmer,
        )
    farmer.cluster = existing
    farmer.save(update_fields=["is_lead", "cluster", "updated_at"])
    return existing


def replace_crop_allocations(farmer, rows):
    """Replace the draft crop list. Hectares in one season cannot pass the farm's arable land."""
    from decimal import Decimal, InvalidOperation

    from apps.programmes.models import Crop, Season

    from .models import RegistrationCropAllocation

    farm = farmer.farms.order_by("id").first()
    limit = Decimal(str(farm.arable_hectares if farm is not None else 0))
    cleaned = []
    seen = set()
    totals = {}
    for index, row in enumerate(rows or []):
        crop = Crop.objects.filter(pk=row.get("crop"), active=True).first()
        season = Season.objects.filter(pk=row.get("season")).first()
        if crop is None or season is None:
            raise ValueError(f"Crop row {index + 1} needs a crop from the catalogue and a season.")
        try:
            hectares = Decimal(str(row.get("hectares")))
        except (InvalidOperation, TypeError):
            raise ValueError(f"Crop row {index + 1} has an invalid hectare value.")
        if hectares <= 0:
            raise ValueError(f"Crop row {index + 1} needs hectares greater than zero.")
        key = (crop.pk, season.pk)
        if key in seen:
            raise ValueError(f"{crop.name} is already allocated for {season.name}.")
        seen.add(key)
        totals[season.pk] = totals.get(season.pk, Decimal("0")) + hectares
        if totals[season.pk] > limit:
            raise ValueError(
                f"Allocated hectares for {season.name} ({totals[season.pk]} ha) exceed the farm's arable hectares ({limit} ha)."
            )
        cleaned.append((crop, season, hectares))
    farmer.crop_allocations.all().delete()
    RegistrationCropAllocation.objects.bulk_create([
        RegistrationCropAllocation(farmer=farmer, crop=crop, season=season, hectares=hectares)
        for crop, season, hectares in cleaned
    ])


def publish_registration_crops(farmer):
    """Copy approved registration crops into seasonal planting and production."""
    from apps.production.models import FarmerProduction, SeasonalPlantingPlan
    from apps.programmes.models import Crop

    farm = farmer.farms.order_by("id").first()
    if farm is None:
        return
    by_season = {}
    for row in farmer.crop_allocations.select_related("crop", "season"):
        FarmerProduction.objects.update_or_create(
            farmer=farmer,
            season=row.season,
            crop=row.crop.name,
            defaults={
                "farm": farm,
                "contracted_hectares": row.hectares,
                "status": FarmerProduction.STATUS_PENDING,
            },
        )
        bucket = by_season.setdefault(row.season_id, {"season": row.season, "summer": None, "winter": None})
        if row.crop.category == Crop.CATEGORY_WINTER:
            if bucket["winter"] is None:
                bucket["winter"] = row
        elif bucket["summer"] is None:
            bucket["summer"] = row
    for bucket in by_season.values():
        summer = bucket["summer"]
        winter = bucket["winter"]
        SeasonalPlantingPlan.objects.update_or_create(
            farmer=farmer,
            farm=farm,
            season=bucket["season"],
            defaults={
                "summer_crop": summer.crop if summer else None,
                "summer_hectares": summer.hectares if summer else 0,
                "winter_crop": winter.crop if winter else None,
                "winter_hectares": winter.hectares if winter else 0,
            },
        )
