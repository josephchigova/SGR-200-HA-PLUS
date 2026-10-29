from django.db import migrations


def remove_sorghum_non_catalogue_rows(apps, schema_editor):
    Crop = apps.get_model("programmes", "Crop")
    CropInputRequirement = apps.get_model("programmes", "CropInputRequirement")

    sorghum = Crop.objects.filter(name__iexact="Sorghum").first()
    if sorghum is None:
        return

    CropInputRequirement.objects.filter(
        crop_id=sorghum.pk,
        item_name__in=[
            "Discing",
            "Planting",
            "Spraying and fertilisation (7 times)",
            "Packaging",
            "Transport",
        ],
    ).delete()


def reverse_noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("programmes", "0006_crop_case_insensitive_constraint"),
    ]

    operations = [
        migrations.RunPython(remove_sorghum_non_catalogue_rows, reverse_noop),
    ]
