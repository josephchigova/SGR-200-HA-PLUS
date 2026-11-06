import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clusters", "0001_initial"),
        ("farmers", "0005_farm_cluster_and_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="cluster",
            name="lead_member",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clusters_led",
                to="farmers.farmer",
            ),
        ),
        migrations.AlterField(
            model_name="cluster",
            name="district",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clusters",
                to="geography.district",
            ),
        ),
        migrations.AddConstraint(
            model_name="cluster",
            constraint=models.UniqueConstraint(
                condition=models.Q(active=True, lead_member__isnull=False),
                fields=("lead_member",),
                name="unique_active_cluster_lead_member",
            ),
        ),
    ]
