from django.core.management.base import BaseCommand

from apps.geography.zimbabwe import sync_zimbabwe_geography
from apps.programmes.catalogue import ensure_predefined_crops


class Command(BaseCommand):
    help = (
        "Load Zimbabwe's 10 provinces and their districts, and insert Maize, Sorghum and Wheat "
        "when those crops are missing. Safe to run again. Does not add prices, input rates, "
        "wards, clusters, programmes, farmers or subscriptions, and does not change existing "
        "crop requirements. On Render, open the shell for the web service and run: "
        "python manage.py load_reference_data"
    )

    def handle(self, *args, **options):
        geography = sync_zimbabwe_geography()
        crops = ensure_predefined_crops()
        for label in (
            "provinces_added",
            "provinces_renamed",
            "districts_added",
            "districts_repointed",
            "districts_deactivated",
            "provinces_deactivated",
        ):
            self.stdout.write(f"{label}: {len(geography[label])}")
        self.stdout.write(f"crops_created: {', '.join(crops['created']) or 'none'}")
        self.stdout.write(f"crops_unchanged: {', '.join(crops['unchanged']) or 'none'}")
        self.stdout.write(self.style.SUCCESS(
            "Reference data load completed. Configure wards, clusters, programmes and input prices in the application."
        ))
