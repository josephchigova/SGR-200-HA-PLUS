import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("farmers", "0007_registration_approval_workflow"),
        ("programmes", "0010_input_types_and_automatic_debt"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="farmer_type",
            field=models.CharField(choices=[("NEW", "New farmer"), ("EXISTING", "Existing farmer")], default="EXISTING", max_length=20),
        ),
        migrations.AddField(
            model_name="farmer",
            name="is_lead",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="RegistrationCropAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hectares", models.DecimalField(decimal_places=2, max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("crop", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_allocations", to="programmes.crop")),
                ("farmer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crop_allocations", to="farmers.farmer")),
                ("season", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registration_allocations", to="programmes.season")),
            ],
            options={"ordering": ["season_id", "crop__name"]},
        ),
        migrations.AddConstraint(
            model_name="registrationcropallocation",
            constraint=models.UniqueConstraint(fields=("farmer", "crop", "season"), name="unique_registration_crop_season"),
        ),
    ]
