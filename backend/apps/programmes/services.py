from decimal import Decimal

from django.db import transaction

from apps.accounts.models import User

from .models import Crop, CropSellingPrice, Programme, Season


class ProgrammeCapacityService:
    @staticmethod
    def validate_allocation(programme: Programme, requested_hectares: Decimal | str):
        amount = Decimal(str(requested_hectares))
        remaining = programme.remaining_capacity

        if amount <= Decimal("0"):
            return {"valid": False, "error": "Requested hectares must be greater than zero."}
        if amount > remaining:
            return {"valid": False, "error": "Requested hectares exceed the remaining programme capacity."}
        return {"valid": True, "error": None}

    @staticmethod
    @transaction.atomic
    def apply_allocation(programme: Programme, requested_hectares: Decimal | str):
        validation = ProgrammeCapacityService.validate_allocation(programme, requested_hectares)
        if not validation["valid"]:
            return validation

        programme.total_allocated_hectares += Decimal(str(requested_hectares))
        programme.save(update_fields=["total_allocated_hectares", "updated_at"])
        return {"valid": True, "error": None, "remaining_capacity": programme.remaining_capacity}


class RoleAccessService:
    @staticmethod
    def can_access_user(user: User, target_user: User):
        if user.role in {User.ROLE_SUPER_ADMIN, User.ROLE_SGR_EXECUTIVE, User.ROLE_AUDITOR}:
            return True
        if user.pk == target_user.pk:
            return True
        return False


class CropPricingService:
    @staticmethod
    def resolve_price_per_tonne(*, crop: Crop, season: Season | None = None):
        if season is None:
            raise ValueError(f"Select an agricultural year before using the {crop.name} selling price.")
        season_price = CropSellingPrice.objects.filter(
            crop=crop,
            season=season,
            active=True,
        ).order_by("-effective_from", "-id").first()
        if season_price is None:
            raise ValueError(
                f"No selling price is configured for {crop.name} in agricultural year {season.name}."
            )
        return season_price.price_per_tonne
