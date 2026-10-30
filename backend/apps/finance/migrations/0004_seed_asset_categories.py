from django.db import migrations


CATEGORIES = [
    ("Vehicles", "Cars, trucks, motorcycles and other vehicles."),
    ("Computers and IT Equipment", "Computers, printers, networking and other IT equipment."),
    ("Office Furniture", "Desks, chairs, cabinets and other office furniture."),
    ("Machinery and Equipment", "Workshop machinery and general equipment."),
    ("Buildings and Property", "Buildings, land and other property."),
    ("Agricultural Equipment", "Equipment used in agricultural operations."),
    ("Other", "Assets that do not fit another category."),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model("finance", "AssetCategory")
    Asset = apps.get_model("finance", "Asset")
    for name, description in CATEGORIES:
        Category.objects.get_or_create(name=name, defaults={"description": description, "is_active": True})
    for asset in Asset.objects.exclude(category="").filter(category_ref__isnull=True):
        match = Category.objects.filter(name__iexact=asset.category).first()
        if match:
            asset.category_ref_id = match.pk
            asset.save(update_fields=["category_ref"])


def remove_unused_seed_categories(apps, schema_editor):
    Category = apps.get_model("finance", "AssetCategory")
    names = [name for name, _description in CATEGORIES]
    Category.objects.filter(name__in=names, assets__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0003_asset_register"),
    ]

    operations = [
        migrations.RunPython(seed_categories, remove_unused_seed_categories),
    ]
