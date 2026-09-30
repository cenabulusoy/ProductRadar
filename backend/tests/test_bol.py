import base64
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.bol import router, get_bol_client
from app.services.bol import BolClient, BolSettings

EAN = '4006381333931'
CLIENT_ID, SECRET, TOKEN = 'fake-client-id', 'fake-secret-value', 'fake-access-token'
CATALOG = {'published': True, 'gpc': {'chunkId': '123'}, 'enrichment': {'status': 2},
    'attributes': [{'id': 'Title', 'values': [{'value': 'Testproduct'}]},
                   {'id': 'Brand', 'values': [{'value': 'Merk'}]}]}
RATINGS = {'ratings': [{'rating': 5, 'count': 3}, {'rating': 1, 'count': 1}]}


def setup_client(handler=None, settings=None, clock=None):
    calls = []

    def mock(request):
        calls.append(request)
        if handler:
            custom = handler(request)
            if custom is not None:
                return custom
        if request.url.host == 'login.bol.com':
            assert request.method == 'POST'
            assert request.headers['authorization'] == 'Basic ' + base64.b64encode(f'{CLIENT_ID}:{SECRET}'.encode()).decode()
            assert request.content == b'grant_type=client_credentials'
            return httpx.Response(200, json={'access_token': TOKEN, 'expires_in': 299, 'token_type': 'Bearer'})
        assert request.method == 'GET'
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        assert request.headers['accept'] == 'application/vnd.retailer.v10+json'
        return httpx.Response(200, json=CATALOG if 'catalog-products' in request.url.path else RATINGS)

    kwargs = {'clock': clock} if clock else {}
    bol = BolClient(settings or BolSettings(CLIENT_ID, SECRET), transport=httpx.MockTransport(mock), **kwargs)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_bol_client] = lambda: bol
    return TestClient(app), bol, calls


def preview(client, ean=EAN):
    return client.get('/api/bol/ean-preview/' + ean)


def test_preview_normalizes_data_and_reuses_token(caplog):
    client, bol, calls = setup_client()
    response = preview(client)
    assert response.status_code == 200
    data = response.json()
    assert data['ean'] == EAN
    assert data['catalog']['title'] == 'Testproduct'
    assert data['ratings']['count'] == 4
    assert data['ratings']['average'] == 4.0
    assert data['fetched_at'] and data['warnings'] == []
    assert response.headers['cache-control'] == 'no-store'
    assert preview(client).status_code == 200
    assert len([r for r in calls if r.url.host == 'login.bol.com']) == 1
    for value in (CLIENT_ID, SECRET, TOKEN):
        assert value not in response.text + caplog.text + repr(bol.settings)


@pytest.mark.parametrize('ean', ['123', '4006381333932', 'abcdefghijklz', '４００６３８１３３３９３１'])
def test_invalid_ean_never_calls_bol(ean):
    client, _, calls = setup_client()
    assert preview(client, ean).status_code == 400
    assert not calls


def test_leading_zero_is_preserved():
    client, _, calls = setup_client()
    response = preview(client, '0000000000000')
    assert response.json()['ean'] == '0000000000000'
    assert '0000000000000' in calls[1].url.path


def test_missing_configuration_never_calls_network(monkeypatch):
    monkeypatch.delenv('BOL_CLIENT_ID', raising=False)
    monkeypatch.delenv('BOL_CLIENT_SECRET', raising=False)
    client, _, calls = setup_client(settings=BolSettings.from_environment())
    assert preview(client).status_code == 503
    assert not calls


def test_environment_configuration_is_private(monkeypatch):
    monkeypatch.setenv('BOL_CLIENT_ID', CLIENT_ID)
    monkeypatch.setenv('BOL_CLIENT_SECRET', SECRET)
    settings = BolSettings.from_environment()
    assert settings.client_id == CLIENT_ID and settings.client_secret == SECRET
    assert SECRET not in repr(settings)


def test_expired_token_refreshes():
    now = [0.0]
    client, _, calls = setup_client(clock=lambda: now[0])
    preview(client)
    now[0] = 280
    assert preview(client).status_code == 200
    assert sum(r.url.host == 'login.bol.com' for r in calls) == 2


def test_concurrent_requests_share_token():
    _, bol, calls = setup_client()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: bol.preview(EAN), range(4)))
    assert len(results) == 4
    assert sum(r.url.host == 'login.bol.com' for r in calls) == 1


@pytest.mark.parametrize('status,expected', [(401, 503), (403, 503), (429, 429), (500, 502), (302, 502)])
def test_authentication_errors_do_not_leak(status, expected, caplog):
    client, _, calls = setup_client(handler=lambda r: httpx.Response(status, text=SECRET + TOKEN))
    response = preview(client)
    assert response.status_code == expected
    assert SECRET not in response.text + caplog.text
    assert TOKEN not in response.text + caplog.text
    assert len(calls) == 1


def test_unauthorized_catalog_refreshes_token_only_once():
    failures = [0]
    def handler(request):
        if 'catalog-products' in request.url.path:
            failures[0] += 1
            if failures[0] == 1:
                return httpx.Response(401)
    client, _, calls = setup_client(handler)
    assert preview(client).status_code == 200
    assert sum(r.url.host == 'login.bol.com' for r in calls) == 2


def test_repeated_unauthorized_stops():
    client, _, calls = setup_client(lambda r: httpx.Response(401) if 'catalog-products' in r.url.path else None)
    assert preview(client).status_code == 503
    assert len(calls) == 4


def test_rate_limit_stops_new_requests_until_cooldown():
    now = [0.0]
    def handler(request):
        if 'catalog-products' in request.url.path and now[0] == 0:
            return httpx.Response(429, headers={'Retry-After': '120'}, text=SECRET)
    client, _, calls = setup_client(handler, clock=lambda: now[0])
    assert preview(client).status_code == 429
    count = len(calls)
    assert preview(client).status_code == 429
    assert len(calls) == count
    now[0] = 121
    assert preview(client).status_code == 200


@pytest.mark.parametrize('status,expected', [(403, 503), (404, 404), (500, 502)])
def test_catalog_errors(status, expected):
    client, _, _ = setup_client(lambda r: httpx.Response(status, text=SECRET) if 'catalog-products' in r.url.path else None)
    response = preview(client)
    assert response.status_code == expected and SECRET not in response.text


@pytest.mark.parametrize('exception,expected', [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_network_failures_are_sanitized(exception, expected):
    def handler(request):
        raise exception(SECRET, request=request)
    client, _, _ = setup_client(handler)
    response = preview(client)
    assert response.status_code == expected and SECRET not in response.text


@pytest.mark.parametrize('body', [{'access_token': TOKEN, 'expires_in': 0}, {'access_token': TOKEN}, {'expires_in': 299}])
def test_invalid_token_response(body):
    client, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    assert preview(client).status_code == 502


def test_malformed_json_is_sanitized():
    client, _, _ = setup_client(lambda r: httpx.Response(200, text=SECRET))
    response = preview(client)
    assert response.status_code == 502 and SECRET not in response.text


@pytest.mark.parametrize('body', [{}, {'products': []}, {'products': [None]}, {'attributes': None}, {'attributes': {}}])
def test_malformed_catalog(body):
    client, _, _ = setup_client(lambda r: httpx.Response(200, json=body) if 'catalog-products' in r.url.path else None)
    assert preview(client).status_code == 502


@pytest.mark.parametrize('rating_response', [httpx.Response(404), httpx.Response(503), httpx.Response(200, json={'ratings': None}), httpx.Response(200, json={'ratings': [{'rating': 9, 'count': -1}]})])
def test_partial_preview_preserves_catalog(rating_response):
    client, _, _ = setup_client(lambda r: rating_response if r.url.path.endswith('/ratings') else None)
    response = preview(client)
    assert response.status_code == 200
    assert response.json()['catalog']['title'] == 'Testproduct'
    assert response.json()['ratings'] is None and response.json()['warnings']


def test_zero_ratings_is_not_zero_stars():
    client, _, _ = setup_client(lambda r: httpx.Response(200, json={'ratings': []}) if r.url.path.endswith('/ratings') else None)
    assert preview(client).json()['ratings'] == {'count': 0, 'average': None, 'distribution': []}


def test_allowlist_and_echo_redaction():
    body = json.loads(json.dumps(CATALOG))
    body['client_secret'] = SECRET
    body['attributes'][0]['values'][0]['value'] = SECRET + TOKEN + CLIENT_ID
    client, _, _ = setup_client(lambda r: httpx.Response(200, json=body) if 'catalog-products' in r.url.path else None)
    response = preview(client)
    for value in (SECRET, TOKEN, CLIENT_ID, 'client_secret'):
        assert value not in response.text


def test_preview_does_not_modify_products_or_scores(tmp_path, monkeypatch):
    from app.core import database
    from app.main import app
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'products.db')
    _, bol, _ = setup_client()
    app.dependency_overrides[get_bol_client] = lambda: bol
    try:
        with TestClient(app) as client:
            before = client.get('/api/products').json()
            contents = database.DB_PATH.read_bytes()
            assert preview(client).status_code == 200
            assert database.DB_PATH.read_bytes() == contents
            assert client.get('/api/products').json() == before
    finally:
        app.dependency_overrides.pop(get_bol_client, None)
