from django.core.management.base import BaseCommand

from apps.geography.wards import SOURCE, load_wards


class Command(BaseCommand):
    help = "Load the real wards of every Zimbabwe district. Existing wards and farmer records are kept."

    def handle(self, *args, **options):
        summary = load_wards()
        self.stdout.write(f"Source: {SOURCE}")
        self.stdout.write(f"wards_added: {summary['wards_added']}")
        self.stdout.write(f"wards_matched: {summary['wards_matched']}")
        for label in ("districts_added", "review"):
            self.stdout.write(f"{label}: {len(summary[label])}")
            for row in summary[label]:
                self.stdout.write(f"  - {row}")
        self.stdout.write(self.style.SUCCESS("Zimbabwe ward register is up to date."))
