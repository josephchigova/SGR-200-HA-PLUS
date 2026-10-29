import re

from django.db import transaction

from apps.geography.models import District, Province

# Rural districts for Zimbabwe's 10 provinces. Names follow the rural district
# councils used in ZimStat provincial tables and the Ministry of Local Government
# lists. Urban councils that share a rural district name are not separate rows.
PROVINCES = [
    {"name": "Manicaland", "code": "MN", "aliases": ["MANICALAND"]},
    {"name": "Mashonaland Central", "code": "MC", "aliases": ["MASHCENTRAL"]},
    {"name": "Mashonaland East", "code": "ME", "aliases": ["MASHEAST"]},
    {"name": "Mashonaland West", "code": "MW", "aliases": ["MASHWEST"]},
    {"name": "Masvingo", "code": "MV", "aliases": []},
    {"name": "Matabeleland North", "code": "MNO", "aliases": []},
    {"name": "Matabeleland South", "code": "MS", "aliases": ["MATABELELAND SOUTH", "MATEBELELAND SOUTH"]},
    {"name": "Midlands", "code": "MD", "aliases": ["MIDLANDS", "MIDLADS"]},
    {"name": "Harare Metropolitan", "code": "HRE", "aliases": ["Harare", "HARARE"]},
    {"name": "Bulawayo Metropolitan", "code": "BYO", "aliases": ["Bulawayo", "BULAWAYO"]},
]

DISTRICTS = {
    "Manicaland": ["Buhera", "Chimanimani", "Chipinge", "Makoni", "Mutare", "Mutasa", "Nyanga"],
    "Mashonaland Central": ["Bindura", "Guruve", "Mazowe", "Mbire", "Mount Darwin", "Muzarabani", "Rushinga", "Shamva"],
    "Mashonaland East": ["Chikomba", "Goromonzi", "Hwedza", "Marondera", "Mudzi", "Murehwa", "Mutoko", "Seke", "Uzumba-Maramba-Pfungwe"],
    "Mashonaland West": ["Chegutu", "Hurungwe", "Kariba", "Makonde", "Mhondoro-Ngezi", "Sanyati", "Zvimba"],
    "Masvingo": ["Bikita", "Chiredzi", "Chivi", "Gutu", "Masvingo", "Mwenezi", "Zaka"],
    "Matabeleland North": ["Binga", "Bubi", "Hwange", "Lupane", "Nkayi", "Tsholotsho", "Umguza"],
    "Matabeleland South": ["Beitbridge", "Bulilima", "Gwanda", "Insiza", "Mangwe", "Matobo", "Umzingwane"],
    "Midlands": ["Chirumhanzu", "Gokwe North", "Gokwe South", "Gweru", "Kwekwe", "Mberengwa", "Shurugwi", "Zvishavane"],
    "Harare Metropolitan": ["Harare", "Chitungwiza", "Epworth"],
    "Bulawayo Metropolitan": ["Bulawayo"],
}

# Present in farmer records. Kadoma Municipality is not the same place as Sanyati.
RETAINED_EXTRA_DISTRICTS = {
    "Mashonaland West": ["Kadoma"],
}

LEGACY_UNUSED_DISTRICTS = ["Bulilimamangwe"]


def normalize_name(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _new_summary():
    return {
        "provinces_added": [],
        "provinces_renamed": [],
        "districts_added": [],
        "districts_repointed": [],
        "districts_deactivated": [],
        "provinces_deactivated": [],
        "skipped": [],
        "review": [],
    }


def _district_names(province_name):
    return list(DISTRICTS.get(province_name, []))


def _official_district_keys():
    keys = {}
    for province_name, names in DISTRICTS.items():
        for name in names:
            keys[normalize_name(name)] = province_name
    for province_name, names in RETAINED_EXTRA_DISTRICTS.items():
        for name in names:
            keys[normalize_name(name)] = province_name
    return keys


def _province_in_use(province):
    from apps.accounts.models import User
    from apps.clusters.models import Cluster
    from apps.farmers.models import Farm, Farmer
    from apps.recovery.models import InputDebt

    return (
        Farmer.objects.filter(province=province).exists()
        or Farm.objects.filter(province=province).exists()
        or Cluster.objects.filter(province=province).exists()
        or User.objects.filter(province=province).exists()
        or InputDebt.objects.filter(province=province).exists()
    )


def _district_in_use(district):
    from apps.accounts.models import User
    from apps.clusters.models import Cluster
    from apps.farmers.models import Farm, Farmer
    from apps.recovery.models import InputDebt

    return (
        Farmer.objects.filter(district=district).exists()
        or Farm.objects.filter(district=district).exists()
        or Cluster.objects.filter(district=district).exists()
        or User.objects.filter(district=district).exists()
        or InputDebt.objects.filter(district=district).exists()
        or district.wards.exists()
    )


def _repoint_district(source, target, summary):
    from apps.accounts.models import User
    from apps.clusters.models import Cluster
    from apps.farmers.models import Farm, Farmer
    from apps.geography.models import Ward
    from apps.recovery.models import InputDebt

    if source.pk == target.pk:
        return
    Farmer.objects.filter(district=source).update(district=target, province=target.province)
    Farm.objects.filter(district=source).update(district=target, province=target.province)
    Cluster.objects.filter(district=source).update(district=target, province=target.province)
    User.objects.filter(district=source).update(district=target, province=target.province)
    InputDebt.objects.filter(district=source).update(district=target, province=target.province)
    for ward in list(source.wards.all()):
        if Ward.objects.filter(district=target, name__iexact=ward.name).exists():
            summary["review"].append(
                f"Ward {ward.name} on {source} was not moved because {target} already has that ward."
            )
        else:
            ward.district = target
            ward.save(update_fields=["district", "updated_at"])
    summary["districts_repointed"].append(f"{source.province.name} / {source.name} -> {target.province.name} / {target.name}")
    if source.active and not _district_in_use(source):
        source.active = False
        source.save(update_fields=["active", "updated_at"])
        summary["districts_deactivated"].append(f"{source.province.name} / {source.name}")


def _ensure_district(province, district_name, summary):
    key = normalize_name(district_name)
    match = None
    for district in province.districts.all():
        if normalize_name(district.name) == key:
            match = district
            break
    if match is None:
        match = District.objects.create(
            province=province,
            name=district_name,
            code=re.sub(r"[^A-Za-z0-9]", "", district_name)[:6].upper(),
            active=True,
        )
        summary["districts_added"].append(f"{province.name} / {district_name}")
        return match
    updates = []
    if match.name != district_name and not province.districts.filter(name=district_name).exclude(pk=match.pk).exists():
        match.name = district_name
        updates.append("name")
    if not match.active and district_name not in LEGACY_UNUSED_DISTRICTS:
        match.active = True
        updates.append("active")
    if updates:
        updates.append("updated_at")
        match.save(update_fields=updates)
    return match


@transaction.atomic
def sync_zimbabwe_geography():
    summary = _new_summary()
    district_home = _official_district_keys()
    alias_keys = set()
    keepers = {}

    for spec in PROVINCES:
        keys = {normalize_name(spec["name"]), *[normalize_name(alias) for alias in spec["aliases"]]}
        alias_keys.update(keys)
        candidates = [province for province in Province.objects.all() if normalize_name(province.name) in keys]
        exact = [province for province in candidates if normalize_name(province.name) == normalize_name(spec["name"])]
        if exact:
            keeper = min(exact, key=lambda province: province.id)
        elif candidates:
            keeper = max(candidates, key=lambda province: (province.farmers.count(), -province.id))
        else:
            keeper = Province.objects.create(name=spec["name"], code=spec["code"], official=True, active=True)
            summary["provinces_added"].append(spec["name"])
        if keeper.name != spec["name"]:
            summary["provinces_renamed"].append(f"{keeper.name} -> {spec['name']}")
            keeper.name = spec["name"]
        if keeper.code != spec["code"] and not Province.objects.filter(code=spec["code"]).exclude(pk=keeper.pk).exists():
            keeper.code = spec["code"]
        keeper.official = True
        keeper.active = True
        keeper.save()
        keepers[spec["name"]] = keeper
        for district_name in _district_names(spec["name"]):
            _ensure_district(keeper, district_name, summary)

    for district in list(District.objects.select_related("province")):
        if not district.active and not _district_in_use(district):
            continue
        home_name = district_home.get(normalize_name(district.name))
        if not home_name:
            continue
        keeper = keepers[home_name]
        canonical_name = next(
            name
            for name in [*_district_names(home_name), *RETAINED_EXTRA_DISTRICTS.get(home_name, [])]
            if normalize_name(name) == normalize_name(district.name)
        )
        target = _ensure_district(keeper, canonical_name, summary)
        if district.province_id != keeper.id or district.id != target.id:
            _repoint_district(district, target, summary)

    for province in Province.objects.exclude(official=True):
        if normalize_name(province.name) in alias_keys and not _province_in_use(province):
            if province.active:
                province.active = False
                province.save(update_fields=["active", "updated_at"])
                summary["provinces_deactivated"].append(province.name)

    for legacy_name in LEGACY_UNUSED_DISTRICTS:
        for district in District.objects.filter(name__iexact=legacy_name):
            if _district_in_use(district):
                summary["review"].append(
                    f"{district.province.name} / {district.name} is a legacy combined district. Bulilima and Mangwe were added separately. It was left in place because records still reference it."
                )
            elif district.active:
                district.active = False
                district.save(update_fields=["active", "updated_at"])
                summary["districts_deactivated"].append(f"{district.province.name} / {district.name}")
                summary["review"].append(
                    f"{district.name} is the former combined district. It was deactivated, not deleted. Bulilima and Mangwe are the current districts."
                )

    official_keys = set(district_home)
    for district in District.objects.select_related("province").filter(active=True):
        key = normalize_name(district.name)
        if key in {"unknown", "nk"}:
            summary["review"].append(f"{district.province.name} / {district.name} is not an official district and was left unchanged.")
            continue
        if not district.province.official:
            if district.farmers.exists() or district.farms.exists():
                summary["review"].append(
                    f"{district.province.name} / {district.name} still has farmer or farm records and was not merged."
                )
            continue
        if key not in official_keys:
            summary["review"].append(
                f"{district.province.name} / {district.name} is not in the official district list and was left unchanged."
            )
        elif district_home[key] != district.province.name:
            summary["review"].append(
                f"{district.province.name} / {district.name} does not match the official province {district_home[key]}."
            )

    for province_name, names in RETAINED_EXTRA_DISTRICTS.items():
        for name in names:
            if District.objects.filter(province__name=province_name, name__iexact=name, active=True).exists():
                summary["review"].append(
                    f"{province_name} / {name} was kept because existing records use it. It is Kadoma Municipality, not a duplicate of Sanyati."
                )
    return summary
