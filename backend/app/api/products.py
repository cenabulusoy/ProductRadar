from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_connection
from app.services.scoring import calculate_scores

router = APIRouter(prefix="/products", tags=["products"])


def serialize(row) -> dict:
    product = dict(row)
    product["favorite"] = bool(product["favorite"])
    product["analysis"] = calculate_scores(product)
    return product


@router.get("")
def list_products(search: str = Query(default=""), category: str = Query(default="")) -> list[dict]:
    query = "SELECT * FROM products WHERE 1=1"
    params: list[object] = []
    if search:
        query += " AND (LOWER(name) LIKE ? OR LOWER(brand) LIKE ? OR ean LIKE ?)"
        term = f"%{search.lower()}%"
        params.extend([term, term, f"%{search}%"])
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY favorite DESC, id ASC"
    with get_connection() as db:
        return [serialize(row) for row in db.execute(query, params).fetchall()]


@router.get("/{product_id}")
def get_product(product_id: int) -> dict:
    with get_connection() as db:
        row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product niet gevonden")
    return serialize(row)


@router.post("/{product_id}/favorite")
def toggle_favorite(product_id: int) -> dict:
    with get_connection() as db:
        row = db.execute("SELECT favorite FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Product niet gevonden")
        value = 0 if row["favorite"] else 1
        db.execute("UPDATE products SET favorite = ? WHERE id = ?", (value, product_id))
    return {"id": product_id, "favorite": bool(value)}
