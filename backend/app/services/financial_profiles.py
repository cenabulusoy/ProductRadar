"""Append-only financial inputs and explicit proposals; no legacy product updates."""
from datetime import datetime, timezone
from contextlib import contextmanager
from decimal import Decimal
from hashlib import sha256
import json
import sqlite3
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.analysis.financial_v2 import Model, CostInput, FinancialInputs, effective_cost, calculate_financial, market_reference
from app.analysis.scoring_v2 import ScoringInputs
from app.api.financial import read_market
from app.core import database
from app.services.snapshots import PreviewStore


class Breakdown(Model):
    purchase_cost: CostInput | None = None
    inbound_cost: CostInput | None = None
    shipping_cost: CostInput | None = None
    packaging_cost: CostInput | None = None
    handling_cost: CostInput | None = None


class Reference(Model):
    import_reference: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    snapshot_id: int | None = Field(default=None, gt=0, strict=True)
    rule_reference: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")


class Profile(Model):
    schema_version: Literal['1'] = '1'
    financial: FinancialInputs
    breakdown: Breakdown = Field(default_factory=Breakdown)
    references: dict[str, Reference] = Field(default_factory=dict)

    @model_validator(mode='after')
    def consistent(self):
        if self.financial.scenario_mode != 'conservative':
            raise ValueError('Stored profile must use the conservative scenario')
        allowed = set(input_groups(self))
        if any(key not in allowed for key in self.references):
            raise ValueError('Reference must belong to an existing input group')
        for total, names in [('landed_purchase_cost', ('purchase_cost','inbound_cost')),
                             ('fulfilment_cost', ('shipping_cost','packaging_cost','handling_cost'))]:
            items = [getattr(self.breakdown, key) for key in names]
            if not any(item is not None for item in items):
                continue
            calculated = cost_sum(items)
            target = getattr(self.financial, total)
            amount = normalize_cost(target)
            if amount is not None:
                if calculated is None:
                    raise ValueError('A confirmed total with breakdown requires every component, including explicit zeros')
                if abs(amount - calculated) > Decimal('0.0001'):
                    raise ValueError('Confirmed total does not match its economic cost breakdown')
        return self


def input_groups(profile):
    groups = {}
    for key in type(profile.financial).model_fields:
        item = getattr(profile.financial, key)
        if hasattr(item, 'provenance'):
            groups['financial.'+key] = item
            if key == 'commission' and item.fixed_fee:
                groups['financial.commission.fixed_fee'] = item.fixed_fee
    for key in type(profile.breakdown).model_fields:
        item = getattr(profile.breakdown, key)
        if item is not None:
            groups['breakdown.'+key] = item
    return groups


def normalize_cost(item):
    return None if item is None else effective_cost(item.amount,item.vat_basis,item.vat_rate_percent,item.input_vat_recoverable)


def cost_sum(items):
    values = [normalize_cost(item) for item in items]
    return sum(values, Decimal(0)) if all(v is not None for v in values) else None


def proposals(profile):
    return {key: {'amount': str(cost_sum([getattr(profile.breakdown, name) for name in names]))
                          if cost_sum([getattr(profile.breakdown, name) for name in names]) is not None else None,
                  'vat_basis': 'effective', 'kind': 'derived', 'depends_on': ['breakdown.'+name for name in names],
                  'requires_explicit_confirmation': True}
            for key,names in [('landed_purchase_cost', ('purchase_cost','inbound_cost')),
                              ('fulfilment_cost', ('shipping_cost','packaging_cost','handling_cost'))]}


def migrate_financial_profiles(db):
    db.execute('''CREATE TABLE IF NOT EXISTS financial_input_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL REFERENCES products(id),
        version INTEGER NOT NULL CHECK(version>0),
        schema_version TEXT NOT NULL,
        saved_at TEXT NOT NULL,
        profile_hash TEXT NOT NULL,
        payload TEXT NOT NULL,
        preview_id TEXT NOT NULL,
        UNIQUE(product_id, version), UNIQUE(product_id, preview_id)
    )''')


@contextmanager
def connect(mode='ro'):
    if not database.DB_PATH.exists():
        raise HTTPException(404,'Product niet gevonden.')
    db=sqlite3.connect(database.DB_PATH.resolve().as_uri()+'?mode='+mode,uri=True)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def serialize(row):
    return {'id':row['id'],'product_id':row['product_id'],'version':row['version'],
            'schema_version':row['schema_version'],'saved_at':row['saved_at'],
            'profile_hash':row['profile_hash'],'profile':json.loads(row['payload'])}


def read_profile(product_id, version=None):
    if not database.DB_PATH.exists():
        return None
    try:
        with connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='financial_input_versions' AND type='table'").fetchone():
                return None
            if version is None:
                row=db.execute('SELECT * FROM financial_input_versions WHERE product_id=? ORDER BY version DESC LIMIT 1',(product_id,)).fetchone()
            else:
                row=db.execute('SELECT * FROM financial_input_versions WHERE product_id=? AND version=?',(product_id,version)).fetchone()
            return serialize(row) if row else None
    except (sqlite3.Error,ValueError,TypeError):
        raise HTTPException(503,'Financiële invoer is tijdelijk niet beschikbaar.') from None


def validate_evidence(profile, product, as_of):
    for path,item in input_groups(profile).items():
        provenance=item.provenance
        if provenance.recorded_at > as_of:
            raise ValueError('Input evidence cannot be in the future')
        ref=profile.references.get(path)
        if ref and ref.snapshot_id is not None:
            read_market(product.get('ean') or '',ref.snapshot_id)
        if provenance.snapshot_id is not None:
            read_market(product.get('ean') or '',provenance.snapshot_id)
        if provenance.kind == 'official_measured':
            # Current trusted provider: only an exact saved bol offer price. No tax/fee guesswork.
            if path != 'financial.planned_sale_price' or provenance.snapshot_id is None:
                raise ValueError('No official rule provider exists for this financial input')
            payload,_=read_market(product.get('ean') or '',provenance.snapshot_id)
            measured=datetime.fromisoformat(payload['measured_at'])
            if measured != provenance.recorded_at or item.vat_basis != 'inclusive':
                raise ValueError('Official price must match snapshot timestamp and gross basis')
            result=market_reference(payload,provenance.snapshot_id,measured)
            if result['status'] != 'usable' or item.amount != Decimal(result['price']):
                raise ValueError('Official price must match saved relevant bol price')
            if ref and ref.snapshot_id is not None and ref.snapshot_id != provenance.snapshot_id:
                raise ValueError('Conflicting snapshot references')


def scoring_inputs(profile):
    # All financial types and official evidence were validated at this server boundary.
    # The public scoring API still rejects caller-injected official measurements.
    validated=ScoringInputs(financial={})
    return validated.model_copy(update={'financial':profile.financial})


def digest(profile):
    return sha256(json.dumps(profile.model_dump(mode='json'),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


receipts=PreviewStore()


def preview_profile(product, profile, expected_version, as_of):
    validate_evidence(profile,product,as_of)
    current=read_profile(product['id'])
    if (current['version'] if current else 0) != expected_version:
        raise HTTPException(409,'De financiële invoer is inmiddels gewijzigd. Laad de nieuwste versie.')
    payload,sid=read_market(product.get('ean') or '',None) if product.get('ean') else (None,None)
    financial=calculate_financial(profile.financial,as_of=as_of,market_payload=payload,snapshot_id=sid)
    receipt=receipts.issue({'product_id':product['id'],'expected_version':expected_version,'profile_hash':digest(profile)})
    return {'preview_id':receipt,'profile_hash':digest(profile),'financial':financial,'proposals':proposals(profile),
            'expected_version':expected_version,'expires_in_seconds':900}


def save_profile(product,profile,expected_version,receipt,as_of):
    validate_evidence(profile,product,as_of)
    try:
        with connect('rw') as db:
            db.execute('BEGIN IMMEDIATE')
            migrate_financial_profiles(db) # Additive in same atomic transaction; no legacy data changes.
            existing=db.execute('SELECT * FROM financial_input_versions WHERE product_id=? AND preview_id=?',(product['id'],receipt)).fetchone()
            if existing:
                if existing['profile_hash'] != digest(profile):
                    raise HTTPException(409,'Deze preview is al opgeslagen met andere invoer.')
                return serialize(existing)
            evidence=receipts.get(receipt)
            if evidence != {'product_id':product['id'],'expected_version':expected_version,'profile_hash':digest(profile)}:
                raise HTTPException(409,'Invoer is gewijzigd sinds de preview. Bereken eerst een nieuwe preview.')
            current=db.execute('SELECT MAX(version) FROM financial_input_versions WHERE product_id=?',(product['id'],)).fetchone()[0] or 0
            if current != expected_version:
                raise HTTPException(409,'De financiële invoer is inmiddels gewijzigd. Laad de nieuwste versie.')
            cursor=db.execute('''INSERT INTO financial_input_versions(product_id,version,schema_version,saved_at,profile_hash,payload,preview_id)
                                 VALUES (?,?,?,?,?,?,?)''',(product['id'],current+1,profile.schema_version,as_of.isoformat(),digest(profile),
                                                           json.dumps(profile.model_dump(mode='json'),ensure_ascii=False),receipt))
            row=db.execute('SELECT * FROM financial_input_versions WHERE id=?',(cursor.lastrowid,)).fetchone()
            return serialize(row)
    except sqlite3.Error:
        raise HTTPException(503,'Opslaan van financiële invoer is tijdelijk niet beschikbaar.') from None


def history(product_id):
    if read_profile(product_id) is None:
        return []
    try:
        with connect() as db:
            rows=db.execute('SELECT id,version,saved_at,profile_hash FROM financial_input_versions WHERE product_id=? ORDER BY version DESC',(product_id,)).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error:
        raise HTTPException(503,'Versiehistorie is tijdelijk niet beschikbaar.') from None
