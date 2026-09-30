import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.main import app
from app.api.bol import get_bol_client
from app.services import snapshots
from app.services.bol import BolError
from test_bol import setup_client, EAN, SECRET, TOKEN, CLIENT_ID, CATALOG


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setattr(snapshots, 'previews', snapshots.PreviewStore())
    # The router and persistence service must use the same receipt store.
    from app.api import bol
    monkeypatch.setattr(bol, 'previews', snapshots.previews)
    _, adapter, calls = setup_client()
    app.dependency_overrides[get_bol_client] = lambda: adapter
    try:
        with TestClient(app) as client:
            yield client, calls
    finally:
        app.dependency_overrides.pop(get_bol_client, None)


def fetch(client):
    result = client.get('/api/bol/ean-preview/' + EAN)
    assert result.status_code == 200
    return result.json()


def save(client, preview):
    return client.post('/api/bol/snapshots', json={'preview_id': preview['preview_id']})


def history(client):
    return client.get('/api/bol/products/' + EAN + '/snapshots')


def test_preview_is_readonly_and_save_preserves_products_scores_and_csv(client):
    client, calls = client
    # Include real manual/CSV data with the same EAN as the bol identity.
    csv = 'name,category,ean,sale_price,purchase_price,shipping_cost\nManual,Custom,' + EAN + ',50,12,4\n'
    imported = client.post('/api/products/import', files={'file': ('test.csv', csv, 'text/csv')})
    assert imported.status_code == 200 and imported.json()['imported_count'] == 1
    before = client.get('/api/products').json()
    contents = database.DB_PATH.read_bytes()
    preview = fetch(client)
    assert database.DB_PATH.read_bytes() == contents
    count = len(calls)
    response = save(client, preview)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert len(calls) == count  # Saving does not refetch or mutate bol.
    assert client.get('/api/products').json() == before
    duplicate = client.post('/api/products/import', files={'file': ('test.csv', csv, 'text/csv')})
    assert duplicate.json()['skipped_count'] == 1
    assert client.get('/api/products').json() == before
    stored = response.json()['preview']
    assert stored == {k: v for k, v in preview.items() if k != 'preview_id'}
    assert stored['data_kinds']['rating_distribution'] == 'official_bol'
    assert stored['data_kinds']['rating_count_and_average'] == 'derived_productradar'
    assert stored['endpoints']['catalog']['version'] == 'v10'
    assert stored['status'] == 'complete'
    assert stored['ratings']['distribution'] == [{'rating': 1, 'count': 1}, {'rating': 5, 'count': 3}]


def test_repeated_measurements_one_identity_and_retry_one_snapshot(client):
    client, _ = client
    first = fetch(client)
    one = save(client, first).json()
    assert save(client, first).json() == one
    second = save(client, fetch(client)).json()
    assert second['id'] != one['id']
    data = history(client).json()
    assert [s['id'] for s in data['snapshots']] == [second['id'], one['id']]
    with database.get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM bol_product_identities').fetchone()[0] == 1


def test_concurrent_saves_are_idempotent(client):
    client, _ = client
    receipt = fetch(client)['preview_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(snapshots.save_snapshot, [receipt] * 4))
    assert len({r['id'] for r in results}) == 1
    assert len(history(client).json()['snapshots']) == 1


def test_saved_retry_survives_receipt_expiration(client, monkeypatch):
    client, _ = client
    preview = fetch(client)
    stored = save(client, preview).json()
    monkeypatch.setattr(snapshots, 'previews', snapshots.PreviewStore())
    assert save(client, preview).json() == stored


@pytest.mark.parametrize('body', [{}, {'preview_id': 'short'}, {'preview_id': 'a'*43, 'catalog': {'title': 'forged'}}, {'preview_id': 'a'*43, 'ean': EAN}])
def test_client_cannot_forge_measurements(client, body):
    client, _ = client
    assert client.post('/api/bol/snapshots', json=body).status_code == 422
    assert history(client).json()['snapshots'] == []


def test_unknown_receipt_writes_nothing(client):
    client, _ = client
    assert client.post('/api/bol/snapshots', json={'preview_id': 'a'*43}).status_code == 410
    assert history(client).json() == {'identity': None, 'snapshots': []}


def test_expiration_bounding_and_copy_isolation():
    now = [0]
    store = snapshots.PreviewStore(clock=lambda: now[0], ttl=5, capacity=2)
    value = {'catalog': {'title': 'Original'}}
    first = store.issue(value)
    value['catalog']['title'] = 'Changed'
    assert store.get(first)['catalog']['title'] == 'Original'
    store.get(first)['catalog']['title'] = 'Changed'
    assert store.get(first)['catalog']['title'] == 'Original'
    store.issue(value)
    latest = store.issue(value)
    with pytest.raises(BolError): store.get(first)
    now[0] = 5
    with pytest.raises(BolError): store.get(latest)


def test_partial_status_and_safe_error_persist(client):
    client, _ = client
    _, adapter, _ = setup_client(lambda r: httpx.Response(403, text=SECRET) if r.url.path.endswith('/ratings') else None)
    app.dependency_overrides[get_bol_client] = lambda: adapter
    data = save(client, fetch(client)).json()['preview']
    assert data['status'] == 'partial' and data['ratings'] is None
    assert data['endpoints']['ratings']['status'] == 'unavailable'
    assert data['endpoints']['ratings']['error_code'] == 503  # adapter status, not raw HTTP
    assert data['field_completeness']['ratings'] is False
    assert SECRET not in json.dumps(data)


def test_catalog_failure_cannot_be_saved(client):
    client, _ = client
    _, adapter, _ = setup_client(lambda r: httpx.Response(404) if 'catalog-products' in r.url.path else None)
    app.dependency_overrides[get_bol_client] = lambda: adapter
    response = client.get('/api/bol/ean-preview/' + EAN)
    assert response.status_code == 404 and 'preview_id' not in response.json()
    assert history(client).json()['snapshots'] == []


def test_missing_metadata_is_not_fabricated(client):
    client, _ = client
    _, adapter, _ = setup_client(lambda r: httpx.Response(200, json={'attributes': []}) if 'catalog-products' in r.url.path else None)
    app.dependency_overrides[get_bol_client] = lambda: adapter
    data = save(client, fetch(client)).json()['preview']
    assert data['bol_product_id'] is None
    assert data['catalog']['title'] is None
    assert data['field_completeness']['title'] is False


def test_optional_product_id_and_secret_redaction(client, caplog):
    client, _ = client
    catalog = {**CATALOG, 'productId': 'bol-id-123', 'unexpected_secret': SECRET}
    _, adapter, _ = setup_client(lambda r: httpx.Response(200, json=catalog) if 'catalog-products' in r.url.path else None)
    app.dependency_overrides[get_bol_client] = lambda: adapter
    response = save(client, fetch(client))
    assert response.json()['preview']['bol_product_id'] == 'bol-id-123'
    assert history(client).json()['identity']['bol_product_id'] == 'bol-id-123'
    content = database.DB_PATH.read_bytes()
    for secret in (SECRET, TOKEN, CLIENT_ID):
        assert secret.encode() not in content
        assert secret not in response.text + caplog.text


def test_history_does_not_call_bol_and_validates_ean(client):
    client, calls = client
    assert history(client).json() == {'identity': None, 'snapshots': []}
    assert client.get('/api/bol/products/invalid/snapshots').status_code == 400
    assert not calls


def test_database_failure_is_sanitized_and_atomic(client):
    client, _ = client
    preview = fetch(client)
    with database.get_connection() as db:
        db.execute("""CREATE TRIGGER reject_snapshot BEFORE INSERT ON bol_product_snapshots
                      BEGIN SELECT RAISE(ABORT, 'sensitive database detail'); END""")
    result = save(client, preview)
    assert result.status_code == 503
    assert 'sensitive database detail' not in result.text
    assert history(client).json() == {'identity': None, 'snapshots': []}


def test_additive_migration_preserves_legacy_rows_and_is_repeatable(client):
    client, _ = client
    before = client.get('/api/products').json()
    with database.get_connection() as db:
        db.execute('DROP TABLE bol_market_snapshots')
        db.execute('DROP TABLE bol_product_snapshots')
        db.execute('DROP TABLE bol_product_identities')
    database.init_db()
    database.init_db()
    assert client.get('/api/products').json() == before
    assert history(client).json()['snapshots'] == []
    with database.get_connection() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_cross_origin_save_preflight(client):
    client, _ = client
    response = client.options('/api/bol/snapshots', headers={
        'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://localhost:3000'


def test_history_orders_by_measurement_not_save_time_and_limits_results(client):
    client, _ = client
    preview = fetch(client)
    base = {k: v for k, v in preview.items() if k != 'preview_id'}
    # Save old observations later: storage order must not make them look fresh.
    for minute in reversed(range(55)):
        measured = {**base, 'fetched_at': f'2026-09-25T12:{minute:02d}:00+00:00'}
        snapshots.save_snapshot(snapshots.previews.issue(measured))
    results = history(client).json()['snapshots']
    assert len(results) == 50
    assert results[0]['preview']['fetched_at'] == '2026-09-25T12:54:00+00:00'
    assert results[-1]['preview']['fetched_at'] == '2026-09-25T12:05:00+00:00'


def test_identity_fills_missing_id_without_silently_replacing_known_id(client):
    client, _ = client
    preview = fetch(client)
    save(client, preview)
    base = {k: v for k, v in preview.items() if k != 'preview_id'}
    snapshots.save_snapshot(snapshots.previews.issue({**base, 'bol_product_id': 'first-id'}))
    changed = snapshots.save_snapshot(snapshots.previews.issue({**base, 'bol_product_id': 'different-id'}))
    assert history(client).json()['identity']['bol_product_id'] == 'first-id'
    assert changed['preview']['bol_product_id'] == 'different-id'


def test_failed_migration_rolls_back_all_new_schema(client, monkeypatch):
    client, _ = client
    before = client.get('/api/products').json()
    with database.get_connection() as db:
        db.execute('DROP TABLE bol_market_snapshots')
        db.execute('DROP TABLE bol_product_snapshots')
        db.execute('DROP TABLE bol_product_identities')
    original = snapshots.migrate_snapshots
    def fail(db):
        original(db)
        raise sqlite3.OperationalError('simulated migration failure')
    monkeypatch.setattr(snapshots, 'migrate_snapshots', fail)
    with pytest.raises(sqlite3.OperationalError):
        database.init_db()
    with database.get_connection() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'bol_%'").fetchall()
    assert client.get('/api/products').json() == before
