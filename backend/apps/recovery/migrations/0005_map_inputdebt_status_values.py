from django.db import migrations


def map_statuses(apps, schema_editor):
    InputDebt = apps.get_model("recovery", "InputDebt")
    InputDebt.objects.filter(status="OPEN").update(status="NOT_RECOVERED")
    InputDebt.objects.filter(status="PARTIAL").update(status="PARTIALLY_RECOVERED")
    InputDebt.objects.filter(status="CLEARED").update(status="FULLY_RECOVERED")


class Migration(migrations.Migration):

    dependencies = [
        ("recovery", "0004_inputdebt_amount_recovered_inputdebt_district_and_more"),
    ]

    operations = [
        migrations.RunPython(map_statuses, migrations.RunPython.noop),
    ]
