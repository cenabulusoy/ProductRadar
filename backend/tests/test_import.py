import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.main import app
from app.services.importer import parse_csv

HEADER = 'name,category,sale_price,purchase_price,ean\n'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'products.db')
    with TestClient(app) as client:
        yield client


def post(client, endpoint, text, filename='products.csv'):
    return client.post('/api/products/import' + endpoint,
                       files={'file': (filename, text, 'text/csv')})


def count(client):
    return len(client.get('/api/products').json())


def test_preview_does_not_write_and_limits_sample(client):
    before = count(client)
    csv = HEADER + ''.join(f'Product {i},Test,20,10,00{i}\n' for i in range(7))
    response = post(client, '/preview', '\ufeff' + csv)
    assert response.status_code == 200
    assert response.json()['filename'] == 'products.csv'
    assert response.json()['product_count'] == 7
    assert len(response.json()['preview']) == 5
    assert response.json()['preview'][0]['ean'] == '000'
    assert count(client) == before


def test_duplicate_eans_and_repeat_import(client):
    before = count(client)
    csv = HEADER + 'One,Test,20,10,00123\nDuplicate,Test,20,10,00123\nTwo,Test,30,10,00456\n'
    first = post(client, '', csv)
    assert first.status_code == 200
    assert first.json()['imported_count'] == 2
    assert first.json()['skipped_count'] == 1
    second = post(client, '', csv)
    assert second.json()['imported_count'] == 0
    assert second.json()['skipped_count'] == 3
    assert count(client) == before + 2


def test_empty_eans_remain_supported(client):
    response = post(client, '', HEADER + 'One,Test,20,10,\nTwo,Test,20,10,\n')
    assert response.json()['imported_count'] == 2


@pytest.mark.parametrize('endpoint', ['', '/preview'])
@pytest.mark.parametrize('csv,filename', [
    ('', 'empty.csv'),
    (HEADER, 'empty.csv'),
    ('name\nProduct', 'missing.csv'),
    (HEADER + 'Good,Test,20,10,123\nBad,Test,no,10,456', 'invalid.csv'),
    (HEADER + 'Bad,Test,NaN,10,123', 'nan.csv'),
    (HEADER + 'Bad,Test,inf,10,123', 'inf.csv'),
    (HEADER + 'Bad,Test,20', 'short.csv'),
    (HEADER + 'Bad,Test,20,10,123,extra', 'long.csv'),
    (HEADER + ',Test,20,10,123', 'noname.csv'),
    (HEADER + 'Bad,,20,10,123', 'nocategory.csv'),
    ('name,name,category,sale_price,purchase_price\nA,B,T,20,10', 'duplicate.csv'),
    (b'\xff\xfe', 'encoding.csv'),
    (HEADER + 'Good,Test,20,10,123', 'file.txt'),
])
def test_invalid_import_is_atomic_and_readable(client, endpoint, csv, filename):
    before = count(client)
    response = post(client, endpoint, csv, filename)
    assert response.status_code == 400
    assert isinstance(response.json()['detail'], str)
    assert count(client) == before


def test_trimmed_headers_defaults_and_quoted_fields():
    product = parse_csv(' name , category , sale_price , purchase_price ,ean\n"A, B",Test,20,10,00123')[0]
    assert product['name'] == 'A, B'
    assert product['ean'] == '00123'
    assert product['commission_rate'] == 15
    assert product['shipping_cost'] == 0


def test_favorites_and_product_details_after_import(client):
    post(client, '', HEADER + 'New,Test,20,10,00123')
    product = next(p for p in client.get('/api/products').json() if p['ean'] == '00123')
    assert 'analysis' in product
    assert client.post(f"/api/products/{product['id']}/favorite").json()['favorite'] is True
    assert client.get(f"/api/products/{product['id']}").json()['favorite'] is True
