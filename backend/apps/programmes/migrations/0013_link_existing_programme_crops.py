"""Link each programme to the crops it already works with.

Only clear links are made: the crop named on the programme, crops in the programme's own
catalogue lines, and crops of its input requests. Catalogue lines with no programme are not
assigned to any programme here; they are left for an administrator to assign.
"""

from django.db import migrations


def link_crops(apps, schema_editor):
    Programme = apps.get_model("programmes", "Programme")
    Crop = apps.get_model("programmes", "Crop")
    ProgrammeCrop = apps.get_model("programmes", "ProgrammeCrop")
    CropInputRequirement = apps.get_model("programmes", "CropInputRequirement")
    Batch = apps.get_model("arda_requests", "ARDARequestBatch")
    crops = {crop.name.strip().lower(): crop for crop in Crop.objects.all()}

    for programme in Programme.objects.all():
        wanted = set()
        if (programme.crop or "").strip().lower() in crops:
            wanted.add(crops[programme.crop.strip().lower()].pk)
        wanted.update(CropInputRequirement.objects.filter(programme=programme).values_list("crop_id", flat=True))
        for name in Batch.objects.filter(programme=programme).values_list("crop", flat=True):
            if (name or "").strip().lower() in crops:
                wanted.add(crops[name.strip().lower()].pk)
        for crop_id in wanted:
            ProgrammeCrop.objects.get_or_create(programme=programme, crop_id=crop_id)
        # Input types the programme already has catalogue lines for.
        if not programme.input_categories:
            categories = sorted(set(
                CropInputRequirement.objects.filter(programme=programme).exclude(input_category="").values_list("input_category", flat=True)
            ))
            if categories:
                programme.input_categories = categories
                programme.save(update_fields=["input_categories"])


def approved_requests_keep_their_hectares(apps, schema_editor):
    """Requests already marked approved were approved in full: there was no partial approval before."""
    Batch = apps.get_model("arda_requests", "ARDARequestBatch")
    for batch in Batch.objects.filter(status="APPROVED", approved_hectares__isnull=True, requested_hectares__gt=0):
        batch.approved_hectares = batch.requested_hectares
        batch.save(update_fields=["approved_hectares"])


class Migration(migrations.Migration):
    dependencies = [
        ("programmes", "0012_programme_crops_and_packs"),
        ("arda_requests", "0006_request_approval"),
    ]

    operations = [
        migrations.RunPython(link_crops, migrations.RunPython.noop),
        migrations.RunPython(approved_requests_keep_their_hectares, migrations.RunPython.noop),
    ]
