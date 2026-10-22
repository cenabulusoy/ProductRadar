"""Separate v10 webshop placement source; no scoring or category mutation."""
from datetime import datetime, timezone
import json
import threading
from fastapi import HTTPException
from app.services.bol import BolError, validate_ean
from app.services.discovery import connection

lock = threading.Lock()


def validate_query(ean, country, language):
    validate_ean(ean)
    if country not in ('NL', 'BE') or language not in ('nl', 'nl-BE', 'fr-BE'):
        raise BolError(422, 'Gebruik een officieel ondersteund land en taal.')


def parse(client, body):
    if not isinstance(body, dict) or not isinstance(body.get('url'), str) or not isinstance(body.get('categories'), list):
        raise BolError(502, 'Placementresponse wijkt af van het v10-contract.')
    count, incomplete = 0, False

    def node(value, root=False, depth=0):
        nonlocal count, incomplete
        count += 1
        if count > 500 or depth > 20 or not isinstance(value, dict):
            raise BolError(502, 'Placementhiërarchie is ongeldig of overschrijdt de veilige grens.')
        keys = ('categoryId', 'categoryName') if root else ('id', 'name')
        result = {}
        for key in keys:
            field = value.get(key)
            if root and not isinstance(field, str) or field is not None and not isinstance(field, str):
                raise BolError(502, 'Placementcategorie bevat ongeldige velden.')
            if field is None or not field.strip():
                incomplete = True
            result[key] = client._text(field) if field is not None and field.strip() else None
        children = value.get('subcategories')
        if children is not None and not isinstance(children, list):
            raise BolError(502, 'Placementsubcategorieën zijn ongeldig.')
        result['subcategories'] = None if children is None else [node(x, depth=depth + 1) for x in children]
        return result

    categories = [node(value, root=True) for value in body['categories']]
    url = client._text(body['url']) if body['url'].strip() else None
    return {'url': url, 'categories': categories}, incomplete or not bool(url and url.strip())


def fetch(client, ean, country='NL', language='nl'):
    validate_query(ean, country, language)
    token = client._access_token()
    # Deliberately one placement request; no automatic 401 retry or follow-up.
    response = client._request('GET', 'https://api.bol.com/retailer/products/' + ean + '/placement',
        params={'country-code': country}, headers={'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.retailer.v10+json', 'Accept-Language': language})
    client._check(response)
    official, incomplete = parse(client, client._json(response))
    return {'ean': ean, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'query': {'country_code': country, 'language': language},
        'query_notice': 'Land/taal zijn expliciete requestcontext; geen afzonderlijk responseveld.',
        'official': official, 'status': 'partial' if incomplete else 'complete',
        'completeness': {'kind': 'derived', 'missing_category_identity_or_url': incomplete},
        'http_status': response.status_code,
        'provenance': {'kind': 'official_measured', 'source': 'bol Retailer API',
            'api_version': 'v10', 'endpoint': 'products/{ean}/placement'},
        'notice': 'Officiële webshopplacement; geen Product List-zoekcontext, GPC, ranking, vraag of verkoopvolume.'}


def migrate_placement(db):
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_placement_measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
        query_key TEXT NOT NULL, ean TEXT NOT NULL, retrieved_at TEXT NOT NULL,
        country_code TEXT NOT NULL, language TEXT NOT NULL, payload TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS discovery_placement_ean_history ON discovery_placement_measurements(ean,id)')


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def stored(ean):
    validate_ean(ean)
    with connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_placement_measurements'").fetchone():
            return []
        return [{'id': row['id'], **json.loads(row['payload'])} for row in db.execute(
            'SELECT id,payload FROM discovery_placement_measurements WHERE ean=? ORDER BY id DESC LIMIT 20', (ean,))]


def measure(client, ean, country, language, request_id):
    validate_query(ean, country, language)
    query = encode([ean, country, language])
    if not lock.acquire(False):
        raise HTTPException(409, 'Er loopt al een placementaanvraag.')
    try:
        with connection() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_placement_measurements'").fetchone()
            row = db.execute('SELECT * FROM discovery_placement_measurements WHERE request_id=?', (request_id,)).fetchone() if exists else None
            if row:
                if row['query_key'] != query:
                    raise HTTPException(409, 'Deze aanvraag hoort bij een andere placementcontext.')
                return {'id': row['id'], **json.loads(row['payload'])}
        result = fetch(client, ean, country, language)
        with connection(True) as db:
            db.execute('BEGIN IMMEDIATE')
            migrate_placement(db)
            db.execute('INSERT INTO discovery_placement_measurements(request_id,query_key,ean,retrieved_at,country_code,language,payload) VALUES (?,?,?,?,?,?,?)',
                (request_id, query, ean, result['retrieved_at'], country, language, encode(result)))
            identity = db.execute('SELECT id FROM discovery_placement_measurements WHERE request_id=?', (request_id,)).fetchone()[0]
        return {'id': identity, **result}
    finally:
        lock.release()
