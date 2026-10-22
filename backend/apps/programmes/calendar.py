"""Agricultural year and Summer/Winter calendar.

The agricultural year runs from 1 October through 30 September. The existing
Season row is that year (for example "2026/2027"). Summer and Winter are the
two crop seasons inside the year. They are not additional Season rows.

April belongs to both stated ranges, so one boundary is used everywhere:

- Summer owns 1 October through 15 April.
- Winter owns 16 April through 30 September.

15 April is still Summer. 16 April is Winter. A date is never assigned to
both seasons.
"""

from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Season

SUMMER = "SUMMER"
WINTER = "WINTER"
# The first operating year. Other Season rows stay in the database and are hidden from the selector.
SELECTABLE_AGRICULTURAL_YEARS = ("2026/2027",)
CROP_SEASONS = (SUMMER, WINTER)
APRIL_SUMMER_LAST_DAY = 15
APRIL_CONVENTION = (
    "April is shared by Summer and Winter. "
    "1 April through 15 April belong to Summer, the season that is ending. "
    "16 April through 30 April belong to Winter, the season that is starting. "
    "Every date uses this same boundary."
)


def today():
    return timezone.localdate()


def agricultural_year_for_date(on_date):
    start_year = on_date.year if on_date.month >= 10 else on_date.year - 1
    end_year = start_year + 1
    return {
        "start_year": start_year,
        "end_year": end_year,
        "name": f"{start_year}/{end_year}",
        "start_date": date(start_year, 10, 1),
        "end_date": date(end_year, 9, 30),
    }


def crop_season_for_date(on_date):
    if on_date.month >= 10 or on_date.month <= 3:
        return SUMMER
    if on_date.month == 4 and on_date.day <= APRIL_SUMMER_LAST_DAY:
        return SUMMER
    return WINTER


def crop_season_label(crop_season):
    if crop_season == SUMMER:
        return "Summer"
    if crop_season == WINTER:
        return "Winter"
    return ""


def crop_seasons_for_date(on_date):
    spec = agricultural_year_for_date(on_date)
    summer_end = date(spec["end_year"], 4, APRIL_SUMMER_LAST_DAY)
    winter_start = date(spec["end_year"], 4, APRIL_SUMMER_LAST_DAY + 1)
    return [
        {
            "code": SUMMER,
            "label": "Summer",
            "start_date": spec["start_date"].isoformat(),
            "end_date": summer_end.isoformat(),
        },
        {
            "code": WINTER,
            "label": "Winter",
            "start_date": winter_start.isoformat(),
            "end_date": spec["end_date"].isoformat(),
        },
    ]


def season_is_selectable(season):
    return bool(season) and season.name in SELECTABLE_AGRICULTURAL_YEARS


def season_is_current_year(season, on_date=None):
    spec = agricultural_year_for_date(on_date or today())
    return season.start_date == spec["start_date"] and season.end_date == spec["end_date"]


def ensure_current_agricultural_year(on_date=None):
    """Return the Season row for the agricultural year, creating it once if needed.

    An existing row with the canonical name is reused even when its dates differ.
    If exactly one other row already has the canonical dates, that row is reused
    instead of inserting a second year. Existing rows are not renamed or deleted.
    """

    spec = agricultural_year_for_date(on_date or today())
    named = Season.objects.filter(name=spec["name"]).first()
    if named is not None:
        return named

    dated = Season.objects.filter(start_date=spec["start_date"], end_date=spec["end_date"]).order_by("id")
    if dated.count() == 1:
        return dated.first()

    try:
        with transaction.atomic():
            season, _created = Season.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "start_date": spec["start_date"],
                    "end_date": spec["end_date"],
                    "status": Season.STATUS_ACTIVE,
                    "notes": "Created for the current agricultural year.",
                },
            )
    except IntegrityError:
        season = Season.objects.get(name=spec["name"])
    return season
