import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.core import database
from app.main import app
from app.api.bol import get_bol_client
from app.services import market, snapshots
from test_bol import setup_client, EAN, SECRET, TOKEN, CLIENT_ID
from test_snapshots import client, fetch, save, history


def offer(index=1, **changes):
    return {'offerId': str(index), 'retailerId': str(index), 'price': 10.50,
            'countryCode': 'NL', 'condition': 'NEW', 'bestOffer': False,
            'fulfilmentMethod': 'FBR', 'ultimateOrderTime': '23:59',
            'minDeliveryDate': '2026-10-01', 'maxDeliveryDate': '2026-10-02', **changes}


def adapter_for(pages):
    def handler(request):
        if request.url.path.endswith('/offers'):
            assert request.url.params['country-code'] == 'NL'
            assert request.url.params['condition'] == 'NEW'
            assert request.url.params['best-offer-only'] == 'false'
            response = pages[int(request.url.params['page']) - 1]
            return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)
    return setup_client(handler)


def measure(pages):
    _, adapter, calls = adapter_for(pages)
    return market.measure_market(adapter, EAN), calls


def test_pages_count_offers_and_unique_sellers_separately_best_is_not_cheapest():
    rows = [offer(i, retailerId=str(i % 4), price=10 + i, bestOffer=i == 5) for i in range(50)]
    result, calls = measure([{'offers': rows}, {'offers': [offer(50, retailerId='0', price=2)]}])
    assert result['status'] == 'complete'
    derived = result['derived']
    assert derived['offer_count'] == 51 and derived['unique_seller_count'] == 4
    assert derived['price_min'] == 2 and derived['price_max'] == 59
    assert derived['lowest_offer']['offerId'] == '50'
    assert derived['best_offers'][0]['offerId'] == '5'
    assert derived['best_offers'][0]['price'] == 15
    assert result['offers'][0]['retailerId'] == '0'  # bol itself is a retailer too.
    assert result['offers'][0]['ultimateOrderTime'] == '23:59'
    assert [p['page'] for p in result['pages']] == [1, 2]
    assert sum(r.url.host == 'login.bol.com' for r in calls) == 1


def test_full_page_requires_next_page_even_when_it_is_empty():
    result, _ = measure([{'offers': [offer(i) for i in range(50)]}, {'offers': []}])
    assert result['derived']['offer_count'] == 50
    assert len(result['pages']) == 2 and result['pagination_complete']


def test_explicit_empty_list_is_complete_but_has_no_price_or_best_offer():
    result, _ = measure([{'offers': []}])
    assert result['status'] == 'complete'
    assert result['derived']['unique_seller_count'] == 0
    assert result['derived']['offer_count'] == 0
    assert result['derived']['price_min'] is None
    assert result['derived']['best_offers'] == []


@pytest.mark.parametrize('body', [{}, {'offers': None}, {'offers': {}}, {'offers': 'bad'}, {'offers': [None]}, {'offers': [offer(i) for i in range(51)]}])
def test_missing_or_invalid_offers_are_never_zero_competition(body):
    result, _ = measure([body])
    assert result['status'] == 'unavailable'
    assert result['derived']['offer_count'] is None
    assert result['derived']['unique_seller_count'] is None
    assert result['warnings']


@pytest.mark.parametrize('change', [dict(retailerId=None), dict(offerId=''), dict(price=None), dict(price=-1),
                                   dict(price=True), dict(price='12'), dict(price=1.234), dict(bestOffer='true'),
                                   dict(countryCode='BE'), dict(condition='AS_NEW')])
def test_malformed_or_wrong_segment_offer_cannot_produce_complete_totals(change):
    result, _ = measure([{'offers': [offer(**change)]}])
    assert result['status'] != 'complete'
    assert result['derived']['unique_seller_count'] is None
    assert result['derived']['price_min'] is None


@pytest.mark.parametrize('status', [403, 404, 429, 500])
def test_upstream_errors_do_not_mean_zero_offers(status):
    result, _ = measure([httpx.Response(status, text=SECRET)])
    assert result['status'] == 'unavailable'
    assert result['derived']['offer_count'] is None
    assert SECRET not in json.dumps(result)


def test_later_page_failure_preserves_observations_without_false_totals():
    result, _ = measure([{'offers': [offer(i) for i in range(50)]}, httpx.Response(500, text=TOKEN)])
    assert result['status'] == 'partial'
    assert len(result['offers']) == 50
    assert result['derived']['observed_unique_seller_count'] == 50
    assert result['derived']['offer_count'] is None and result['derived']['lowest_offer'] is None
    assert not result['pagination_complete']


def test_rate_limit_stops_and_prevents_immediate_followup_requests():
    _, adapter, calls = adapter_for([{'offers': [offer(i) for i in range(50)]}, httpx.Response(429, headers={'Retry-After': '120'})])
    result = market.measure_market(adapter, EAN)
    assert result['status'] == 'partial' and result['pages'][-1]['error_code'] == 429
    count = len(calls)
    retry = market.measure_market(adapter, EAN)
    assert retry['status'] == 'unavailable' and len(calls) == count


def test_repeated_page_stops_and_deduplicates_offer_ids():
    page = {'offers': [offer(i) for i in range(50)]}
    result, _ = measure([page, page])
    assert result['status'] == 'partial'
    assert len(result['offers']) == 50 and len(result['pages']) == 2
    assert result['derived']['offer_count'] is None


def test_overlapping_offer_ids_are_not_counted_twice():
    result, _ = measure([{'offers': [offer(i) for i in range(50)]}, {'offers': [offer(49, price=3), offer(50)]}])
    assert result['status'] == 'partial' and len(result['offers']) == 51
    assert result['pagination_complete']


def test_page_ceiling_is_marked_partial(monkeypatch):
    monkeypatch.setattr(market, 'MAX_PAGES', 2)
    result, _ = measure([{'offers': [offer(i) for i in range(50)]}, {'offers': [offer(i) for i in range(50, 100)]}])
    assert result['status'] == 'partial' and not result['pagination_complete']
    assert result['derived']['offer_count'] is None


def test_optional_metadata_absence_and_multiple_best_offers_are_preserved():
    result, _ = measure([{'offers': [offer(1, bestOffer=True, fulfilmentMethod=None), offer(2, bestOffer=True)]}])
    assert result['status'] == 'complete'
    assert len(result['derived']['best_offers']) == 2
    assert result['offers'][0]['fulfilmentMethod'] is None


def test_market_payload_is_allowlisted_and_redacted():
    result, _ = measure([{'offers': [offer(1, fulfilmentMethod=SECRET + TOKEN + CLIENT_ID, unexpected=SECRET)]}])
    text = json.dumps(result)
    assert all(s not in text for s in (SECRET, TOKEN, CLIENT_ID, 'unexpected'))


def test_malformed_json_and_timeout_are_safe():
    result, _ = measure([httpx.Response(200, text=SECRET)])
    assert result['status'] == 'unavailable' and SECRET not in json.dumps(result)
    def handler(request):
        if request.url.path.endswith('/offers'):
            raise httpx.ReadTimeout(SECRET, request=request)
    _, adapter, _ = setup_client(handler)
    result = market.measure_market(adapter, EAN)
    assert result['pages'][0]['error_code'] == 504
    assert result['derived']['offer_count'] is None


def test_market_snapshot_roundtrip_idempotency_and_manual_data_preserved(client):
    client, _ = client
    _, adapter, _ = adapter_for([{'offers': [offer(1), offer(2, retailerId='1')]}])
    app.dependency_overrides[get_bol_client] = lambda: adapter
    before = client.get('/api/products').json()
    preview = fetch(client)
    saved = save(client, preview).json()
    assert save(client, preview).json() == saved
    assert history(client).json()['snapshots'][0]['preview']['market'] == preview['market']
    with database.get_connection() as db:
        rows = db.execute('SELECT * FROM bol_market_snapshots').fetchall()
        assert len(rows) == 1
        assert rows[0]['country'] == 'NL' and rows[0]['condition'] == 'NEW'
        assert rows[0]['measured_at'] == preview['market']['measured_at']
        assert json.loads(rows[0]['payload']) == preview['market']
    assert client.get('/api/products').json() == before


def test_concurrent_snapshot_save_creates_one_market_measurement(client):
    client, _ = client
    receipt = fetch(client)['preview_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(snapshots.save_snapshot, [receipt] * 4))
    assert len({r['id'] for r in results}) == 1
    with database.get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM bol_market_snapshots').fetchone()[0] == 1


def test_market_write_failure_rolls_back_whole_snapshot(client):
    client, _ = client
    preview = fetch(client)
    with database.get_connection() as db:
        db.execute("""CREATE TRIGGER reject_market BEFORE INSERT ON bol_market_snapshots
                      BEGIN SELECT RAISE(ABORT, 'private detail'); END""")
    response = save(client, preview)
    assert response.status_code == 503 and 'private detail' not in response.text
    assert history(client).json() == {'identity': None, 'snapshots': []}


def test_old_snapshot_remains_readable_after_additive_migration(client):
    client, _ = client
    preview = fetch(client)
    preview.pop('market')
    receipt = snapshots.previews.issue(preview)
    stored = snapshots.save_snapshot(receipt)
    with database.get_connection() as db:
        db.execute('DROP TABLE bol_market_snapshots')
    database.init_db()
    database.init_db()
    assert history(client).json()['snapshots'] == [stored]
    with database.get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM bol_market_snapshots').fetchone()[0] == 0
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_unavailable_market_is_saved_as_unknown_not_zero(client):
    client, _ = client
    _, adapter, _ = adapter_for([httpx.Response(404)])
    app.dependency_overrides[get_bol_client] = lambda: adapter
    preview = fetch(client)
    assert preview['status'] == 'partial'
    saved = save(client, preview).json()
    assert saved['preview']['market']['status'] == 'unavailable'
    assert saved['preview']['market']['derived']['offer_count'] is None
    with database.get_connection() as db:
        row = db.execute('SELECT status, payload FROM bol_market_snapshots').fetchone()
        assert row['status'] == 'unavailable'
        assert json.loads(row['payload'])['derived']['unique_seller_count'] is None


def test_second_measurement_creates_history_not_an_extra_identity(client):
    client, _ = client
    first = save(client, fetch(client)).json()
    second = save(client, fetch(client)).json()
    assert first['id'] != second['id']
    with database.get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM bol_product_identities').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM bol_market_snapshots').fetchone()[0] == 2
