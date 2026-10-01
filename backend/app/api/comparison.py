"""GET-only comparison/evaluation over saved data. Never initializes the user database."""
from datetime import datetime, timezone
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Response

from app.core import database
from app.services.comparison import compare_saved_product

router = APIRouter(prefix='/comparison', tags=['decision comparison'])


def read_products(product_id=None, offset=0, limit=25):
    if not database.DB_PATH.exists():
        return [], 0
    try:
        db = sqlite3.connect(database.DB_PATH.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products'").fetchone():
                return [], 0
            if product_id is not None:
                rows = db.execute('SELECT * FROM products WHERE id=?', (product_id,)).fetchall()
                return [dict(row) for row in rows], len(rows)
            total = db.execute('SELECT COUNT(*) FROM products').fetchone()[0]
            rows = db.execute('SELECT * FROM products ORDER BY id ASC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            return [dict(row) for row in rows], total
        finally:
            db.close()
    except sqlite3.Error:
        raise HTTPException(503, 'Opgeslagen producten zijn tijdelijk niet beschikbaar.') from None


@router.get('/products')
def evaluation(response: Response, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=50)):
    response.headers['Cache-Control'] = 'no-store'
    products, total = read_products(offset=offset, limit=limit)
    as_of = datetime.now(timezone.utc)
    items = []
    for product in products:
        try:
            items.append(compare_saved_product(product, as_of))
        except (HTTPException, ValueError, TypeError, KeyError, ArithmeticError):
            # One corrupt product/measurement must not silently disappear or suppress other products.
            items.append({'product': {'id': product['id'], 'name': product['name']},
                          'error': 'Vergelijking niet beschikbaar. Controleer de opgeslagen brongegevens.'})
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit,
            'next_offset': offset+limit if offset+limit < total else None,
            'order': 'product_id_ascending', 'evaluated_at': as_of.isoformat()}


@router.get('/products/{product_id}')
def comparison(product_id: int, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    products, _ = read_products(product_id=product_id)
    if not products:
        raise HTTPException(404, 'Product niet gevonden.')
    try:
        return compare_saved_product(products[0], datetime.now(timezone.utc))
    except (ValueError, TypeError, KeyError, ArithmeticError):
        raise HTTPException(422, 'Vergelijking niet beschikbaar. Controleer de opgeslagen brongegevens.') from None
