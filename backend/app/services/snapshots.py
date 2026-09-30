"""Explicit persistence of server-issued previews; never updates products."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import secrets
import sqlite3
import threading
import time

from app.core.database import get_connection
from app.services.bol import BolError


class PreviewStore:
    """Bounded process-local receipts; restart/expiry requires a fresh preview."""
    def __init__(self, clock=time.monotonic, ttl=900, capacity=256):
        self.clock, self.ttl, self.capacity = clock, ttl, capacity
        self.items = {}
        self.lock = threading.Lock()

    def issue(self, preview):
        with self.lock:
            now = self.clock()
            self.items = {k: v for k, v in self.items.items() if v[0] > now}
            while len(self.items) >= self.capacity:
                self.items.pop(next(iter(self.items)))
            receipt = secrets.token_urlsafe(32)
            self.items[receipt] = (now + self.ttl, deepcopy(preview))
            return receipt

    def get(self, receipt):
        with self.lock:
            item = self.items.get(receipt)
            if item is None or item[0] <= self.clock():
                self.items.pop(receipt, None)
                raise BolError(410, "Dit voorbeeld is verlopen. Haal eerst een nieuw voorbeeld op.")
            return deepcopy(item[1])


previews = PreviewStore()


def migrate_snapshots(db):
    # Additive, transactional and repeatable: no alterations to existing tables.
    db.execute("""CREATE TABLE IF NOT EXISTS bol_product_identities (
        ean TEXT PRIMARY KEY CHECK(length(ean) = 13),
        bol_product_id TEXT,
        created_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS bol_product_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        preview_id TEXT NOT NULL UNIQUE,
        ean TEXT NOT NULL REFERENCES bol_product_identities(ean),
        measured_at TEXT NOT NULL,
        saved_at TEXT NOT NULL,
        source TEXT NOT NULL,
        api_version TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('complete', 'partial')),
        payload TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS bol_snapshots_ean_measured
                  ON bol_product_snapshots(ean, measured_at DESC, id DESC)""")

    db.execute("""CREATE TABLE IF NOT EXISTS bol_market_snapshots (
        snapshot_id INTEGER PRIMARY KEY REFERENCES bol_product_snapshots(id),
        ean TEXT NOT NULL REFERENCES bol_product_identities(ean),
        measured_at TEXT NOT NULL,
        source TEXT NOT NULL,
        api_version TEXT NOT NULL,
        country TEXT NOT NULL,
        condition TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('complete', 'partial', 'unavailable')),
        payload TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS bol_market_ean_segment_time
                  ON bol_market_snapshots(ean, country, condition, measured_at DESC)""")


def serialize(row):
    return {"id": row["id"], "saved_at": row["saved_at"],
            "preview": json.loads(row["payload"])}


def save_snapshot(receipt):
    try:
        with get_connection() as db:
            # Serialize writers so concurrent retries create only one snapshot.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM bol_product_snapshots WHERE preview_id = ?", (receipt,)).fetchone()
            if existing:
                return serialize(existing)
            preview = previews.get(receipt)
            now = datetime.now(timezone.utc).isoformat()
            db.execute("""INSERT INTO bol_product_identities(ean, bol_product_id, created_at)
                          VALUES (?, ?, ?) ON CONFLICT(ean) DO NOTHING""",
                       (preview["ean"], preview["bol_product_id"], now))
            # Only fill an unknown identity; later conflicting IDs stay in snapshots.
            db.execute("""UPDATE bol_product_identities SET bol_product_id = ?
                          WHERE ean = ? AND bol_product_id IS NULL""",
                       (preview["bol_product_id"], preview["ean"]))
            cursor = db.execute("""INSERT INTO bol_product_snapshots
                (preview_id, ean, measured_at, saved_at, source, api_version, status, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (receipt, preview["ean"], preview["fetched_at"], now, preview["source"],
                 preview["api_version"], preview["status"], json.dumps(preview, ensure_ascii=False)))
            market = preview.get("market")
            if market is not None:
                db.execute("""INSERT INTO bol_market_snapshots
                    (snapshot_id, ean, measured_at, source, api_version, country, condition, status, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cursor.lastrowid, preview["ean"], market["measured_at"], market["source"],
                     market["api_version"], market["country"], market["condition"], market["status"],
                     json.dumps(market, ensure_ascii=False)))
            row = db.execute("SELECT * FROM bol_product_snapshots WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return serialize(row)
    except sqlite3.Error:
        raise BolError(503, "Opslaan is tijdelijk niet beschikbaar. Probeer het opnieuw.") from None


def history(ean):
    try:
        with get_connection() as db:
            identity = db.execute("SELECT * FROM bol_product_identities WHERE ean = ?", (ean,)).fetchone()
            rows = db.execute("""SELECT * FROM bol_product_snapshots WHERE ean = ?
                                 ORDER BY measured_at DESC, id DESC LIMIT 50""", (ean,)).fetchall()
            return {"identity": dict(identity) if identity else None,
                    "snapshots": [serialize(row) for row in rows]}
    except sqlite3.Error:
        raise BolError(503, "Snapshotgeschiedenis is tijdelijk niet beschikbaar.") from None
