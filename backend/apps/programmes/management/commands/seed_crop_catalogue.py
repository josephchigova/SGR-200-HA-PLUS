from decimal import Decimal

from django.core.management.base import BaseCommand
from apps.programmes.models import Crop, CropInputRequirement


class Command(BaseCommand):
    help = "Seed crop catalogue with Sorghum and Maize input requirements, and create Wheat scaffold."

    def handle(self, *args, **options):
        source_rows = {
            "Sorghum": {
                "category": Crop.CATEGORY_SUMMER,
                "requirements": [
                    {"group_name": "Seed", "item_name": "SCXH102/NS-5511", "rate_per_hectare": "10.00", "unit": "Kg", "cost_per_unit": "40.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Seed", "item_name": "Seed Safener - Benoxacor", "rate_per_hectare": "0.06", "unit": "Kg", "cost_per_unit": "10.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Fertilisers", "item_name": "Basal fertiliser", "rate_per_hectare": "200.00", "unit": "kg", "cost_per_unit": "128.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Fertilisers", "item_name": "Top Dressing", "rate_per_hectare": "200.00", "unit": "kg", "cost_per_unit": "140.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Pre-emergence Herbicide", "item_name": "Glyphosate (granules)", "rate_per_hectare": "2.00", "unit": "Kg", "cost_per_unit": "12.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Pre-emergence Herbicide", "item_name": "S-Metolachlor", "rate_per_hectare": "1.20", "unit": "L", "cost_per_unit": "12.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Pre-emergence Herbicide", "item_name": "Atrazine", "rate_per_hectare": "2.00", "unit": "L", "cost_per_unit": "8.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Post-emergence Herbicide", "item_name": "Atrazine", "rate_per_hectare": "3.00", "unit": "L", "cost_per_unit": "12.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Post-emergence Herbicide", "item_name": "CP Wetter", "rate_per_hectare": "0.30", "unit": "L", "cost_per_unit": "3.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Insecticides / Fungicides", "item_name": "Elegant Star", "rate_per_hectare": "0.15", "unit": "L", "cost_per_unit": "8.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Insecticides / Fungicides", "item_name": "Dimethoate", "rate_per_hectare": "0.56", "unit": "L", "cost_per_unit": "5.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals - Insecticides / Fungicides", "item_name": "Tebuconazole", "rate_per_hectare": "0.25", "unit": "L", "cost_per_unit": "5.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                ],
            },
            "Maize": {
                "category": Crop.CATEGORY_SUMMER,
                "requirements": [
                    {"group_name": "Seed & Fertilisers", "item_name": "SEED (SC659)", "rate_per_hectare": "25.00", "unit": "kg", "cost_per_unit": "4.50", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Seed & Fertilisers", "item_name": "COMP D", "rate_per_hectare": "6.00", "unit": "kg", "cost_per_unit": "31.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Seed & Fertilisers", "item_name": "AN", "rate_per_hectare": "6.00", "unit": "kg", "cost_per_unit": "36.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals", "item_name": "GLYPHOSATE (GRANULES)", "rate_per_hectare": "3.00", "unit": "kg", "cost_per_unit": "8.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals", "item_name": "ATRAZINE", "rate_per_hectare": "3.00", "unit": "kg", "cost_per_unit": "5.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals", "item_name": "METOLACHLOR", "rate_per_hectare": "2.00", "unit": "kg", "cost_per_unit": "12.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals", "item_name": "MUTSVAIRO/NATO", "rate_per_hectare": "2.00", "unit": "kg", "cost_per_unit": "12.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                    {"group_name": "Chemicals", "item_name": "EMAMECTIN BENZOATE", "rate_per_hectare": "0.50", "unit": "kg", "cost_per_unit": "50.00", "cost_type": CropInputRequirement.COST_TYPE_INPUT, "include_in_input_cost": True},
                ],
            },
            "Wheat": {
                "category": Crop.CATEGORY_WINTER,
                "requirements": [],
            },
        }

        created_crops = 0
        updated_crops = 0
        created_requirements = 0
        updated_requirements = 0

        def upsert_crop(crop_name, category):
            exact_match = Crop.objects.filter(name=crop_name).first()
            if exact_match is not None:
                if exact_match.category != category or not exact_match.active:
                    exact_match.category = category
                    exact_match.active = True
                    exact_match.save(update_fields=["category", "active", "updated_at"])
                Crop.objects.filter(name__iexact=crop_name).exclude(pk=exact_match.pk).update(active=False)
                return exact_match, False

            case_insensitive_matches = Crop.objects.filter(name__iexact=crop_name).order_by("id")
            if case_insensitive_matches.exists():
                keeper = case_insensitive_matches.first()
                if keeper.category != category or not keeper.active:
                    keeper.category = category
                    keeper.active = True
                    keeper.save(update_fields=["category", "active", "updated_at"])
                case_insensitive_matches.exclude(pk=keeper.pk).update(active=False)
                return keeper, False

            return Crop.objects.create(name=crop_name, category=category, active=True), True

        for crop_name, crop_data in source_rows.items():
            crop, created = upsert_crop(crop_name, crop_data["category"])
            if created:
                created_crops += 1
                self.stdout.write(self.style.SUCCESS(f"Created crop: {crop.name}"))
            else:
                updated_crops += 1
                self.stdout.write(f"Updated crop: {crop.name}")

            if not crop_data["requirements"]:
                self.stdout.write(f"No input data supplied for {crop.name}; skipped input creation.")
                continue

            for row in crop_data["requirements"]:
                rate = Decimal(str(row["rate_per_hectare"]))
                cost_per_unit = Decimal(str(row["cost_per_unit"])) if row.get("cost_per_unit") is not None else None
                if cost_per_unit is not None:
                    cost_per_hectare = (rate * cost_per_unit).quantize(Decimal("0.0001"))
                else:
                    cost_per_hectare = Decimal(str(row.get("cost_per_hectare", "0.00")))

                requirement, row_created = CropInputRequirement.objects.update_or_create(
                    crop=crop,
                    group_name=row["group_name"],
                    item_name=row["item_name"],
                    cost_type=row.get("cost_type", CropInputRequirement.COST_TYPE_INPUT),
                    defaults={
                        "rate_per_hectare": rate,
                        "unit": row.get("unit", ""),
                        "cost_per_unit": cost_per_unit,
                        "cost_per_hectare": cost_per_hectare,
                        "include_in_input_cost": row.get("include_in_input_cost", True),
                        "active": True,
                    },
                )
                if row_created:
                    created_requirements += 1
                    self.stdout.write(self.style.SUCCESS(f"Created input: {requirement.item_name}"))
                else:
                    updated_requirements += 1
                    self.stdout.write(f"Updated input: {requirement.item_name}")

            if crop.name == "Sorghum":
                CropInputRequirement.objects.filter(
                    crop=crop,
                    item_name__in=[
                        "Discing",
                        "Planting",
                        "Spraying and fertilisation (7 times)",
                        "Packaging",
                        "Transport",
                    ],
                ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                "Crop catalogue seed complete: "
                f"crops created={created_crops}, crops updated={updated_crops}, "
                f"inputs created={created_requirements}, inputs updated={updated_requirements}."
            )
        )
