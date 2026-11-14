from django.db import migrations
from django.db.models import Q
from django.utils import timezone

OPEN = ["DRAFT", "PENDING", "SUBMITTED", "UNDER_REVIEW"]
NOTE = "Registration completed: the lead farmer was registered by an administrator, who checked the KYC documents in person."


def complete(apps, schema_editor):
    """A lead farmer an administrator registered is a complete, approved member.

    Records left open before this rule existed are completed. Rejected records and records
    sent back for corrections keep their state, and lead farmers' own captures are untouched.
    """
    Farmer = apps.get_model("farmers", "Farmer")
    Farm = apps.get_model("farmers", "Farm")
    Event = apps.get_model("farmers", "FarmerReviewEvent")
    now = timezone.now()
    open_leads = Farmer.objects.filter(is_lead=True, verification_status__in=OPEN).filter(
        Q(registered_by__isnull=True) | ~Q(registered_by__role="lead_farmer")
    )
    for farmer in open_leads:
        farmer.verification_status = "VERIFIED"
        farmer.membership_status = "ACTIVE"
        farmer.verified_by_id = farmer.registered_by_id
        farmer.verification_date = now
        farmer.submitted_at = farmer.submitted_at or now
        farmer.save(update_fields=["verification_status", "membership_status", "verified_by", "verification_date", "submitted_at"])
        Farm.objects.filter(farmer=farmer).update(verification_status="VERIFIED", verification_date=now)
        Event.objects.create(farmer=farmer, action="APPROVED", remarks=NOTE, actor_name="System")


class Migration(migrations.Migration):
    dependencies = [("farmers", "0009_farmer_reassignment_event")]
    operations = [migrations.RunPython(complete, migrations.RunPython.noop)]
