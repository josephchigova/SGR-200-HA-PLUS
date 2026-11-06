from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("farmers", "0005_farm_cluster_and_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="farm",
            name="irrigation_type",
            field=models.CharField(
                choices=[
                    ("NONE", "Not recorded"),
                    ("RAINFED", "Rainfed"),
                    ("CENTRE_PIVOT", "Centre pivot"),
                    ("DRIP", "Drip"),
                    ("SPRINKLER", "Sprinkler"),
                    ("FLOOD", "Flood"),
                    ("OTHER", "Other"),
                ],
                default="NONE",
                max_length=30,
            ),
        ),
    ]
