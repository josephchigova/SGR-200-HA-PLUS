from django.core.management.base import BaseCommand

from apps.programmes.models import Crop


class Command(BaseCommand):
    help = "Create the default summer and winter crop catalogue."

    def handle(self, *args, **options):
        defaults = [
            ("Maize", Crop.CATEGORY_SUMMER),
            ("Sorghum", Crop.CATEGORY_SUMMER),
            ("Wheat", Crop.CATEGORY_WINTER),
        ]
        for name, category in defaults:
            Crop.objects.update_or_create(name=name, defaults={"category": category, "active": True})
        self.stdout.write(self.style.SUCCESS("Default summer and winter crops are ready."))
