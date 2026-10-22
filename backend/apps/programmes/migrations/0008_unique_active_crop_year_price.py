from django.db import migrations, models
from django.db.models import Q


def deactivate_duplicate_active_prices(apps, schema_editor):
    CropSellingPrice = apps.get_model("programmes", "CropSellingPrice")
    seen = set()
    prices = CropSellingPrice.objects.filter(active=True).order_by("crop_id", "season_id", "-id")
    for price in prices:
        key = (price.crop_id, price.season_id)
        if key in seen:
            price.active = False
            price.save(update_fields=["active"])
        else:
            seen.add(key)


class Migration(migrations.Migration):
    dependencies = [
        ("programmes", "0007_remove_sorghum_non_catalogue_rows"),
    ]

    operations = [
        migrations.RunPython(deactivate_duplicate_active_prices, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="cropsellingprice",
            constraint=models.UniqueConstraint(
                fields=["crop", "season"],
                condition=Q(active=True),
                name="unique_active_crop_year_selling_price",
            ),
        ),
    ]
