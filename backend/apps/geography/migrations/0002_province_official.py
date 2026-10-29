from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="province",
            name="official",
            field=models.BooleanField(default=False),
        ),
    ]
