"""Requests still in draft or submitted become approved.

A request is now approved when it is made, so earlier drafts are treated the same way. Only
the status and approved hectares change; no request is deleted. Rejected requests stay rejected.
"""

from django.db import migrations
from django.db.models import F


def approve_open_requests(apps, schema_editor):
    Batch = apps.get_model("arda_requests", "ARDARequestBatch")
    Line = apps.get_model("arda_requests", "RequestBatchLine")
    open_batches = Batch.objects.filter(status__in=["PENDING", "SUBMITTED"])
    open_batches.filter(requested_hectares__gt=0).update(status="APPROVED", approved_hectares=F("requested_hectares"))
    open_batches.update(status="APPROVED")
    Line.objects.filter(batch__status="APPROVED", approved_hectares__isnull=True).update(approved_hectares=F("requested_hectares"))


class Migration(migrations.Migration):
    dependencies = [("arda_requests", "0007_request_product_lines")]

    operations = [migrations.RunPython(approve_open_requests, migrations.RunPython.noop)]
