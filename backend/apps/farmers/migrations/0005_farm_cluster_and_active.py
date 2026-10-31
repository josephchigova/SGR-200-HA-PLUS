from django.db import migrations, models
import django.db.models.deletion


def copy_farm_geography(apps, schema_editor):
    """Fill empty farm geography from the farmer. Never create a second farm."""
    Farm = apps.get_model("farmers", "Farm")
    for farm in Farm.objects.select_related("farmer").iterator():
        farmer = farm.farmer
        updates = []
        if farm.province_id is None and farmer.province_id:
            farm.province_id = farmer.province_id
            updates.append("province")
        if farm.district_id is None and farmer.district_id:
            farm.district_id = farmer.district_id
            updates.append("district")
        if farm.ward_id is None and farmer.ward_id:
            farm.ward_id = farmer.ward_id
            updates.append("ward")
        if farm.cluster_id is None and farmer.cluster_id:
            farm.cluster_id = farmer.cluster_id
            updates.append("cluster")
        if updates:
            farm.save(update_fields=updates)


class Migration(migrations.Migration):

    dependencies = [
        ("clusters", "0001_initial"),
        ("farmers", "0004_farmer_name_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="farm",
            name="cluster",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="farms",
                to="clusters.cluster",
            ),
        ),
        migrations.AddField(
            model_name="farm",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(copy_farm_geography, migrations.RunPython.noop),
    ]
