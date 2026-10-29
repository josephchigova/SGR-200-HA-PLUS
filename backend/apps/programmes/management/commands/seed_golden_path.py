from django.core.management.base import BaseCommand

from apps.inputs.models import Input
from apps.programmes.models import Programme, Season


class Command(BaseCommand):
    help = "Create or update the demonstration season, programme, and seed input."

    def handle(self, *args, **options):
        season, season_created = Season.objects.update_or_create(
            name="2026/2027",
            defaults={
                "start_date": "2026-11-01",
                "end_date": "2027-10-31",
                "status": Season.STATUS_ACTIVE,
            },
        )
        programme, programme_created = Programme.objects.update_or_create(
            code="SGR-200HA-2026",
            defaults={
                "name": "SGR 200HA+ 2026/27",
                "description": "SGR 200HA+ demonstration programme",
                "season": season,
                "crop": "Maize",
                "institution": "ARDA",
                "announced_hectares": "20000.00",
                "status": Programme.STATUS_OPEN,
                "is_active": True,
            },
        )
        input_item, input_created = Input.objects.get_or_create(
            name="Maize Seed",
            defaults={"category": Input.CATEGORY_SEED, "unit": "bags", "active": True},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Golden Path data ready: season {season.pk}, programme {programme.pk}, "
                f"input {input_item.pk} (created: {season_created}/{programme_created}/{input_created})."
            )
        )
