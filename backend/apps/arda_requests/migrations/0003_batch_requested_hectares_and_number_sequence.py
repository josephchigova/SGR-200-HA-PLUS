from decimal import Decimal

from django.db import migrations, models


def backfill_batch_requested_hectares(apps, schema_editor):
    Batch = apps.get_model("arda_requests", "ARDARequestBatch")
    FarmerRequest = apps.get_model("arda_requests", "ARDAFarmerRequest")
    database = schema_editor.connection.alias
    batch_totals = FarmerRequest.objects.using(database).values("request_batch_id").annotate(
        total=models.Sum("requested_hectares")
    )
    for row in batch_totals.iterator():
        Batch.objects.using(database).filter(pk=row["request_batch_id"]).update(
            requested_hectares=row["total"] or Decimal("0.00")
        )


def seed_next_request_number(apps, schema_editor):
    Batch = apps.get_model("arda_requests", "ARDARequestBatch")
    Sequence = apps.get_model("arda_requests", "ARDARequestNumberSequence")
    highest_existing = 999
    for request_number in Batch.objects.using(schema_editor.connection.alias).values_list("request_number", flat=True):
        suffix = request_number[3:] if request_number.startswith("SGR") else ""
        if suffix.isdecimal():
            highest_existing = max(highest_existing, int(suffix))
    Sequence.objects.using(schema_editor.connection.alias).update_or_create(
        pk=1,
        defaults={"next_number": max(1000, highest_existing + 1)},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("arda_requests", "0002_ardarequestbatch_ardafarmerrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="ardarequestbatch",
            name="requested_hectares",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14),
        ),
        migrations.CreateModel(
            name="ARDARequestNumberSequence",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("next_number", models.PositiveIntegerField(default=1000)),
            ],
        ),
        migrations.RunPython(backfill_batch_requested_hectares, migrations.RunPython.noop),
        migrations.RunPython(seed_next_request_number, migrations.RunPython.noop),
    ]