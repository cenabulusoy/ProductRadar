"""Read-only v2 scoring adapter. No credentials, live requests, writes or migrations."""
from datetime import datetime, timezone
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Response
from pydantic import model_validator

from app.analysis.scoring_v2 import ScoringInputs, calculate_decision
from app.analysis.financial_v2 import Model
from app.core import database
from app.services.bol import BolError, validate_ean

router = APIRouter(prefix="/decision/v2", tags=["decision v2"])


class DecisionRequest(Model):
    ean: str
    inputs: ScoringInputs

    @model_validator(mode="after")
    def valid_ean(self):
        try:
            validate_ean(self.ean)
        except BolError:
            raise ValueError("Invalid EAN") from None
        return self


def read_evidence(ean):
    if not database.DB_PATH.exists():
        return None, [], []
    try:
        db = sqlite3.connect(database.DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")  # A consistent read transaction across all three tables.
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            identity = None
            if "bol_product_identities" in tables:
                row = db.execute("SELECT ean, bol_product_id, created_at FROM bol_product_identities WHERE ean=?", (ean,)).fetchone()
                identity = dict(row) if row else None

            def load(table, key):
                if table not in tables:
                    return []
                # Fixed table/column constants only; user EAN remains parameterized.
                rows = db.execute(f"SELECT {key} AS id, measured_at, payload FROM {table} WHERE ean=? ORDER BY measured_at DESC, {key} DESC LIMIT 2001", (ean,)).fetchall()
                if len(rows) > 2000:
                    raise HTTPException(422, "Te veel snapshots voor deze analyse; expliciete historie-selectie is nodig.")
                result = []
                for row in rows:
                    try:
                        payload = json.loads(row["payload"])
                    except (ValueError, TypeError):
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    # Freeze only known domain fields, never arbitrary stored transport data.
                    allowed = ({"ean", "source", "api_version", "language", "fetched_at", "catalog", "bol_product_id",
                                "endpoints", "ratings", "status", "field_completeness"} if table == "bol_product_snapshots" else
                               {"source", "api_version", "endpoint", "country", "condition", "currency", "measured_at",
                                "status", "pagination_complete", "offers"})
                    result.append({"id": row["id"], "measured_at": row["measured_at"],
                                   "payload": {k: v for k, v in payload.items() if k in allowed}})
                return result
            return identity, load("bol_product_snapshots", "id"), load("bol_market_snapshots", "snapshot_id")
        finally:
            db.close()
    except sqlite3.Error:
        raise HTTPException(503, "Opgeslagen bronmetingen zijn tijdelijk niet beschikbaar.") from None


@router.post("/analyze")
def analyze(body: DecisionRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    identity, products, markets = read_evidence(body.ean)
    try:
        result = calculate_decision(body.inputs, as_of=datetime.now(timezone.utc), ean=body.ean,
                                    identity=identity, product_snapshots=products, market_snapshots=markets)
    except ValueError:
        raise HTTPException(422, "De analyse bevat ongeldige of toekomstige brongegevens.") from None
    return {"ean": body.ean, "analysis_v2": result}
