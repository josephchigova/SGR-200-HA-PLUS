from django.db import migrations, models
from django.db.models.functions import Lower, Trim


class Migration(migrations.Migration):

    dependencies = [
        ("programmes", "0005_merge_duplicate_crops"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="crop",
            constraint=models.UniqueConstraint(
                Lower(Trim("name")),
                name="unique_crop_name_case_insensitive",
            ),
        ),
    ]
