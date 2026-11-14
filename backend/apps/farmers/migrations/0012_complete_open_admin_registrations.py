from django.db import migrations
from django.db.models import Q
from django.utils import timezone

OPEN = ["DRAFT", "PENDING", "SUBMITTED", "UNDER_REVIEW", "CORRECTIONS_REQUESTED"]
NOTE = "Registration completed: registered by an administrator, who checked the KYC documents in person."


def complete(apps, schema_editor):
    """Any farmer an administrator registered is complete once their farm is recorded.

    0010 completed lead farmers only. This also completes other farmers an administrator
    registered, and records saved after 0010 but never finished in the wizard. Records
    lead farmers captured, records with no registrar, records without a farm and rejected
    records are left alone.
    """
    Farmer = apps.get_model("farmers", "Farmer")
    Farm = apps.get_model("farmers", "Farm")
    Event = apps.get_model("farmers", "FarmerReviewEvent")
    now = timezone.now()
    open_records = (
        Farmer.objects.filter(verification_status__in=OPEN, registered_by__isnull=False, farms__isnull=False)
        .filter(Q(registered_by__is_superuser=True) | ~Q(registered_by__role="lead_farmer"))
        .distinct()
    )
    for farmer in open_records:
        farmer.verification_status = "VERIFIED"
        farmer.membership_status = "ACTIVE"
        farmer.verified_by_id = farmer.registered_by_id
        farmer.verification_date = now
        farmer.submitted_at = farmer.submitted_at or now
        farmer.rejection_reason = ""
        farmer.save(update_fields=["verification_status", "membership_status", "verified_by", "verification_date", "submitted_at", "rejection_reason"])
        Farm.objects.filter(farmer=farmer).update(verification_status="VERIFIED", verification_date=now)
        Event.objects.create(farmer=farmer, action="APPROVED", remarks=NOTE, actor_name="System")


class Migration(migrations.Migration):
    dependencies = [("farmers", "0011_farmer_change_requests")]
    operations = [migrations.RunPython(complete, migrations.RunPython.noop)]
