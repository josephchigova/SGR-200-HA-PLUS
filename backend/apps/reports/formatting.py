import csv
import io
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


def quantize(value, places):
    if value is None or value == "":
        return None
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    step = Decimal("1").scaleb(-places)
    return amount.quantize(step, rounding=ROUND_HALF_UP)


def format_value(value, kind):
    if value is None or value == "":
        return ""
    if kind == "bool":
        return "Yes" if value else "No"
    if kind == "month":
        if isinstance(value, datetime):
            return value.strftime("%Y-%m")
        if isinstance(value, date):
            return value.strftime("%Y-%m")
        return str(value)[:7]
    if kind == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10]
    if kind == "datetime":
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        if isinstance(value, date):
            return value.isoformat()
        return str(value)
    if kind == "money":
        amount = quantize(value, 2)
        return "" if amount is None else f"{amount:.2f}"
    if kind == "qty":
        amount = quantize(value, 2)
        return "" if amount is None else f"{amount:.2f}"
    if kind == "qty3":
        amount = quantize(value, 3)
        return "" if amount is None else f"{amount:.3f}"
    if kind == "rate":
        amount = quantize(value, 4)
        return "" if amount is None else f"{amount:.4f}"
    return str(value)


def csv_safe(value, kind):
    text = format_value(value, kind)
    if kind in {"money", "qty", "qty3", "rate"}:
        return text
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def csv_document(columns, rows):
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow([column.label for column in columns])
    for row in rows:
        writer.writerow([csv_safe(row.get(column.key), column.kind) for column in columns])
    return buffer.getvalue()
