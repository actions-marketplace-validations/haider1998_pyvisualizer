"""Shared helpers. `clean` here collides with app.legacy.clean."""


def scrub(row):
    return {k: v for k, v in row.items() if v is not None}


def clean(row):
    row["amount"] = max(0, row.get("amount", 0))
    return row
