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
            errors["national_id"] = ["National ID must be unique."]

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
