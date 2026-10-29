from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

COORDINATE_QUANTUM = Decimal("0.000001")


def clean_coordinate_pair(latitude, longitude):
    latitude_empty = latitude is None or latitude == ""
    longitude_empty = longitude is None or longitude == ""
    if latitude_empty and longitude_empty:
        return None, None
    if latitude_empty or longitude_empty:
        raise ValueError("Enter both latitude and longitude, or leave both empty.")
    return (
        _clean_coordinate(latitude, "Latitude", Decimal("-90"), Decimal("90")),
        _clean_coordinate(longitude, "Longitude", Decimal("-180"), Decimal("180")),
    )


def _clean_coordinate(value, label, lower, upper):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if number < lower or number > upper:
        raise ValueError(f"{label} must be between {lower} and {upper}.")
    return number.quantize(COORDINATE_QUANTUM, rounding=ROUND_HALF_UP)
