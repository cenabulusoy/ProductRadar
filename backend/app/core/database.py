from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "productradar.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT NOT NULL DEFAULT '',
                ean TEXT NOT NULL DEFAULT '',
                sale_price REAL NOT NULL,
                purchase_price REAL NOT NULL,
                shipping_cost REAL NOT NULL DEFAULT 0,
                commission_rate REAL NOT NULL DEFAULT 15,
                monthly_sales_low INTEGER NOT NULL DEFAULT 0,
                monthly_sales_high INTEGER NOT NULL DEFAULT 0,
                sellers INTEGER NOT NULL DEFAULT 0,
                reviews INTEGER NOT NULL DEFAULT 0,
                review_growth REAL NOT NULL DEFAULT 0,
                trend REAL NOT NULL DEFAULT 0,
                risk_level INTEGER NOT NULL DEFAULT 50,
                confidence INTEGER NOT NULL DEFAULT 50,
                favorite INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        count = db.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        if count == 0:
            db.executemany(
                """
                INSERT INTO products (
                    name, category, brand, sale_price, purchase_price, shipping_cost,
                    commission_rate, monthly_sales_low, monthly_sales_high, sellers,
                    reviews, review_growth, trend, risk_level, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                SEED_PRODUCTS,
            )


SEED_PRODUCTS = [
    ("WD-40 Smart Straw 400 ml", "Automotive", "WD-40", 14.95, 7.10, 4.25, 15, 170, 260, 18, 1840, 3.8, 6.0, 38, 68),
    ("Werkhandschoenen nitril 12 paar", "Gereedschap", "ProGrip", 24.95, 9.80, 4.25, 15, 110, 190, 11, 426, 5.2, 8.0, 32, 62),
    ("EHBO-kit DIN 13164", "Automotive", "SafeRoad", 19.95, 7.25, 4.25, 15, 95, 155, 8, 318, 4.1, 4.0, 24, 65),
    ("Ventieldoppenset aluminium 4-delig", "Automotive", "RoadStyle", 12.95, 2.10, 3.95, 15, 70, 150, 23, 205, 6.8, 10.0, 58, 55),
    ("Automattenset universeel 4-delig", "Automotive", "AutoFit", 34.95, 14.40, 6.95, 15, 45, 90, 14, 167, 2.3, 1.0, 47, 52),
]
