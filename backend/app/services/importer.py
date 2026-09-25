from __future__ import annotations

import csv
import math
from io import StringIO


REQUIRED_COLUMNS = {
    "name",
    "category",
    "sale_price",
    "purchase_price",
}


def parse_csv(content: str) -> list[dict]:
    reader = csv.DictReader(StringIO(content))

    if not reader.fieldnames:
        raise ValueError("CSV bevat geen kolomnamen")

    reader.fieldnames = [column.strip() for column in reader.fieldnames]
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("CSV bevat dubbele kolomnamen")
    columns = set(reader.fieldnames)

    missing = REQUIRED_COLUMNS - columns

    if missing:
        raise ValueError(
            "Verplichte kolommen ontbreken: "
            + ", ".join(sorted(missing))
        )

    products: list[dict] = []

    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"Regel {row_number}: te veel waarden voor de kolommen")
        name = (row.get("name") or "").strip()
        category = (row.get("category") or "").strip()

        if not name:
            raise ValueError(
                f"Regel {row_number}: productnaam ontbreekt"
            )

        if not category:
            raise ValueError(
                f"Regel {row_number}: categorie ontbreekt"
            )

        try:
            product = {
                "name": name,
                "category": category,
                "brand": (row.get("brand") or "").strip(),
                "ean": (row.get("ean") or "").strip(),
                "sale_price": float(row["sale_price"]),
                "purchase_price": float(row["purchase_price"]),
                "shipping_cost": float(
                    row.get("shipping_cost") or 0
                ),
                "commission_rate": float(
                    row.get("commission_rate") or 15
                ),
                "monthly_sales_low": int(
                    row.get("monthly_sales_low") or 0
                ),
                "monthly_sales_high": int(
                    row.get("monthly_sales_high") or 0
                ),
                "sellers": int(row.get("sellers") or 0),
                "reviews": int(row.get("reviews") or 0),
                "review_growth": float(
                    row.get("review_growth") or 0
                ),
                "trend": float(row.get("trend") or 0),
                "risk_level": int(
                    row.get("risk_level") or 50
                ),
                "confidence": int(
                    row.get("confidence") or 50
                ),
            }
        except (TypeError, ValueError):
            raise ValueError(
                f"Regel {row_number}: ongeldige numerieke waarde"
            )

        if any(isinstance(value, float) and not math.isfinite(value)
               for value in product.values()):
            raise ValueError(f"Regel {row_number}: ongeldige numerieke waarde")

        products.append(product)

    if not products:
        raise ValueError("CSV bevat geen producten")

    return products
    