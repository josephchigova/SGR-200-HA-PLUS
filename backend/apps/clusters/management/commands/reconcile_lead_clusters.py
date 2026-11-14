"""Report how existing records fit the lead-farmer cluster rule, and fix only what is safe.

Safe and automatic (with --apply):
  * a cluster that has a lead farmer is renamed to that lead farmer's name;
  * a lead farmer's own record is marked as a lead and placed in their cluster;
  * a lead farmer's login is linked to their cluster when the link is missing.

Never automatic: farmers with no lead farmer, and clusters with no lead farmer. They
are listed so an administrator can register the lead farmer and move the farmers with
the audited reassignment. Nothing is assigned at random.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

from apps.accounts.models import User
from apps.clusters.models import Cluster
from apps.farmers.models import Farmer
from apps.farmers.services import cluster_name_for


class Command(BaseCommand):
    help = "Check clusters against the rule that each lead farmer is one cluster. Read-only unless --apply is given."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Make the safe corrections listed in the report.")

    def handle(self, *args, **options):
        apply = options["apply"]
        changes = 0
        with transaction.atomic():
            for cluster in Cluster.objects.filter(lead_member__isnull=False).select_related("lead_member"):
                lead = cluster.lead_member
                wanted = cluster_name_for(lead, exclude_pk=cluster.pk)
                if cluster.name != wanted:
                    self.stdout.write(f"rename cluster #{cluster.pk}: {cluster.name!r} -> {wanted!r}")
                    changes += 1
                    if apply:
                        cluster.name = wanted
                        cluster.save(update_fields=["name", "updated_at"])
                if not lead.is_lead or lead.cluster_id != cluster.pk:
                    self.stdout.write(f"mark farmer #{lead.pk} as the lead of cluster #{cluster.pk}")
                    changes += 1
                    if apply:
                        lead.is_lead = True
                        lead.cluster = cluster
                        lead.save(update_fields=["is_lead", "cluster", "updated_at"])
                account = User.objects.filter(farmer=lead, role=User.ROLE_LEAD_FARMER).first()
                if account is not None and (account.assigned_cluster_id != cluster.pk or cluster.lead_farmer_id != account.pk):
                    self.stdout.write(f"link login {account.email} to cluster #{cluster.pk}")
                    changes += 1
                    if apply:
                        account.assigned_cluster = cluster
                        account.save(update_fields=["assigned_cluster", "updated_at"])
                        cluster.lead_farmer = account
                        cluster.save(update_fields=["lead_farmer", "updated_at"])
            if not apply:
                transaction.set_rollback(True)

        orphan_clusters = Cluster.objects.filter(lead_member__isnull=True).annotate(members=Count("farmers"))
        no_lead = Farmer.objects.filter(is_lead=False).filter(Q(cluster__isnull=True) | Q(cluster__lead_member__isnull=True))
        self.stdout.write("")
        self.stdout.write(f"Clusters without a lead farmer: {orphan_clusters.count()} (need an administrator decision)")
        for cluster in orphan_clusters.order_by("name"):
            self.stdout.write(f"  - #{cluster.pk} {cluster.name}: {cluster.members} farmers")
        self.stdout.write(f"Farmers without a lead farmer: {no_lead.count()} (not assigned automatically)")
        lead_logins = User.objects.filter(role=User.ROLE_LEAD_FARMER).filter(Q(farmer__isnull=True) | Q(assigned_cluster__isnull=True))
        self.stdout.write(f"Lead farmer logins missing a register record or cluster: {lead_logins.count()}")
        for account in lead_logins:
            self.stdout.write(f"  - {account.email}")
        verb = "Applied" if apply else "Would apply"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changes} safe correction(s)."))
