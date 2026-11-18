"""Give each farmer row and hectare limit of an earlier one-crop submission its crop.

Earlier submissions named one crop on the submission. Rows and limits now carry their own
crop, so a submission can cover every crop of a season. Nothing is deleted.
"""

from django.db import migrations


def copy_crop(apps, schema_editor):
    Farmer = apps.get_model("inputs", "InputSupplyFarmer")
    Limit = apps.get_model("inputs", "InputSupplyLimit")
    for row in Farmer.objects.filter(crop__isnull=True, request__crop__isnull=False).select_related("request"):
        row.crop_id = row.request.crop_id
        row.save(update_fields=["crop"])
    for limit in Limit.objects.filter(crop__isnull=True).select_related("request", "requirement"):
        crop_id = limit.requirement.crop_id if limit.requirement_id else limit.request.crop_id
        if crop_id:
            limit.crop_id = crop_id
            limit.save(update_fields=["crop"])


class Migration(migrations.Migration):
    dependencies = [("inputs", "0011_season_submissions")]

    operations = [migrations.RunPython(copy_crop, migrations.RunPython.noop)]
