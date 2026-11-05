from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.farmers.operational_reset import collect_counts, operational_models, preserved_models, reset_operational_data


class Command(BaseCommand):
    help = "Delete operational SGR records and keep accounts, geography, seasons, crops, programmes, and finance configuration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the models and record counts that would be deleted. Nothing is changed.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Delete the operational records. Required for any change.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirm = options["confirm"]
        if not dry_run and not confirm:
            raise CommandError("Refusing to delete records. Pass --dry-run to preview, or --confirm to delete.")
        if dry_run and confirm:
            self.stdout.write(self.style.WARNING("--dry-run is set, so --confirm is ignored and nothing will be deleted."))

        self.stdout.write("Operational records")
        operational = collect_counts(operational_models())
        for label, count in operational:
            self.stdout.write(f"  {label}: {count}")
        self.stdout.write("Preserved configuration")
        preserved = collect_counts(preserved_models())
        for label, count in preserved:
            self.stdout.write(f"  {label}: {count}")

        if dry_run or not confirm:
            self.stdout.write(self.style.WARNING("Dry run only. No records were deleted."))
            return

        with transaction.atomic():
            deleted, programmes_reset = reset_operational_data()
        removed = sum(count for _label, count in deleted)
        self.stdout.write(self.style.SUCCESS(f"Deleted {removed} operational records."))
        for label, count in deleted:
            if count:
                self.stdout.write(f"  removed {label}: {count}")
        self.stdout.write(f"Programme allocated-hectare counters cleared: {programmes_reset}")
        self.stdout.write("Preserved configuration after deletion")
        for label, count in collect_counts(preserved_models()):
            self.stdout.write(f"  {label}: {count}")
