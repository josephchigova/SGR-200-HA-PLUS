from django.db import migrations


def merge_duplicate_crops(apps, schema_editor):
    Crop = apps.get_model("programmes", "Crop")
    CropInputRequirement = apps.get_model("programmes", "CropInputRequirement")
    CropSellingPrice = apps.get_model("programmes", "CropSellingPrice")
    InputAllocation = apps.get_model("inputs", "InputAllocation")
    SeasonalPlantingPlan = apps.get_model("production", "SeasonalPlantingPlan")

    canonical_lookup = {
        "maize": "Maize",
        "sorghum": "Sorghum",
        "wheat": "Wheat",
    }

    grouped = {}
    for crop in Crop.objects.all().order_by("id"):
        normalized = " ".join((crop.name or "").split()).lower()
        if not normalized:
            continue
        grouped.setdefault(normalized, []).append(crop)

    for normalized, crops in grouped.items():
        target_name = canonical_lookup.get(normalized, " ".join((crops[0].name or "").split()).title())

        canonical = next((item for item in crops if item.name == target_name), crops[0])
        duplicates = [item for item in crops if item.pk != canonical.pk]

        for crop in duplicates:
            for requirement in CropInputRequirement.objects.filter(crop_id=crop.pk):
                existing = CropInputRequirement.objects.filter(
                    crop_id=canonical.pk,
                    group_name=requirement.group_name,
                    item_name=requirement.item_name,
                    cost_type=requirement.cost_type,
                ).first()
                if existing is None:
                    requirement.crop_id = canonical.pk
                    requirement.save(update_fields=["crop", "updated_at"])
                else:
                    if requirement.active and not existing.active:
                        existing.active = True
                        existing.save(update_fields=["active", "updated_at"])
                    requirement.delete()

            CropSellingPrice.objects.filter(crop_id=crop.pk).update(crop_id=canonical.pk)
            InputAllocation.objects.filter(crop_reference_id=crop.pk).update(crop_reference_id=canonical.pk, crop=target_name)
            SeasonalPlantingPlan.objects.filter(summer_crop_id=crop.pk).update(summer_crop_id=canonical.pk)
            SeasonalPlantingPlan.objects.filter(winter_crop_id=crop.pk).update(winter_crop_id=canonical.pk)
            crop.delete()

        if canonical.name != target_name:
            canonical.name = target_name
        if not canonical.active:
            canonical.active = True
        canonical.save(update_fields=["name", "active", "updated_at"])


def reverse_noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("programmes", "0004_cropinputrequirement_cropsellingprice"),
        ("inputs", "0004_inputallocation_calculated_input_cost_per_hectare_and_more"),
        ("production", "0003_seasonalplantingplan"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_crops, reverse_noop),
    ]
