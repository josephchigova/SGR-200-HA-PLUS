from django.db import migrations, models


def allocate_approved_farmers(apps, schema_editor):
    """An allocation stays pending only while the farmer is not approved."""
    InputAllocation = apps.get_model("inputs", "InputAllocation")
    InputAllocation.objects.filter(
        status="PENDING",
        farmer__verification_status__in=["VERIFIED", "APPROVED"],
    ).update(status="ALLOCATED")


class Migration(migrations.Migration):
    dependencies = [
        ("inputs", "0004_inputallocation_calculated_input_cost_per_hectare_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inputallocation",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("ALLOCATED", "Allocated"),
                    ("COLLECTED", "Collected"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
        migrations.RunPython(allocate_approved_farmers, migrations.RunPython.noop),
    ]
