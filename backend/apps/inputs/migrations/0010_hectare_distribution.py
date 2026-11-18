"""Replace variety quantity caps with Admin hectare limits and a final confirmation step."""

from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_line_hectares(apps, schema_editor):
    """Older lines used the farmer's single hectare figure for every variety."""
    Line = apps.get_model("inputs", "InputSupplyLine")
    Entry = apps.get_model("inputs", "InputSupplyFarmer")
    hectares = dict(Entry.objects.values_list("id", "hectares"))
    for line in Line.objects.all():
        cost = Decimal("0.00")
        if line.unit_price is not None:
            cost = (Decimal(line.quantity) * Decimal(line.unit_price)).quantize(Decimal("0.01"))
        line.hectares = hectares.get(line.farmer_entry_id, Decimal("0"))
        line.estimated_cost = cost
        line.save(update_fields=["hectares", "estimated_cost"])


class Migration(migrations.Migration):

    dependencies = [
        ("programmes", "0013_link_existing_programme_crops"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("inputs", "0009_input_supply_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="inputsupplyrequest",
            name="stage",
            field=models.CharField(
                choices=[("REQUEST", "Hectare request"), ("DISTRIBUTION", "Farmer distribution")],
                default="REQUEST",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="inputsupplyline",
            name="hectares",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="inputsupplyline",
            name="estimated_cost",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=16),
        ),
        migrations.AlterField(
            model_name="inputsupplyline",
            name="cap",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supply_lines",
                to="inputs.programmevarietycap",
            ),
        ),
        migrations.AddField(
            model_name="inputsupplyevent",
            name="detail",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="inputsupplyevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("SAVED", "Draft saved"),
                    ("CORRECTED", "Corrections saved"),
                    ("SUBMITTED", "Submitted"),
                    ("RESUBMITTED", "Resubmitted"),
                    ("LIMITS_APPROVED", "Requested hectares approved"),
                    ("LIMITS_DISTRIBUTED", "Hectares distributed"),
                    ("LIMITS_ADJUSTED", "Approved hectares adjusted"),
                    ("FINAL_SUBMITTED", "Final distribution submitted"),
                    ("FINAL_RESUBMITTED", "Final distribution resubmitted"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                    ("RETURNED", "Returned for corrections"),
                    ("REVERSED", "Approval reversed"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(copy_line_hectares, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="inputsupplyrequest",
            name="one_open_input_supply_request",
        ),
        migrations.AddConstraint(
            model_name="inputsupplyrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["DRAFT", "SUBMITTED", "RETURNED", "LIMITS_SET", "CONFIRMATION"])),
                fields=("lead_farmer", "programme", "season", "crop"),
                name="one_open_input_supply_request",
            ),
        ),
        migrations.CreateModel(
            name="InputSupplyLimit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("CROP", "Crop"), ("CATEGORY", "Input category"), ("VARIETY", "Variety")], max_length=20)),
                ("input_category", models.CharField(blank=True, default="", max_length=20)),
                ("requested_hectares", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("approved_hectares", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="limits", to="inputs.inputsupplyrequest")),
                (
                    "requirement",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supply_limits",
                        to="programmes.cropinputrequirement",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="supply_limits_set",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["request_id", "scope", "input_category", "id"]},
        ),
        migrations.AddConstraint(
            model_name="inputsupplylimit",
            constraint=models.UniqueConstraint(condition=models.Q(("scope", "CROP")), fields=("request",), name="unique_supply_crop_limit"),
        ),
        migrations.AddConstraint(
            model_name="inputsupplylimit",
            constraint=models.UniqueConstraint(
                condition=models.Q(("scope", "CATEGORY")), fields=("request", "input_category"), name="unique_supply_category_limit",
            ),
        ),
        migrations.AddConstraint(
            model_name="inputsupplylimit",
            constraint=models.UniqueConstraint(
                condition=models.Q(("scope", "VARIETY")), fields=("request", "requirement"), name="unique_supply_variety_limit",
            ),
        ),
        migrations.AddConstraint(
            model_name="inputsupplylimit",
            constraint=models.CheckConstraint(condition=models.Q(("approved_hectares__gte", 0)), name="supply_limit_approved_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="inputsupplylimit",
            constraint=models.CheckConstraint(condition=models.Q(("requested_hectares__gte", 0)), name="supply_limit_requested_nonnegative"),
        ),
    ]
