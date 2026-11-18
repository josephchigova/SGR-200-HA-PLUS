from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0004_subscriptionpayment"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmersubscription",
            name="crop_season",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name="farmersubscription",
            name="unique_farmer_subscription_season",
        ),
        migrations.AddConstraint(
            model_name="farmersubscription",
            constraint=models.UniqueConstraint(fields=("farmer", "season", "crop_season"), name="unique_farmer_subscription_season"),
        ),
    ]
