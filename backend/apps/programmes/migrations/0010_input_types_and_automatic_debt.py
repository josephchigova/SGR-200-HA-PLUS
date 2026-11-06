from django.db import migrations, models


def remap_cost_types(apps, schema_editor):
    requirement = apps.get_model("programmes", "CropInputRequirement")
    mapping = {
        "AGRICULTURAL_INPUT": "CROP_INPUT",
        "MACHINERY_HIRING": "FARM_EQUIPMENT",
        "LABOUR": "CROP_INPUT",
        "OTHER_OPERATIONAL": "CROP_INPUT",
    }
    for old, new in mapping.items():
        requirement.objects.filter(cost_type=old).update(cost_type=new)


class Migration(migrations.Migration):

    dependencies = [
        ("programmes", "0009_deactivate_winter_named_selling_prices"),
    ]

    operations = [
        migrations.RunPython(remap_cost_types, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="cropinputrequirement",
            name="include_in_input_cost",
        ),
        migrations.AlterField(
            model_name="cropinputrequirement",
            name="cost_type",
            field=models.CharField(
                choices=[("CROP_INPUT", "Crop Input"), ("FARM_EQUIPMENT", "Farm Equipment")],
                default="CROP_INPUT",
                max_length=30,
            ),
        ),
    ]
