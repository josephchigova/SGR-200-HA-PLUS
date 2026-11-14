from django.db import migrations
from django.db.models import Q
from django.utils import timezone

OPEN = ["DRAFT", "PENDING", "SUBMITTED", "UNDER_REVIEW"]
NOTE = "Registration completed: a lead farmer, and any farmer an administrator registered, does not upload KYC documents. The documents are checked in person."


def complete(apps, schema_editor):
    """Open lead-farmer records are complete, and so are other administrator registrations.

    Missing KYC files are not a reason to leave these incomplete. A lead farmer is
    complete even without a farm. An ordinary farmer an administrator registered is
    complete once a farm exists. Farmers a lead farmer is still capturing, rejected
    records and records sent back for corrections are left as they are.
    """
    Farmer = apps.get_model("farmers", "Farmer")
    Farm = apps.get_model("farmers", "Farm")
    Event = apps.get_model("farmers", "FarmerReviewEvent")
    Cluster = apps.get_model("clusters", "Cluster")
    now = timezone.now()
    lead_ids = set(Cluster.objects.exclude(lead_member_id=None).values_list("lead_member_id", flat=True))
    leads = Farmer.objects.filter(verification_status__in=OPEN).filter(Q(is_lead=True) | Q(pk__in=lead_ids or [0]))
    ordinary = (
        Farmer.objects.filter(verification_status__in=OPEN, is_lead=False, registered_by__isnull=False, farms__isnull=False)
        .filter(Q(registered_by__is_superuser=True) | ~Q(registered_by__role="lead_farmer"))
        .exclude(pk__in=lead_ids or [0])
        .distinct()
    )
    seen = set()
    for farmer in list(leads) + list(ordinary):
        if farmer.pk in seen:
            continue
        seen.add(farmer.pk)
        if farmer.pk in lead_ids:
            farmer.is_lead = True
        farmer.verification_status = "VERIFIED"
        farmer.membership_status = "ACTIVE"
        farmer.verified_by_id = farmer.registered_by_id
        farmer.verification_date = now
        farmer.submitted_at = farmer.submitted_at or now
        farmer.rejection_reason = ""
        farmer.save(update_fields=[
            "is_lead", "verification_status", "membership_status", "verified_by", "verification_date",
            "submitted_at", "rejection_reason",
        ])
        Farm.objects.filter(farmer=farmer).update(verification_status="VERIFIED", verification_date=now)
        Event.objects.create(farmer=farmer, action="APPROVED", remarks=NOTE, actor_name="System")


class Migration(migrations.Migration):
    dependencies = [
        ("farmers", "0012_complete_open_admin_registrations"),
        ("clusters", "0002_lead_member_and_optional_district"),
    ]
    operations = [migrations.RunPython(complete, migrations.RunPython.noop)]
