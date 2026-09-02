from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core.database import get_connection
from app.services.importer import parse_csv
from app.services.scoring import calculate_scores

router = APIRouter(prefix="/products", tags=["products"])


def serialize(row) -> dict:
    product = dict(row)
    product["favorite"] = bool(product["favorite"])
    product["analysis"] = calculate_scores(product)
    return product


@router.get("")
def list_products(
    search: str = Query(default=""),
    category: str = Query(default=""),
) -> list[dict]:
    query = "SELECT * FROM products WHERE 1=1"
    params: list[object] = []

    if search:
        query += (
            " AND (LOWER(name) LIKE ? "
            "OR LOWER(brand) LIKE ? "
            "OR ean LIKE ?)"
        )
        term = f"%{search.lower()}%"
        params.extend([term, term, f"%{search}%"])

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY favorite DESC, id ASC"

    with get_connection() as db:
        return [
            serialize(row)
            for row in db.execute(query, params).fetchall()
        ]


@router.get("/{product_id}")
def get_product(product_id: int) -> dict:
    with get_connection() as db:
        row = db.execute(
            "SELECT * FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Product niet gevonden",
        )

    return serialize(row)


@router.post("/{product_id}/favorite")
def toggle_favorite(product_id: int) -> dict:
    with get_connection() as db:
        row = db.execute(
            "SELECT favorite FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Product niet gevonden",
            )

        value = 0 if row["favorite"] else 1

        db.execute(
            "UPDATE products SET favorite = ? WHERE id = ?",
            (value, product_id),
        )

    return {
        "id": product_id,
        "favorite": bool(value),
    }


@router.post("/import/preview")
async def preview_import(
    file: UploadFile = File(...),
) -> dict:
    if (
        not file.filename
        or not file.filename.lower().endswith(".csv")
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload een CSV-bestand",
        )

    content = await file.read()

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="CSV moet UTF-8 gecodeerd zijn",
        )

    try:
        products = parse_csv(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "filename": file.filename,
        "product_count": len(products),
        "preview": products[:5],
    }


@router.post("/import")
async def import_products(
    file: UploadFile = File(...),
) -> dict:
    if (
        not file.filename
        or not file.filename.lower().endswith(".csv")
    ):
        raise HTTPException(
            status_code=400,
            detail="Upload een CSV-bestand",
        )

    content = await file.read()

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="CSV moet UTF-8 gecodeerd zijn",
        )

    try:
        products = parse_csv(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    imported_count = 0
    skipped_count = 0

    with get_connection() as db:
        for product in products:
            if product["ean"]:
                existing = db.execute(
                    "SELECT id FROM products WHERE ean = ?",
                    (product["ean"],),
                ).fetchone()

                if existing:
                    skipped_count += 1
                    continue

            db.execute(
                """
                INSERT INTO products (
                    name,
                    category,
                    brand,
                    ean,
                    sale_price,
                    purchase_price,
                    shipping_cost,
                    commission_rate,
                    monthly_sales_low,
                    monthly_sales_high,
                    sellers,
                    reviews,
                    review_growth,
                    trend,
                    risk_level,
                    confidence
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    product["name"],
                    product["category"],
                    product["brand"],
                    product["ean"],
                    product["sale_price"],
                    product["purchase_price"],
                    product["shipping_cost"],
                    product["commission_rate"],
                    product["monthly_sales_low"],
                    product["monthly_sales_high"],
                    product["sellers"],
                    product["reviews"],
                    product["review_growth"],
                    product["trend"],
                    product["risk_level"],
                    product["confidence"],
                ),
            )

            imported_count += 1

    return {
        "filename": file.filename,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "message": (
            f"{imported_count} producten geïmporteerd, "
            f"{skipped_count} overgeslagen"
        ),
    }