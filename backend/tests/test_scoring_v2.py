from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.financial_v2 import FinancialInputs, calculate_financial
from app.analysis.scoring import calculate_scores
from app.analysis.scoring_v2 import ScoringInputs, calculate_decision, freshness
from app.core import database
from app.services import snapshots
from test_financial_v2 import inputs as financial_inputs, market as financial_market
from test_snapshots import client, fetch
from test_bol import EAN

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def prov(kind='manual_or_imported', when=NOW):
    return {'kind': kind, 'source': 'Fictitious documented acceptance evidence', 'recorded_at': when.isoformat()}


def financial(k=3, when=NOW):
    data = financial_inputs()
    data['landed_purchase_cost']['amount'] = str(k)
    def dates(value):
        if isinstance(value, dict):
            if 'provenance' in value:
                value['provenance'] = prov(when=when)
            for child in value.values():
                dates(child)
    dates(data)
    return data


def rating(sid, count, when):
    return {'id': sid, 'measured_at': when.isoformat(), 'payload': {
        'ean': EAN, 'bol_product_id': 'fictitious-id', 'source': 'bol Retailer API v10', 'api_version': 'v10',
        'language': 'nl', 'fetched_at': when.isoformat(), 'status': 'complete',
        'catalog': {'title': 'Fictitious acceptance product'},
        'endpoints': {'ratings': {'path': 'products/{ean}/ratings', 'version': 'v10', 'status': 'ok'}},
        'ratings': {'distribution': [{'rating': 1, 'count': min(2, count)}, {'rating': 5, 'count': max(0, count - 2)}]}}}


def market(sid=3, n=3, when=NOW, price=24.2):
    p = financial_market(measured_at=when.isoformat())
    p['offers'] = [{'offerId': str(i), 'retailerId': str(i), 'countryCode': 'NL', 'condition': 'NEW',
                    'price': price, 'bestOffer': i == 0, 'fulfilmentMethod': 'FBB',
                    'maxDeliveryDate': (when + timedelta(days=1)).date().isoformat()} for i in range(n)]
    return {'id': sid, 'measured_at': when.isoformat(), 'payload': p}


def case(k=3, n=3, growth=30, age=0, estimated=False):
    current = NOW - timedelta(days=age)
    raw = {'financial': financial(k), 'operational': {
        name: {'value': value, 'explanation': 'Documented fictitious assessment', 'provenance': prov()}
        for name, value in zip(('fragility', 'handling', 'obsolescence', 'supplier', 'inventory_exposure'), (0, 0, 0, 50, 50))},
        'delivery': {'market_snapshot_id': 3, 'offer_id': '0', 'days_later': 0, 'same_order_conditions': True,
                     'explanation': 'Compared for identical ordering conditions', 'provenance': prov(when=current)}}
    products = [rating(10, 90, NOW), rating(9, 90 - growth, NOW - timedelta(days=30))]
    if estimated:
        products = products[:1]
        raw['demand_estimate'] = {'monthly_sales_lower': 500, 'scope': 'market', 'method': 'Explicit test estimate',
                                 'provenance': prov('estimated')}
    return {'inputs': raw, 'ean': EAN, 'as_of': NOW, 'identity': {'ean': EAN, 'bol_product_id': 'fictitious-id'},
            'product_snapshots': products,
            'market_snapshots': [market(3, n, current), market(2, n, current - timedelta(days=4), 25.168),
                                 market(1, n, current - timedelta(days=8))]}


def run(data=None):
    data = deepcopy(case() if data is None else data)
    data['inputs'] = ScoringInputs.model_validate(data['inputs'])
    return calculate_decision(**data)


@pytest.mark.parametrize('name,k,n,growth,estimated,expected_p,expected_score,verdict', [
    ('A', 7, 20, 30, False, 92.5, 73.3422, 'Onderzoeken'),
    ('B', 12, 1, 30, False, 15.9722, 49, 'Twijfel'),
    ('C', 3, 3, 30, True, 100, 64, 'Onderzoeken'),
    ('D', 15, 3, 30, False, 0, 24, 'Niet inkopen'),
    ('E', 3, 3, 30, False, 100, 79.9591, 'Kansrijk'),
    ('G', 3, 3, 1, False, 100, 49, 'Twijfel')])
def test_design_acceptance_scenarios(name, k, n, growth, estimated, expected_p, expected_score, verdict):
    result = run(case(k=k, n=n, growth=growth, estimated=estimated))
    assert result['subscores']['profitability'] == pytest.approx(expected_p, abs=.001)
    assert result['opportunity_score'] == pytest.approx(expected_score, abs=.015)
    assert result['verdict'] == verdict
    assert result['subscores']['data_confidence'] == pytest.approx(75.75 if estimated else 84.5)
    assert result['financial']['base']['contribution_per_unit'] == f'{13-k:.4f}'


def test_design_f_uses_unchanged_24h_financial_policy_not_older_design_price():
    result = run(case(age=4))
    assert result['opportunity_score'] is None and result['verdict'] == 'Onderzoeken'
    assert result['subscores']['competition'] is not None
    assert result['metrics']['market']['quality'] == .5
    assert result['subscores']['profitability'] is None
    assert 'current_complete_market_price' in result['missing_critical_inputs']


def test_nonlinear_sellers_and_duplicate_retailers_are_separate_from_offer_count():
    three, nine = run(case(n=3)), run(case(n=9))
    assert 1 < three['subscores']['competition'] / nine['subscores']['competition'] < 2
    data = case()
    offer = deepcopy(data['market_snapshots'][0]['payload']['offers'][0])
    offer['offerId'] = 'another-offer-same-retailer'
    data['market_snapshots'][0]['payload']['offers'].append(offer)
    result = run(data)
    assert result['metrics']['market']['offer_count'] == 4
    assert result['metrics']['market']['unique_seller_count'] == 3
    assert result['subscores']['competition'] == three['subscores']['competition']


@pytest.mark.parametrize('change', [{'status': 'partial'}, {'pagination_complete': False}, {'offers': None},
                                     {'country': 'BE'}, {'api_version': 'v9'}, {'offers': [{}]},
                                     {'measured_at': 'not-a-date'}, {'measured_at': (NOW+timedelta(days=1)).isoformat()}])
def test_invalid_partial_market_never_means_low_competition(change):
    data = case()
    data['market_snapshots'][0]['payload'].update(change)
    result = run(data)
    assert result['subscores']['competition'] is None
    assert result['metrics']['market']['unique_seller_count'] is None
    assert result['opportunity_score'] is None


def test_missing_and_explicit_zero_offers_are_distinct_but_neither_scores_accessibility():
    empty = run(case(n=0))
    data = case()
    data['market_snapshots'] = []
    missing = run(data)
    assert empty['metrics']['market']['offer_count'] == 0
    assert missing['metrics']['market']['offer_count'] is None
    assert empty['subscores']['competition'] is missing['subscores']['competition'] is None
    assert empty['opportunity_score'] is missing['opportunity_score'] is None


def test_unknown_delivery_has_neutral_prior_and_lower_confidence_no_fake_metadata_bonus():
    data = case()
    data['inputs']['delivery'] = None
    result = run(data)
    assert result['metrics']['delivery']['score'] is None
    assert result['input_quality']['competition'] == .8
    assert result['subscores']['competition'] == pytest.approx(run()['subscores']['competition'] - 10)


@pytest.mark.parametrize('changes', [{'market_snapshot_id': 999}, {'offer_id': 'wrong'}, {'same_order_conditions': False}])
def test_delivery_must_reference_same_snapshot_offer_and_order_conditions(changes):
    data = case()
    data['inputs']['delivery'].update(changes)
    assert run(data)['metrics']['delivery']['score'] is None


@pytest.mark.parametrize('days,score', [(-1,100), (0,100), (1,50), (2,0)])
def test_delivery_thresholds(days, score):
    data = case()
    data['inputs']['delivery']['days_later'] = days
    assert run(data)['metrics']['delivery']['score'] == score


def test_extreme_roi_saturates_and_zero_is_not_infinite_roi():
    high = run(case(k=.0001))
    assert high['subscores']['profitability'] == 100
    assert high['metrics']['profitability']['roi'] == 100
    zero = run(case(k=0))
    assert zero['financial']['base']['contribution_per_unit'] == '13.0000'
    assert zero['subscores']['profitability'] is None and zero['opportunity_score'] is None
    missing = case()
    missing['inputs']['financial']['landed_purchase_cost'] = None
    assert run(missing)['financial']['base']['contribution_per_unit'] is None


def test_positive_but_stress_negative_capped_and_exact_zero_base_rejected():
    stress = run(case(k=12))
    assert 'stress_loss' in [s['code'] for s in stress['safeguards']]
    assert stress['opportunity_score'] <= 49
    zero = run(case(k=13))
    assert zero['opportunity_score'] <= 24 and zero['verdict'] == 'Niet inkopen'


def test_missing_stress_tariff_prevents_promising_without_fabricating_stress_loss():
    data = case()
    data['inputs']['financial']['commission'].update(flat_tariff_confirmed=False, valid_from_gross_price='23', valid_to_gross_price='25')
    result = run(data)
    assert result['financial']['stress']['contribution_per_unit'] is None
    assert result['opportunity_score'] <= 74 and result['verdict'] != 'Kansrijk'
    assert 'stress_loss' not in [s['code'] for s in result['safeguards']]


def test_no_demand_and_explicit_zero_growth_are_not_the_same():
    no = case()
    no['product_snapshots'] = no['product_snapshots'][:1]
    missing = run(no)
    zero = run(case(growth=0))
    assert missing['subscores']['demand'] is None and missing['input_quality']['demand'] == 0
    assert missing['opportunity_score'] <= 64 and missing['verdict'] != 'Kansrijk'
    assert zero['subscores']['demand'] == 0 and zero['input_quality']['demand'] == .6
    assert zero['opportunity_score'] <= 49


def test_rating_count_alone_never_proves_demand_and_estimate_not_double_counted():
    data = case()
    data['inputs']['demand_estimate'] = case(estimated=True)['inputs']['demand_estimate']
    assert run(data)['metrics']['demand']['route'] == 'rating_growth'
    assert run(data)['subscores']['demand'] == run()['subscores']['demand']


@pytest.mark.parametrize('days,usable', [(13,False), (14,True), (60,True), (61,False)])
def test_rating_interval_bounds(days, usable):
    data = case()
    data['product_snapshots'][1] = rating(9, 60, NOW-timedelta(days=days))
    assert (run(data)['subscores']['demand'] is not None) == usable


@pytest.mark.parametrize('changes', [ {'bol_product_id': 'different'}, {'language': 'en'}, {'ratings': None},
                                     {'ratings': {'distribution': [{'rating': 5, 'count': -1}]}},
                                     {'ratings': {'distribution': [{'rating': 5, 'count': 100}]}}])
def test_rating_identity_scope_invalid_counts_and_decreases(changes):
    data = case()
    data['product_snapshots'][1]['payload'].update(changes)
    assert run(data)['subscores']['demand'] is None


def test_intermediate_rating_drop_invalidates_otherwise_positive_endpoint_growth():
    data = case()
    data['product_snapshots'].append(rating(8, 100, NOW-timedelta(days=7)))
    assert run(data)['subscores']['demand'] is None


def test_stale_ratings_reduce_confidence_without_changing_raw_signal():
    data = case()
    data['product_snapshots'] = [rating(10,90,NOW-timedelta(days=37)), rating(9,60,NOW-timedelta(days=67))]
    result = run(data)
    assert result['subscores']['demand'] == 100
    assert result['input_quality']['demand'] == .3
    assert result['subscores']['data_confidence'] < run()['subscores']['data_confidence']


def test_unknown_operational_risks_are_exposed_not_claimed_zero():
    data = case()
    data['inputs']['operational'] = {}
    result = run(data)
    assert result['metrics']['risk']['operational']['score'] is None
    assert result['input_quality']['risk'] == pytest.approx(.4)
    assert result['subscores']['risk'] == pytest.approx(35)


def test_high_supported_risk_is_capped():
    data = case()
    for item in data['inputs']['operational'].values(): item['value'] = 100
    data['product_snapshots'][0]['payload']['ratings']['distribution'] = [{'rating': 1, 'count': 90}]
    result = run(data)
    assert result['subscores']['risk'] >= 75
    assert result['opportunity_score'] <= 49


def test_price_risk_needs_distinct_days_and_seven_day_span():
    data = case()
    data['market_snapshots'] = [market(3),market(2, when=NOW-timedelta(hours=1)), market(1,when=NOW-timedelta(hours=2))]
    assert run(data)['metrics']['risk']['price']['score'] is None
    assert run()['metrics']['risk']['price']['score'] == pytest.approx(20)


def test_low_confidence_means_research_not_fake_low_demand():
    data = case()
    data['inputs']['operational'] = {}
    data['product_snapshots'] = []
    data['market_snapshots'] = data['market_snapshots'][:1]
    data['inputs']['financial'] = financial(3, NOW-timedelta(days=80))
    result = run(data)
    assert result['subscores']['data_confidence'] < 50
    assert result['verdict'] == 'Onderzoeken'
    assert result['subscores']['demand'] is None


def test_confirmed_block_overrides_missing_data():
    data = case()
    data['inputs']['sales_block'] = {'confirmed': True, 'explanation': 'Fictitious sales restriction', 'provenance': prov()}
    data['market_snapshots'] = []
    assert run(data)['opportunity_score'] == 0 and run(data)['verdict'] == 'Niet inkopen'


@pytest.mark.parametrize('age,expected', [(1,1), (4,.5), (14,2**(-13/3)), (15,0), (-1,0)])
def test_market_freshness_bounds(age, expected):
    assert freshness((NOW-timedelta(days=age)).isoformat(), NOW, 'market') == pytest.approx(expected)


def test_pure_replay_explanation_config_hash_and_no_input_mutation():
    data = case()
    before = deepcopy(data)
    first = run(data)
    assert data == before
    frozen = first['frozen_evidence']
    replay = deepcopy(frozen)
    replay['as_of'] = datetime.fromisoformat(replay['as_of'])
    assert run(replay) == first
    canonical = json.dumps(first['score_config'], sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    assert first['score_config_hash'] == sha256(canonical.encode()).hexdigest()
    assert first['positive_drivers'] and first['financial']['financial_engine_version'] == '2.0.0-financial.1'
    assert first['provenance']['scores']['kind'] == 'derived'
    assert first['frozen_evidence']['inputs']['financial']['advertising_cost']['amount'] == '0'
    assert all(0 <= value <= 100 for value in first['subscores'].values())


def test_future_input_manual_price_override_and_bad_operational_value_rejected():
    data = case()
    data['inputs']['operational']['fragility']['provenance']['recorded_at'] = (NOW+timedelta(days=1)).isoformat()
    with pytest.raises(ValueError): run(data)
    data = case()
    data['inputs']['financial']['scenario_mode'] = 'manual'
    with pytest.raises(ValidationError): run(data)
    data = case()
    data['inputs']['operational']['fragility']['value'] = True
    with pytest.raises(ValidationError): run(data)


def test_v1_and_financial_v2_full_golden_outputs_remain_identical():
    fixtures = Path(__file__).parent / 'fixtures'
    for item in json.loads((fixtures/'scoring_v1_golden.json').read_text(encoding='utf-8')):
        assert calculate_scores(item['input']) == item['expected']
    for item in json.loads((fixtures/'financial_v2_golden.json').read_text(encoding='utf-8')):
        result = calculate_financial(FinancialInputs.model_validate(item['input']),
            as_of=datetime.fromisoformat(item['as_of']), market_payload=item['market'], snapshot_id=12)
        assert result == item['expected']


def test_api_server_loaded_evidence_readonly_no_live_requests_and_v1_financial_unchanged(client):
    client, calls = client
    preview = fetch(client)
    preview['market'] = market(when=datetime.now(timezone.utc))['payload']
    stored = snapshots.save_snapshot(snapshots.previews.issue(preview))
    request = {'ean': EAN, 'inputs': case()['inputs']}
    # Use a fixed past date; live test clock is not assumed to match fixture NOW.
    def past(value):
        if isinstance(value, dict):
            if 'recorded_at' in value: value['recorded_at'] = '2020-01-01T00:00:00+00:00'
            for v in value.values(): past(v)
    past(request)
    before = database.DB_PATH.read_bytes()
    legacy = client.get('/api/products').json()
    finance_body = {'ean': EAN, 'inputs': request['inputs']['financial']}
    financial_before = client.post('/api/financial/v2/calculate', json=finance_body).json()['v2_financial']['base']
    n = len(calls)
    response = client.post('/api/decision/v2/analyze', json=request)
    assert response.status_code == 200
    result = response.json()['analysis_v2']
    assert result['financial']['base'] == financial_before
    assert result['metrics']['market']['provenance']['snapshot_id'] == stored['id']
    assert response.headers['cache-control'] == 'no-store'
    assert len(calls) == n and database.DB_PATH.read_bytes() == before
    assert client.get('/api/products').json() == legacy
    assert client.post('/api/financial/v2/calculate', json=finance_body).json()['v2_financial']['base'] == financial_before
    assert 'preview_id' not in result['frozen_evidence']['product_snapshots'][0]['payload']


def test_api_rejects_injected_official_snapshots_and_invalid_ean(client):
    client, _ = client
    body = {'ean': EAN, 'inputs': {'financial': {}}}
    assert client.post('/api/decision/v2/analyze', json={**body, 'market_snapshots': []}).status_code == 422
    assert client.post('/api/decision/v2/analyze', json={**body, 'ean': '123'}).status_code == 422
    result = client.post('/api/decision/v2/analyze', json=body).json()['analysis_v2']
    assert result['opportunity_score'] is None and result['verdict'] == 'Onderzoeken'


def test_read_adapter_does_not_create_database(tmp_path, monkeypatch):
    from app.api.decision import read_evidence
    path = tmp_path/'absent.db'
    monkeypatch.setattr(database, 'DB_PATH', path)
    assert read_evidence(EAN) == (None, [], [])
    assert not path.exists()


def test_identity_conflict_requires_investigation():
    data = case()
    data['identity']['bol_product_id'] = 'other-product'
    result = run(data)
    assert result['opportunity_score'] is None and result['verdict'] == 'Onderzoeken'
    assert 'conflicting_product_identity' in result['missing_critical_inputs']


def test_caller_cannot_label_an_estimate_or_financial_input_official():
    data = case(estimated=True)
    data['inputs']['demand_estimate']['provenance']['kind'] = 'official_measured'
    with pytest.raises(ValidationError): run(data)
    data = case()
    data['inputs']['financial']['landed_purchase_cost']['provenance']['kind'] = 'official_measured'
    with pytest.raises(ValidationError): run(data)


def test_financial_estimates_carry_lower_confidence_than_documented_costs():
    data = case()
    data['inputs']['financial']['returns_loss_reserve']['provenance']['kind'] = 'estimated'
    result = run(data)
    assert result['subscores']['profitability'] == run()['subscores']['profitability']
    assert result['input_quality']['profitability'] == .25
    assert result['subscores']['data_confidence'] < run()['subscores']['data_confidence']
    assert result['verdict'] != 'Kansrijk'


def test_delivery_garbage_date_is_unknown():
    data = case()
    data['market_snapshots'][0]['payload']['offers'][0]['maxDeliveryDate'] = 'tomorrow maybe'
    assert run(data)['metrics']['delivery']['score'] is None


def test_changing_fulfilment_label_alone_never_changes_score():
    data = case()
    for row in data['market_snapshots'][0]['payload']['offers']: row['fulfilmentMethod'] = 'FBR'
    assert run(data)['subscores'] == run()['subscores']


def test_utc_ordering_and_same_day_deduplication():
    data = case()
    # Same instant, different textual offset; must not reorder history lexically.
    row = data['market_snapshots'][0]
    row['measured_at'] = row['payload']['measured_at'] = '2026-10-01T07:00:00-05:00'
    assert run(data)['subscores'] == run()['subscores']


@pytest.mark.parametrize('collection,field', [('market_snapshots','measured_at'), ('product_snapshots','fetched_at')])
def test_inconsistent_persisted_and_payload_times_fail_closed(collection, field):
    data = case()
    data[collection][0]['payload'][field] = (NOW-timedelta(days=1)).isoformat()
    result = run(data)
    target = 'competition' if collection == 'market_snapshots' else 'demand'
    assert result['subscores'][target] is None


def test_full_price_history_quality_and_missing_ratings_distribution():
    data = case()
    data['market_snapshots'] = [market(100-i, when=NOW-timedelta(days=i*5)) for i in range(7)]
    result = run(data)
    assert result['metrics']['risk']['price']['quality'] == 1
    assert result['metrics']['risk']['price']['score'] == 0
    data['product_snapshots'][0]['payload']['ratings']['distribution'] = []
    result = run(data)
    assert result['metrics']['risk']['quality']['score'] is None


@pytest.mark.parametrize('k,n', [(1,1), (1,100), (3,3), (12,5), (13,20), (15,1), (.0001,3)])
def test_scores_bounded_and_loss_safeguard_invariants(k, n):
    result = run(case(k=k,n=n))
    for score in result['subscores'].values():
        assert score is None or 0 <= score <= 100
    assert result['opportunity_score'] is None or 0 <= result['opportunity_score'] <= 100
    if k >= 13:
        assert result['opportunity_score'] <= 24 and result['verdict'] == 'Niet inkopen'


def test_latest_partial_snapshot_not_hidden_by_complete_history_via_api(client):
    client, _ = client
    preview = fetch(client)
    now = datetime.now(timezone.utc)
    preview['market'] = market(when=now-timedelta(minutes=1))['payload']
    snapshots.save_snapshot(snapshots.previews.issue(preview))
    preview['market'] = market(when=now)['payload']
    preview['market']['status'] = 'partial'
    newest = snapshots.save_snapshot(snapshots.previews.issue(preview))
    response = client.post('/api/decision/v2/analyze', json={'ean': EAN, 'inputs': {'financial': {}}})
    assert response.status_code == 200
    result = response.json()['analysis_v2']
    assert result['subscores']['competition'] is None
    assert result['financial']['price_selection']['market_reference']['snapshot_id'] == newest['id']


def test_read_adapter_handles_old_schema_and_invalid_json_without_writes(tmp_path, monkeypatch):
    import sqlite3
    from app.api.decision import read_evidence
    path = tmp_path/'old.db'
    monkeypatch.setattr(database, 'DB_PATH', path)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE products(id INTEGER)')
    db.commit()
    before = path.read_bytes()
    assert read_evidence(EAN) == (None, [], [])
    assert path.read_bytes() == before
    db.execute('CREATE TABLE bol_market_snapshots(snapshot_id INTEGER, ean TEXT, measured_at TEXT, payload TEXT)')
    db.execute('INSERT INTO bol_market_snapshots VALUES (1, ?, ?, ?)', (EAN,NOW.isoformat(),'invalid json'))
    db.commit()
    db.close()
    before = path.read_bytes()
    assert read_evidence(EAN)[2][0]['payload'] == {}
    assert path.read_bytes() == before
