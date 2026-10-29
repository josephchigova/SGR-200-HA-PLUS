from django.core.management.base import BaseCommand

from apps.geography.zimbabwe import sync_zimbabwe_geography


class Command(BaseCommand):
    help = "Insert missing Zimbabwe provinces and districts and correct known duplicate names without deleting farmer records."

    def handle(self, *args, **options):
        summary = sync_zimbabwe_geography()
        for label in (
            "provinces_added",
            "provinces_renamed",
            "districts_added",
            "districts_repointed",
            "districts_deactivated",
            "provinces_deactivated",
            "skipped",
            "review",
        ):
            rows = summary[label]
            self.stdout.write(f"{label}: {len(rows)}")
            for row in rows:
                self.stdout.write(f"  - {row}")
        self.stdout.write(self.style.SUCCESS("Zimbabwe geography sync completed."))
