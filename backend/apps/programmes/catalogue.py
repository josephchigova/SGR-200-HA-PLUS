from apps.programmes.models import Crop

# Names and seasons only. Rates, prices, programmes, farmers and wards are not inserted.
PREDEFINED_CROPS = (
    ("Maize", Crop.CATEGORY_SUMMER),
    ("Sorghum", Crop.CATEGORY_SUMMER),
    ("Wheat", Crop.CATEGORY_WINTER),
)


def ensure_predefined_crops():
    """Insert missing catalogue crops. Existing crops, prices and input rows stay as saved."""
    created = []
    unchanged = []
    for name, category in PREDEFINED_CROPS:
        existing = Crop.objects.filter(name__iexact=name).order_by("id").first()
        if existing is not None:
            unchanged.append(existing.name)
            continue
        Crop.objects.create(name=name, category=category, active=True)
        created.append(name)
    return {"created": created, "unchanged": unchanged}
