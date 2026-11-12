import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_roles_audit_log"),
        ("farmers", "0006_farm_irrigation_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="farmer",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="user_account",
                to="farmers.farmer",
            ),
        ),
    ]
