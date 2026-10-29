from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("farmers", "0003_farmer_cluster"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="farmer",
            index=models.Index(fields=["full_name"], name="farmer_full_name_idx"),
        ),
        migrations.AddIndex(
            model_name="farmer",
            index=models.Index(fields=["surname", "first_name"], name="farmer_name_pair_idx"),
        ),
    ]
