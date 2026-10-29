from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("subscriptions", "0003_farmersubscription_payment_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("payment_date", models.DateField()),
                ("method", models.CharField(choices=[("CASH", "Cash"), ("BANK", "Bank")], max_length=10)),
                ("reference", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("idempotency_key", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="subscription_payments", to=settings.AUTH_USER_MODEL)),
                ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="subscriptions.farmersubscription")),
            ],
            options={"ordering": ["-payment_date", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="subscriptionpayment",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="subscription_payment_positive"),
        ),
    ]
