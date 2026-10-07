"""Explicit refresh orchestration reusing the bol preview and snapshot writer."""
from datetime import datetime, timezone, timedelta
import sqlite3
from app.core.database import get_connection
from app.services.bol import BolError, validate_ean
from app.services import snapshots
from app.services.freshness import LEASE_SECONDS


def migrate_refresh(db):
    db.execute('''CREATE TABLE IF NOT EXISTS bol_market_refresh_requests (
        request_id TEXT PRIMARY KEY, ean TEXT NOT NULL, started_at TEXT NOT NULL,
        lease_until TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('running','done')),
        snapshot_id INTEGER REFERENCES bol_product_snapshots(id), error_code INTEGER
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS bol_refresh_ean_time ON bol_market_refresh_requests(ean,started_at DESC)')


def error_message(code):
    return {429:'Bol vraagt om te wachten. Probeer het later opnieuw.',
            503:'Bol is niet ingesteld of toegang is geweigerd. Controleer de lokale configuratie en accountrechten.',
            404:'Deze EAN is niet gevonden bij bol.', 504:'Bol reageerde niet op tijd. Probeer later opnieuw.',
            502:'De verbinding of het antwoord van bol is niet bruikbaar. Probeer later opnieuw.'}.get(code,
            'De marktmeting is onvolledig. Probeer later opnieuw; de oude meting blijft alleen historie.')


def failed_preview(ean, code, when):
    return {'ean':ean, 'bol_product_id':None, 'fetched_at':when, 'source':'bol Retailer API v10',
            'api_version':'v10', 'language':'nl', 'status':'partial', 'catalog':None, 'ratings':None,
            'endpoints':{}, 'field_completeness':{}, 'warnings':[error_message(code)],
            'market':{'source':'bol Retailer API','api_version':'v10','endpoint':'products/{ean}/offers',
                      'country':'NL','condition':'NEW','currency':'EUR','measured_at':when,
                      'status':'unavailable','pagination_complete':False,'offers':[], 'pages':[],
                      'warnings':[error_message(code)],'refresh_error_code':code}}


def refresh(ean, request_id, client):
    validate_ean(ean)
    now = datetime.now(timezone.utc)
    try:
        with get_connection() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate_refresh(db)
            previous = db.execute('SELECT ean,state,snapshot_id,error_code FROM bol_market_refresh_requests WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['ean'] != ean:
                    raise BolError(409,'Deze refreshreferentie hoort bij een ander product.')
                if previous['state'] == 'done':
                    return {'snapshot_id':previous['snapshot_id'],'error_code':previous['error_code'],'duplicate':True}
                raise BolError(409,'Deze refresh is nog bezig of onderbroken. Probeer later met een nieuwe aanvraag.')
            running = db.execute("SELECT 1 FROM bol_market_refresh_requests WHERE ean=? AND state='running' AND lease_until>?", (ean,now.isoformat())).fetchone()
            if running:
                raise BolError(409,'Voor deze EAN wordt al een marktmeting opgehaald. Wacht op het resultaat.')
            db.execute('INSERT INTO bol_market_refresh_requests VALUES (?,?,?,?,?,?,?)',
                       (request_id,ean,now.isoformat(),(now+timedelta(seconds=LEASE_SECONDS)).isoformat(),'running',None,None))
        code = None
        try:
            preview = client.preview(ean) # Existing OAuth, catalog, ratings, offers and pagination.
            if preview['market']['status'] != 'complete':
                code = next((p.get('error_code') for p in preview['market'].get('pages',[]) if p.get('error_code')),422)
        except BolError as exc:
            code = exc.status
            preview = failed_preview(ean,code,datetime.now(timezone.utc).isoformat())
        except Exception:
            # Fail safely even on unexpected adapter errors; never expose raw exceptions.
            code = 502
            preview = failed_preview(ean,code,datetime.now(timezone.utc).isoformat())
        receipt = snapshots.previews.issue(preview)
        def completed(db, snapshot_id):
            db.execute("UPDATE bol_market_refresh_requests SET state='done',snapshot_id=?,error_code=? WHERE request_id=?", (snapshot_id,code,request_id))
        saved = snapshots.save_snapshot(receipt, on_saved=completed)
        return {'snapshot_id':saved['id'],'error_code':code,'duplicate':False}
    except sqlite3.Error:
        raise BolError(503,'Refreshopslag is tijdelijk niet beschikbaar. De vorige meting is niet opnieuw actueel verklaard.') from None
