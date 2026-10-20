"""Filter querysets by the selected agricultural year and crop season.

Season foreign keys and season-name fields identify the agricultural year.
Summer and Winter are applied only where a crop category, catalogue crop name,
or seasonal planting column identifies the crop season. Records without that
relationship are left on the agricultural year and are not guessed into a crop season.
"""

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .calendar import CROP_SEASONS
from .models import Crop


def parse_crop_season(value):
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip().upper()
    if normalized not in CROP_SEASONS:
        raise ValidationError({"crop_season": ["Select Summer or Winter."]})
    return normalized


def filter_by_agricultural_year(queryset, season, season_name, *, relation="season"):
    if season:
        if str(season).isdigit():
            queryset = queryset.filter(**{f"{relation}_id": season})
        else:
            queryset = queryset.filter(**{f"{relation}__name__iexact": season})
    if season_name:
        queryset = queryset.filter(**{f"{relation}__name__iexact": season_name})
    return queryset


def _catalogue_name_q(field, crop_season):
    names = list(Crop.objects.filter(category=crop_season).values_list("name", flat=True))
    if not names:
        return None
    query = Q()
    for name in names:
        query |= Q(**{f"{field}__iexact": name})
    return query


def filter_by_crop_name(queryset, crop_season, field):
    query = _catalogue_name_q(field, crop_season)
    if query is None:
        return queryset.none()
    return queryset.filter(query)


def filter_allocations_by_crop_season(queryset, crop_season):
    """Use the crop reference category when it is set, otherwise the crop name."""

    name_query = _catalogue_name_q("crop", crop_season)
    reference_query = Q(crop_reference__category=crop_season)
    if name_query is None:
        return queryset.filter(reference_query)
    return queryset.filter(reference_query | (Q(crop_reference__isnull=True) & name_query))


def filter_debts_by_crop_season(queryset, crop_season):
    """Match the debt crop name. A blank crop can use the allocation's crop reference."""

    name_query = _catalogue_name_q("crop", crop_season)
    blank_crop = Q(crop="") | Q(crop__isnull=True)
    reference_query = blank_crop & Q(input_allocation__crop_reference__category=crop_season)
    if name_query is None:
        return queryset.filter(reference_query)
    return queryset.filter(name_query | reference_query)


def filter_planting_by_crop_season(queryset, crop_season):
    from .calendar import SUMMER, WINTER

    if crop_season == SUMMER:
        return queryset.filter(Q(summer_crop__isnull=False) | Q(summer_hectares__gt=0))
    if crop_season == WINTER:
        return queryset.filter(Q(winter_crop__isnull=False) | Q(winter_hectares__gt=0))
    return queryset
