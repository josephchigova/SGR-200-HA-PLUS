"""Zimbabwe ward register.

Source: "Zimbabwe - Subnational Administrative Boundaries" (COD-AB), published by
UN OCHA on the Humanitarian Data Exchange from Zimbabwe National Statistics Agency
(ZIMSTAT) boundaries. Version v01, valid from 11 September 2018. 1,961 wards in 91
districts. Licence: CC BY-IGO. https://data.humdata.org/dataset/cod-ab-zwe

One dataset is used for every ward so the numbering is consistent. It predates the
2023 ZEC delimitation, so a district whose ward count changed in 2023 is listed here
with its 2018 wards. Administrators can add a missing ward in the application.
"""

import csv
import re
from pathlib import Path

from django.db import transaction

from .models import District, Province, Ward
from .zimbabwe import normalize_name

DATA_FILE = Path(__file__).resolve().parent / "data" / "zwe_wards_ocha_zimstat_2018_v01.csv"
SOURCE = "UN OCHA COD-AB Zimbabwe (ZIMSTAT), v01, valid from 2018-09-11"

PROVINCE_ALIASES = {"Harare": "Harare Metropolitan", "Bulawayo": "Bulawayo Metropolitan"}
# Dataset district name -> the name this system already uses.
DISTRICT_ALIASES = {
    "Centenary/ Muzarabani": "Muzarabani",
    "Uzumba Maramba Pfungwe": "Uzumba-Maramba-Pfungwe",
    "Kadoma Urban": "Kadoma",
}


def ward_number(name):
    match = re.search(r"\d+", str(name or ""))
    return int(match.group()) if match else None


@transaction.atomic
def load_wards(path=DATA_FILE):
    summary = {"wards_added": 0, "wards_matched": 0, "districts_added": [], "review": []}
    provinces = {normalize_name(province.name): province for province in Province.objects.all()}
    districts = {}
    existing = {}

    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            province_name = PROVINCE_ALIASES.get(row["province"], row["province"])
            province = provinces.get(normalize_name(province_name))
            if province is None:
                summary["review"].append(f"Province not found: {row['province']}")
                continue
            district_name = DISTRICT_ALIASES.get(row["district"], row["district"])
            key = (province.pk, normalize_name(district_name))
            district = districts.get(key)
            if district is None:
                district = next(
                    (item for item in District.objects.filter(province=province) if normalize_name(item.name) == key[1]),
                    None,
                )
                if district is None:
                    # Urban councils are separate districts in the ZIMSTAT boundaries.
                    district = District.objects.create(province=province, name=district_name)
                    summary["districts_added"].append(f"{district_name} ({province.name})")
                elif not district.active:
                    district.active = True
                    district.save(update_fields=["active"])
                districts[key] = district
                existing[district.pk] = {ward_number(ward.name): ward for ward in district.wards.all() if ward_number(ward.name) is not None}
            number = ward_number(row["ward"])
            current = existing[district.pk].get(number)
            if current is not None:
                # A ward already recorded keeps its name and its farmers. Only the code is filled in.
                if current.code != row["ward_pcode"] or not current.active:
                    current.code = row["ward_pcode"]
                    current.active = True
                    current.save(update_fields=["code", "active", "updated_at"])
                summary["wards_matched"] += 1
                continue
            ward = Ward.objects.create(district=district, name=f"Ward {number}", code=row["ward_pcode"])
            existing[district.pk][number] = ward
            summary["wards_added"] += 1
    return summary


MAX_WARD_NUMBER = 999


def ward_for_number(district, number):
    """The ward with this number in the district, added when it is not on record yet.

    Wards are numbered, and some districts run past 300, so the number is typed rather
    than chosen from a list. A ward already on record keeps its id, name and farmers.
    """
    number = int(number)
    if not 1 <= number <= MAX_WARD_NUMBER:
        raise ValueError(f"Enter a ward number from 1 to {MAX_WARD_NUMBER}.")
    for ward in Ward.objects.filter(district=district):
        if ward_number(ward.name) == number:
            if not ward.active:
                ward.active = True
                ward.save(update_fields=["active", "updated_at"])
            return ward
    ward, _created = Ward.objects.get_or_create(district=district, name=f"Ward {number}")
    return ward
