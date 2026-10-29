from decimal import Decimal

from apps.arda_requests.models import ARDAFarmerRequest, ARDARequestBatch
from apps.farmers.models import Farm


class FarmerProductionService:
    @staticmethod
    def validate(production):
        farm = production.get("farm")
        farmer = production.get("farmer")
        if farm is None and farmer is not None:
            farm = Farm.objects.filter(farmer=farmer).first()
            production["farm"] = farm
        if farm is None or farmer is None or farm.farmer_id != farmer.pk:
            raise ValueError("Select a farm belonging to this farmer.")

        contracted = Decimal(str(production.get("contracted_hectares", 0)))
        planted = Decimal(str(production.get("planted_hectares", 0)))
        if contracted <= 0 or planted < 0:
            raise ValueError("Contracted hectares must be positive and planted hectares cannot be negative.")
        if planted > contracted:
            raise ValueError("Planted hectares cannot exceed contracted hectares.")
        if contracted > farm.arable_hectares:
            raise ValueError("Contracted hectares exceed the farm's arable hectares.")

        batch_statuses = [ARDARequestBatch.STATUS_PENDING, ARDARequestBatch.STATUS_SUBMITTED, ARDARequestBatch.STATUS_APPROVED]
        approved_hectares = sum(
            ARDAFarmerRequest.objects.filter(
                farmer=farmer,
                farm=farm,
                request_batch__season=production.get("season"),
                request_batch__status__in=batch_statuses,
                status=ARDAFarmerRequest.STATUS_APPROVED,
            ).values_list("approved_hectares", flat=True),
            Decimal("0.00"),
        )
        if contracted > approved_hectares:
            raise ValueError("Contracted hectares exceed approved ARDA hectares for this season.")
        return production
