from decimal import Decimal

from apps.programmes.models import Crop


class SeasonalPlantingValidationService:
    @staticmethod
    def validate(*, summer_crop, winter_crop, summer_hectares, winter_hectares, farm):
        summer_area = Decimal(str(summer_hectares or 0))
        winter_area = Decimal(str(winter_hectares or 0))
        if summer_area < 0 or winter_area < 0:
            raise ValueError("Planting hectares cannot be negative.")
        if summer_crop is None and summer_area > 0:
            raise ValueError("Select a summer crop or set summer hectares to zero.")
        if winter_crop is None and winter_area > 0:
            raise ValueError("Select a winter crop or set winter hectares to zero.")
        if summer_crop and summer_crop.category != Crop.CATEGORY_SUMMER:
            raise ValueError("Summer planting must use a summer crop.")
        if winter_crop and winter_crop.category != Crop.CATEGORY_WINTER:
            raise ValueError("Winter planting must use a winter crop.")
        if summer_area + winter_area > Decimal(str(farm.arable_hectares)):
            raise ValueError("Combined seasonal hectares cannot exceed the farm's arable hectares.")
        if summer_area == 0 and winter_area == 0:
            raise ValueError("Enter hectares for at least one season.")
        return True


class SeasonalSubscriptionService:
    LARGE_FARM_THRESHOLD = Decimal("200.00")
    STANDARD_SUBSCRIPTION_AMOUNT = Decimal("500.00")
    LARGE_FARM_SUBSCRIPTION_AMOUNT = Decimal("1000.00")

    @staticmethod
    def subscription_amount(total_planted_hectares):
        hectares = Decimal(str(total_planted_hectares))
        if hectares >= SeasonalSubscriptionService.LARGE_FARM_THRESHOLD:
            return SeasonalSubscriptionService.LARGE_FARM_SUBSCRIPTION_AMOUNT
        return SeasonalSubscriptionService.STANDARD_SUBSCRIPTION_AMOUNT
