"""Isolated v10 visibility measurements; never a demand or sales estimate."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import threading
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.services.bol import BolError, validate_ean
from app.services.discovery import connection

ENDPOINT = 'insights/product-ranks'
lock = threading.Lock()


def today():
    return datetime.now(ZoneInfo('Europe/Amsterdam')).date()


def validate_query(ean, report_date, context_type=None, page=1, as_of=None):
    validate_ean(ean)
    current = as_of or today()
    try:
        parsed = date.fromisoformat(report_date)
        if parsed.isoformat() != report_date:
            raise ValueError()
    except (TypeError, ValueError):
        raise BolError(422, 'Gebruik een verslagdatum in YYYY-MM-DD.') from None
    month_index = current.year * 12 + current.month - 1 - 3
    year, month = divmod(month_index, 12)
    earliest = date(year, month + 1, min(current.day, monthrange(year, month + 1)[1]))
    if not earliest <= parsed <= current - timedelta(days=1):
        raise BolError(422, 'Verslagdatum moet tussen drie kalendermaanden geleden en gisteren liggen.')
    if context_type not in (None, 'SEARCH', 'BROWSE') or type(page) is not int or page != 1:
        raise BolError(422, 'Alleen SEARCH/BROWSE of beide, en pagina 1 zijn toegestaan.')


def parse(client, body):
    if not isinstance(body, dict) or type(body.get('hasNextPage')) is not bool or not isinstance(body.get('ranks'), list) or len(body['ranks']) > 50:
        raise BolError(502, 'Rankingresponse wijkt af van het v10-contract.')
    records = []
    for item in body['ranks']:
        if not isinstance(item, dict):
            raise BolError(502, 'Ongeldig rankingrecord.')
        for key in ('rank', 'impressions'):
            if type(item.get(key)) is not int or not 0 <= item[key] <= 2147483647:
                raise BolError(502, 'Verplichte ranking-/impressionwaarde ontbreekt of is ongeldig.')
        if type(item.get('wasSponsored')) is not bool:
            raise BolError(502, 'Verplichte sponsored-status ontbreekt of is ongeldig.')
        for key in ('searchTerm', 'categoryId'):
            if item.get(key) is not None and not isinstance(item[key], str):
                raise BolError(502, 'Rankingcontext is ongeldig.')
        official = {key: client._text(item.get(key)) for key in ('searchTerm', 'categoryId')}
        official.update({key: item[key] for key in ('rank', 'impressions', 'wasSponsored')})
        search, browse = bool(official['searchTerm']), bool(official['categoryId'])
        inferred = 'SEARCH' if search and not browse else 'BROWSE' if browse and not search else None
        records.append({'official': official, 'derived': {'context_type': inferred, 'kind': 'derived'}})
    return records


def fetch(client, ean, report_date, context_type=None):
    validate_query(ean, report_date, context_type)
    params = {'ean': ean, 'date': report_date, 'page': 1}
    if context_type is not None:
        params['type'] = context_type
    token = client._access_token()
    # Exactly one ranking request: do not use _get's automatic 401 replay.
    response = client._request('GET', 'https://api.bol.com/retailer/' + ENDPOINT,
        params=params, headers={'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.retailer.v10+json', 'Accept-Language': 'nl-NL'})
    client._check(response)
    body = client._json(response)
    records = parse(client, body)
    return {'ean': ean, 'report_date': report_date,
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'country': None,
        'country_reason': 'Het endpoint accepteert/retourneert geen land; taal is geen landbewijs.',
        'requested_type': context_type, 'language': 'nl-NL', 'page': 1,
        'has_next_page': body['hasNextPage'], 'status': 'partial' if body['hasNextPage'] else 'complete',
        'records': records, 'http_status': response.status_code,
        'provenance': {'kind': 'official_measured', 'source': 'bol Retailer API',
            'api_version': 'v10', 'endpoint': ENDPOINT},
        'completeness': {'kind': 'derived', 'scope': 'page_1', 'all_pages_retrieved': not body['hasNextPage']},
        'notice': 'Zichtbaarheid op de verslagdatum; geen vraag, verkoopvolume of Demand Score.'}


def migrate_rankings(db):
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_ranking_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
        query_key TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
        ean TEXT NOT NULL, report_date TEXT NOT NULL, retrieved_at TEXT NOT NULL,
        payload TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS discovery_ranking_ean_date ON discovery_ranking_measurements(ean,report_date,id)')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def stored(ean):
    validate_ean(ean)
    with connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_ranking_measurements'").fetchone():
            return []
        return [{'id': r['id'], **json.loads(r['payload'])} for r in db.execute(
            'SELECT id,payload FROM discovery_ranking_measurements WHERE ean=? ORDER BY id DESC LIMIT 20', (ean,))]


def measure(client, ean, report_date, context_type, request_id):
    validate_query(ean, report_date, context_type)
    query = encode([ean, report_date, context_type, 'nl-NL', 1])
    if not lock.acquire(False):
        raise HTTPException(409, 'Er loopt al een rankingsaanvraag.')
    try:
        with connection() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_ranking_measurements'").fetchone()
            row = db.execute('SELECT * FROM discovery_ranking_measurements WHERE request_id=?', (request_id,)).fetchone() if exists else None
            if row:
                if row['query_key'] != query:
                    raise HTTPException(409, 'Deze aanvraag hoort bij een andere rankingcontext.')
                return {'id': row['id'], **json.loads(row['payload'])}
        result = fetch(client, ean, report_date, context_type)
        # Same successful date/context/payload reuses a measurement, preserving its first retrieval time.
        fingerprint = sha256(encode([query, result['records'], result['has_next_page']]).encode()).hexdigest()
        with connection(True) as db:
            db.execute('BEGIN IMMEDIATE')
            migrate_rankings(db)
            db.execute('INSERT OR IGNORE INTO discovery_ranking_measurements(request_id,query_key,fingerprint,ean,report_date,retrieved_at,payload) VALUES (?,?,?,?,?,?,?)',
                (request_id, query, fingerprint, ean, report_date, result['retrieved_at'], encode(result)))
            row = db.execute('SELECT id,payload FROM discovery_ranking_measurements WHERE fingerprint=?', (fingerprint,)).fetchone()
            return {'id': row['id'], **json.loads(row['payload'])}
    finally:
        lock.release()
