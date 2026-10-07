"""Separate read-only v2 financial output; never changes legacy product inputs."""
from datetime import datetime, timezone
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field, model_validator

from app.analysis.financial_v2 import FinancialInputs, Model, calculate_financial
from app.core import database
from app.services.bol import BolError, validate_ean
from app.services.freshness import load_market_records

router = APIRouter(prefix="/financial/v2", tags=["financial v2"])


class FinancialRequest(Model):
    inputs: FinancialInputs
    ean: str | None = None
    market_snapshot_id: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def identity(self):
        if self.market_snapshot_id is not None and self.ean is None:
            raise ValueError("EAN required for a market snapshot")
        if self.ean is not None:
            try:
                validate_ean(self.ean)
            except BolError:
                raise ValueError("Invalid EAN") from None
        return self


def read_market(ean, snapshot_id):
    if ean is None:
        return None, None
    if not database.DB_PATH.exists():
        if snapshot_id is not None:
            raise HTTPException(404, "Marktsnapshot niet gevonden voor deze EAN.")
        return None, None
    try:
        # No startup, schema migration, mkdir or database creation on this route.
        db = sqlite3.connect(database.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bol_market_snapshots'").fetchone()
            row = None
            if exists:
                if snapshot_id is not None:
                    row = db.execute("SELECT snapshot_id, payload FROM bol_market_snapshots WHERE ean=? AND snapshot_id=?",
                                     (ean, snapshot_id)).fetchone()
                else:
                    row = db.execute("""SELECT snapshot_id, payload FROM bol_market_snapshots WHERE ean=?
                                         ORDER BY measured_at DESC, snapshot_id DESC LIMIT 1""", (ean,)).fetchone()
            if snapshot_id is None:
                records = load_market_records(db, ean)
                return (records[0]['payload'], records[0]['id'] or None) if records else (None, None)
            if row is None:
                if snapshot_id is not None:
                    raise HTTPException(404, "Marktsnapshot niet gevonden voor deze EAN.")
                return None, None
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                payload = {}
            return payload, row["snapshot_id"]
        finally:
            db.close()
    except sqlite3.Error:
        raise HTTPException(503, "Opgeslagen marktdata is tijdelijk niet beschikbaar.") from None


@router.post("/calculate")
def financial_output(body: FinancialRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    payload, snapshot_id = read_market(body.ean, body.market_snapshot_id)
    try:
        result = calculate_financial(body.inputs, as_of=datetime.now(timezone.utc),
                                     market_payload=payload, snapshot_id=snapshot_id)
    except ValueError:
        raise HTTPException(422, "Financiële invoer bevat ongeldige of toekomstige brongegevens.") from None
    return {"ean": body.ean, "v2_financial": result}
