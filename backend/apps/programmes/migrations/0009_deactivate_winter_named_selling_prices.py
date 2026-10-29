from django.db import migrations


def deactivate_prices_on_season_named_winter(apps, schema_editor):
    """A Season named winter is not an agricultural year. Deactivate its prices.

    The Season row and any allocations or debts stay in place. Delivery and
    recovery snapshots keep the price they already stored.
    """
    Season = apps.get_model("programmes", "Season")
    CropSellingPrice = apps.get_model("programmes", "CropSellingPrice")
    winter_year_ids = Season.objects.filter(name__iexact="winter").values_list("id", flat=True)
    CropSellingPrice.objects.filter(season_id__in=winter_year_ids, active=True).update(active=False)


class Migration(migrations.Migration):
    dependencies = [
        ("programmes", "0008_unique_active_crop_year_price"),
    ]

    operations = [
        migrations.RunPython(deactivate_prices_on_season_named_winter, migrations.RunPython.noop),
    ]
