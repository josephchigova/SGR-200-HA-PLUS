from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("subscriptions", "0002_farmersubscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="farmersubscription",
            name="payment_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]