from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.core import database
from app.analysis.scoring import calculate_scores
from app.services.comparison import present_comparison
from test_scoring_v2 import case, run, EAN


def legacy_product(k=3):
    return {'id': 1, 'name': 'Fictief vergelijkingsproduct', 'category': 'Acceptatietest', 'brand': 'Test', 'ean': EAN,
            'sale_price': 39.95, 'purchase_price': k, 'shipping_cost': 3, 'commission_rate': 10,
            'monthly_sales_low': 800, 'monthly_sales_high': 1000, 'sellers': 1, 'reviews': 90,
            'review_growth': 30, 'trend': 10, 'risk_level': 10, 'confidence': 90, 'favorite': 0}


def scenarios():
    result = []
    for name, changes in [('agreement', {}), ('poor_profitability', {'k':15}), ('low_confidence', {}),
                          ('competition', {'n':100}), ('stale_market', {'age':4})]:
        data = case(**changes)
        # Same planned price as v1; bol's stored reference gives the lower conservative scenario.
        data['inputs']['financial']['planned_sale_price']['amount'] = '39.95'
        if name == 'low_confidence':
            data['inputs']['financial']['returns_loss_reserve']['provenance']['kind'] = 'estimated'
        comparison = present_comparison(legacy_product(changes.get('k', 3)), run(data))
        result.append({'scenario': name, 'comparison': comparison})
    return result


@pytest.mark.parametrize('index,reason,verdict', [(0,'agreement','Kansrijk'), (1,'loss','Niet inkopen'),
                                               (2,'low_confidence','Onderzoeken'), (3,'competition','Onderzoeken'),
                                               (4,'stale_market','Onderzoeken')])
def test_representative_real_engine_comparisons(index, reason, verdict):
    c = scenarios()[index]['comparison']
    assert c['analysis_v1']['verdict'] == 'Kansrijk'
    assert c['analysis_v2']['verdict'] == verdict
    assert c['primary_reason']['code'] == reason
    assert c['analysis_v1'] == calculate_scores(legacy_product(15 if index == 1 else 3))
    assert c['default_engine'] == 'v1'
    if index == 4:
        assert c['analysis_v2']['opportunity_score'] is None and c['market']['age_hours'] == 96


def test_shared_ui_golden_is_generated_from_actual_engine_results():
    path = Path(__file__).parent/'fixtures/comparison_scenarios.json'
    assert json.loads(path.read_text(encoding='utf-8')) == scenarios()


@pytest.fixture
def readonly_client(tmp_path, monkeypatch):
    # Only an isolated temporary database is constructed; never start app lifespan/user DB.
    path = tmp_path/'comparison-fixture.sqlite'
    monkeypatch.setattr(database, 'DB_PATH', path)
    database.init_db()
    with database.get_connection() as db:
        db.execute('UPDATE products SET ean=? WHERE id=1', (EAN,))
        db.execute('INSERT INTO bol_product_identities(ean,bol_product_id,created_at) VALUES (?,?,?)',
                   (EAN,'fictitious-id','2020-01-01T00:00:00+00:00'))
        sample = case()
        now = datetime.now(timezone.utc)
        for index, item in enumerate(sample['market_snapshots']):
            p = item['payload']
            when = (now-timedelta(hours=1,days=index*4)).isoformat()
            p['measured_at'] = when
            preview = deepcopy(sample['product_snapshots'][0]['payload'])
            preview['fetched_at'] = when
            db.execute('INSERT INTO bol_product_snapshots(id,preview_id,ean,measured_at,saved_at,source,api_version,status,payload) VALUES (?,?,?,?,?,?,?,?,?)',
                       (index+1,f'fixture-{index}',EAN,when,when,'bol Retailer API v10','v10','complete',json.dumps(preview)))
            db.execute('INSERT INTO bol_market_snapshots(snapshot_id,ean,measured_at,source,api_version,country,condition,status,payload) VALUES (?,?,?,?,?,?,?,?,?)',
                       (index+1,EAN,when,'bol Retailer API','v10','NL','NEW','complete',json.dumps(p)))
    def forbidden(*args, **kwargs):
        raise AssertionError('Live bol requests forbidden in comparison')
    from app.services.bol import BolClient
    monkeypatch.setattr(BolClient, '_get', forbidden)
    yield TestClient(app), path


def test_api_reads_saved_data_without_writes_and_keeps_v1_exact(readonly_client):
    client, path = readonly_client
    before = path.read_bytes()
    old = client.get('/api/products/1').json()
    response = client.get('/api/comparison/products/1')
    assert response.status_code == 200
    result = response.json()
    assert response.headers['cache-control'] == 'no-store'
    assert result['analysis_v1'] == old['analysis']
    assert result['analysis_v2']['opportunity_score'] is None
    assert result['analysis_v2']['subscores']['profitability'] is None
    assert 'financial.sales_vat_rate' in result['analysis_v2']['missing_critical_inputs']
    assert result['market']['unique_seller_count'] == 3
    assert result['market']['source'] == 'bol Retailer API'
    assert all(item['used_in_v2'] is False for item in result['legacy_inputs'])
    assert result['legacy_inputs'][-1]['kind'] == 'estimated'
    assert result['legacy_inputs'][0]['kind'] == 'manual_or_imported'
    assert client.get('/api/products/1').json() == old
    assert path.read_bytes() == before


def test_evaluation_stable_product_order_pagination_and_missing_ean(readonly_client):
    client, path = readonly_client
    before = path.read_bytes()
    response = client.get('/api/comparison/products?limit=2')
    result = response.json()
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert [i['product']['id'] for i in result['items']] == [1,2]
    assert result['next_offset'] == 2 and result['total'] == 5
    assert result['items'][1]['analysis_v2']['opportunity_score'] is None
    assert 'product_identity' in result['items'][1]['analysis_v2']['missing_critical_inputs']
    assert [i['product']['id'] for i in client.get('/api/comparison/products?offset=2&limit=2').json()['items']] == [3,4]
    assert client.get('/api/comparison/products?offset=4&limit=2').json()['next_offset'] is None
    assert path.read_bytes() == before


def test_invalid_requests_do_not_write_and_api_is_get_only(readonly_client):
    client, path = readonly_client
    before = path.read_bytes()
    assert client.get('/api/comparison/products/999').status_code == 404
    assert client.get('/api/comparison/products?limit=51').status_code == 422
    assert client.get('/api/comparison/products?offset=-1').status_code == 422
    assert client.post('/api/comparison/products/1', json={}).status_code == 405
    assert path.read_bytes() == before


def test_comparison_does_not_create_missing_database(tmp_path, monkeypatch):
    path = tmp_path/'missing.sqlite'
    monkeypatch.setattr(database, 'DB_PATH', path)
    client = TestClient(app)
    assert client.get('/api/comparison/products').json()['items'] == []
    assert client.get('/api/comparison/products/1').status_code == 404
    assert not path.exists()


def test_stale_price_never_labelled_current_and_zero_not_missing():
    item = scenarios()[-1]['comparison']
    assert item['market']['freshness'] == 'stale'
    assert item['market']['price_min'] == 24.2
    assert item['analysis_v2']['opportunity_score'] is None
    p = legacy_product()
    p['monthly_sales_low'] = 0
    result = present_comparison(p, run())
    assert next(i for i in result['legacy_inputs'] if i['field']=='monthly_sales_low')['value'] == 0
    assert p['monthly_sales_low'] == 0


def test_v1_original_goldens_are_unchanged_through_presentation():
    fixture = Path(__file__).parent/'fixtures/scoring_v1_golden.json'
    for item in json.loads(fixture.read_text(encoding='utf-8')):
        assert present_comparison(item['input'], run())['analysis_v1'] == item['expected']


def test_one_bad_product_returns_explicit_error_and_preserves_evaluation_rows(readonly_client, monkeypatch):
    from app.api import comparison
    client, _ = readonly_client
    original = comparison.compare_saved_product
    def broken(product, as_of):
        if product['id'] == 2: raise ValueError('Sensitive internal error text')
        return original(product, as_of)
    monkeypatch.setattr(comparison, 'compare_saved_product', broken)
    result = client.get('/api/comparison/products').json()
    assert len(result['items']) == 5
    assert 'error' in result['items'][1]
    assert 'Sensitive' not in json.dumps(result)


def test_presentation_never_mutates_engine_results():
    product, v2 = legacy_product(), run()
    before = deepcopy((product,v2))
    present_comparison(product,v2)
    assert (product,v2) == before
