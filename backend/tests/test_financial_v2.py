from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.financial_v2 import FinancialInputs, calculate_financial, market_reference
from app.analysis.scoring import calculate_scores
from app.core import database
from app.services import snapshots
from test_snapshots import client, fetch, save
from test_bol import EAN

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def evidence():
    return {'kind': 'manual_or_imported', 'source': 'Fictitious test quote',
            'recorded_at': '2020-01-01T00:00:00+00:00'}


def cost(amount, **changes):
    return {'amount': str(amount) if amount is not None else None, 'vat_basis': 'effective', 'provenance': evidence(), **changes}


def inputs(**changes):
    return {
        'planned_sale_price': {'amount': '24.20', 'vat_basis': 'inclusive', 'provenance': evidence()},
        'sales_vat_rate': {'value': '21', 'provenance': evidence()},
        'landed_purchase_cost': cost(7), 'fulfilment_cost': cost(3), 'advertising_cost': cost(0),
        'returns_loss_reserve': cost(1), 'other_allocated_cost': cost(0),
        'commission': {'fixed_fee': cost('.58'), 'variable_rate_percent': '10',
                       'variable_fee_vat_basis': 'effective', 'flat_tariff_confirmed': True, 'provenance': evidence()},
        **changes,
    }


def market(**changes):
    return {'source': 'bol Retailer API', 'country': 'NL', 'condition': 'NEW', 'currency': 'EUR', 'api_version': 'v10',
            'status': 'complete', 'pagination_complete': True, 'measured_at': NOW.isoformat(),
            'offers': [{'offerId': '1', 'countryCode': 'NL', 'condition': 'NEW', 'price': 24.2, 'bestOffer': True}], **changes}


def compute(value=None, observation=None):
    return calculate_financial(FinancialInputs.model_validate(inputs() if value is None else value),
                               as_of=NOW, market_payload=market() if observation is None else observation, snapshot_id=12)


def test_design_example_and_stress_are_exact_without_intermediate_rounding():
    result = compute()
    base, stress = result['base'], result['stress']
    assert base['status'] == 'complete'
    assert base['revenue_excluding_vat'] == '20.0000'
    assert base['sales_vat_amount'] == '4.2000'
    assert base['commission_fixed'] == '0.5800'
    assert base['commission_variable'] == '2.4200'
    assert base['commission_total'] == '3.0000'
    assert base['contribution_per_unit'] == '6.0000'
    assert base['contribution_margin_percent'] == '30.0000'
    assert base['inventory_roi_percent'] == '85.7143'
    assert stress['sale_price_including_vat'] == '21.7800'
    assert stress['revenue_excluding_vat'] == '18.0000'
    assert stress['commission_total'] == '2.7580'
    assert stress['effective_costs']['landed_purchase_cost'] == '7.0000'
    assert stress['effective_costs']['fulfilment_cost'] == '3.3000'
    assert stress['effective_costs']['returns_loss_reserve'] == '1.1000'
    assert stress['contribution_per_unit'] == '3.8420'
    assert stress['contribution_margin_percent'] == '21.3444'
    assert 'net_profit_per_unit' not in base and 'opportunity_score' not in result


def test_loss_is_preserved_not_clamped_or_given_a_verdict():
    result = compute(inputs(landed_purchase_cost=cost(15)))
    assert result['base']['contribution_per_unit'] == '-2.0000'
    assert result['base']['contribution_margin_percent'] == '-10.0000'
    assert result['base']['inventory_roi_percent'] == '-13.3333'
    assert result['stress']['contribution_per_unit'] == '-4.1580'
    assert 'verdict' not in result


def test_zero_investment_is_distinct_from_missing_investment():
    zero = compute(inputs(landed_purchase_cost=cost(0)))['base']
    missing = compute(inputs(landed_purchase_cost=None))['base']
    assert zero['status'] == 'complete' and zero['contribution_per_unit'] == '13.0000'
    assert zero['inventory_roi_percent'] is None and zero['roi_reason'] == 'zero_landed_purchase_cost'
    assert missing['status'] == 'incomplete' and missing['contribution_per_unit'] is None
    assert 'landed_purchase_cost' in missing['missing_inputs']


@pytest.mark.parametrize('field', ['planned_sale_price', 'sales_vat_rate', 'landed_purchase_cost', 'fulfilment_cost',
                                   'advertising_cost', 'returns_loss_reserve', 'other_allocated_cost', 'commission'])
def test_every_missing_financial_input_remains_unknown(field):
    result = compute(inputs(**{field: None}))
    assert result['base']['status'] == 'incomplete'
    assert result['base']['contribution_per_unit'] is None
    assert result['stress']['contribution_per_unit'] is None


def test_no_defaults_for_omitted_values():
    result = compute({})
    assert result['base']['revenue_excluding_vat'] is None
    assert all(v is None for v in result['base']['effective_costs'].values())
    assert result['base']['commission_total'] is None


def test_exclusive_sale_input_matches_equivalent_inclusive_input():
    value = inputs()
    value['planned_sale_price'].update(amount='20', vat_basis='exclusive')
    assert compute(value)['base'] == compute()['base']


def test_explicit_zero_sales_vat_is_not_missing_vat():
    value = inputs()
    value['sales_vat_rate']['value'] = '0'
    result = compute(value)['base']
    assert result['revenue_excluding_vat'] == '24.2000'
    assert result['sales_vat_amount'] == '0.0000'
    assert result['contribution_per_unit'] == '10.2000'


@pytest.mark.parametrize('basis,recoverable,amount,expected', [
    ('inclusive', True, '8.47', '7.0000'), ('inclusive', False, '8.47', '8.4700'),
    ('exclusive', True, '7', '7.0000'), ('exclusive', False, '7', '8.4700')])
def test_cost_vat_basis_and_recoverability(basis, recoverable, amount, expected):
    result = compute(inputs(landed_purchase_cost=cost(amount, vat_basis=basis, vat_rate_percent=21,
                                                     input_vat_recoverable=recoverable)))
    assert result['base']['effective_costs']['landed_purchase_cost'] == expected


def test_unconfirmed_cost_vat_metadata_is_not_treated_as_net():
    value = inputs(fulfilment_cost=cost(3, vat_basis='exclusive'))
    assert compute(value)['base']['effective_costs']['fulfilment_cost'] is None


def test_commission_vat_and_fixed_component_are_normalized():
    value = inputs()
    value['commission'].update(fixed_fee=cost('.7018', vat_basis='inclusive', vat_rate_percent=21, input_vat_recoverable=True),
                               variable_fee_vat_basis='exclusive', variable_fee_vat_rate_percent=21,
                               variable_fee_input_vat_recoverable=False)
    result = compute(value)['base']
    assert result['commission_fixed'] == '0.5800'
    assert result['commission_variable'] == '2.9282'
    assert result['commission_total'] == '3.5082'


def test_explicit_free_commission_works_but_missing_component_does_not():
    value = inputs()
    value['commission'].update(fixed_fee=cost(0), variable_rate_percent=0)
    assert compute(value)['base']['commission_total'] == '0.0000'
    value['commission']['fixed_fee'] = None
    assert compute(value)['base']['commission_total'] is None


def test_stress_does_not_blindly_apply_price_specific_commission():
    value = inputs()
    value['commission'].update(flat_tariff_confirmed=False, valid_from_gross_price='23', valid_to_gross_price='25')
    result = compute(value)
    assert result['base']['status'] == 'complete'
    assert result['stress']['commission_total'] is None
    assert result['stress']['contribution_per_unit'] is None
    assert 'commission_tariff_not_confirmed_for_price' in result['stress']['missing_inputs']


def test_unconfirmed_tariff_without_range_is_unknown():
    value = inputs()
    value['commission']['flat_tariff_confirmed'] = None
    assert compute(value)['base']['commission_total'] is None


def test_selects_lowest_best_offer_not_automatically_cheapest_offer():
    observation = market()
    observation['offers'] = [
        {'offerId': 'a', 'countryCode': 'NL', 'condition': 'NEW', 'price': 15, 'bestOffer': False},
        {'offerId': 'b', 'countryCode': 'NL', 'condition': 'NEW', 'price': 23, 'bestOffer': True},
        {'offerId': 'c', 'countryCode': 'NL', 'condition': 'NEW', 'price': 22, 'bestOffer': True}]
    result = compute(observation=observation)
    assert result['price_selection']['selected_gross_price'] == '22.0000'
    assert result['price_selection']['market_reference']['offer_id'] == 'c'
    assert result['price_selection']['reason'] == 'lowest_bol_best_offer'


def test_no_best_offer_falls_back_to_lowest_and_lower_manual_price_wins():
    observation = market()
    observation['offers'][0].update(price=20, bestOffer=False)
    result = compute(observation=observation)
    assert result['price_selection']['selected_gross_price'] == '20.0000'
    assert result['price_selection']['reason'] == 'lowest_offer_fallback'
    value = inputs()
    value['planned_sale_price']['amount'] = '18'
    assert compute(value, observation)['price_selection']['selected_gross_price'] == '18.0000'


def test_absent_market_keeps_manual_scenario_but_never_silently_uses_it_as_conservative():
    result = calculate_financial(FinancialInputs.model_validate(inputs()), as_of=NOW)
    assert result['base']['contribution_per_unit'] is None
    assert result['manual']['contribution_per_unit'] == '6.0000'
    assert result['price_selection']['reason'] == 'missing_market_snapshot'
    manual = calculate_financial(FinancialInputs.model_validate(inputs(scenario_mode='manual')), as_of=NOW)
    assert manual['base']['contribution_per_unit'] == '6.0000'
    assert manual['price_selection']['reason'] == 'explicit_manual_scenario'


@pytest.mark.parametrize('changes', [dict(status='partial'), dict(pagination_complete=False), dict(country='BE'),
                                    dict(condition='AS_NEW'), dict(currency='USD'), dict(api_version='v9'),
                                    dict(offers=[]), dict(offers=None), dict(offers=[None]),
                                    dict(measured_at=(NOW - timedelta(hours=24, seconds=1)).isoformat()),
                                    dict(measured_at=(NOW + timedelta(seconds=1)).isoformat()),
                                    dict(measured_at='2026-09-30T12:00:00')])
def test_unsuitable_market_never_becomes_a_zero_price(changes):
    result = compute(observation=market(**changes))
    assert result['price_selection']['selected_gross_price'] is None
    assert result['base']['contribution_per_unit'] is None


def test_market_corruption_and_zero_price_are_rejected():
    observation = market()
    observation['offers'][0]['price'] = 0
    assert compute(observation=observation)['base']['status'] == 'incomplete'
    assert market_reference([], 1, NOW)['reason'] == 'invalid_market_snapshot'
    assert market_reference(market(measured_at=(NOW - timedelta(hours=24)).isoformat()), 1, NOW)['status'] == 'usable'


@pytest.mark.parametrize('field,value', [('planned_sale_price', 0), ('planned_sale_price', -1),
                                       ('landed_purchase_cost', -1), ('fulfilment_cost', True),
                                       ('advertising_cost', 'NaN'), ('returns_loss_reserve', 'Infinity'),
                                       ('other_allocated_cost', '1.00001'), ('landed_purchase_cost', 1000000001)])
def test_impossible_amounts_are_validation_errors(field, value):
    data = inputs()
    data[field]['amount'] = value
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)


@pytest.mark.parametrize('value', [-1, 101, True, 'Infinity', 'NaN'])
def test_invalid_vat_percentages(value):
    data = inputs()
    data['sales_vat_rate']['value'] = value
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)


def test_invalid_commission_and_ambiguous_tax_basis_are_rejected():
    data = inputs()
    data['commission']['variable_rate_percent'] = 101
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)
    data = inputs(fulfilment_cost=cost(3, vat_rate_percent=21))
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)
    data = inputs()
    data['commission'].update(valid_from_gross_price=25, valid_to_gross_price=20)
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)


def test_provenance_is_required_timezone_aware_and_never_future():
    data = inputs()
    del data['landed_purchase_cost']['provenance']
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)
    data = inputs()
    data['landed_purchase_cost']['provenance']['recorded_at'] = '2026-09-30T10:00:00'
    with pytest.raises(ValidationError): FinancialInputs.model_validate(data)
    data['landed_purchase_cost']['provenance']['recorded_at'] = (NOW + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError): compute(data)


def test_purity_provenance_and_versioned_output():
    data, observation = inputs(), market()
    before = deepcopy((data, observation))
    result = compute(data, observation)
    assert (data, observation) == before
    assert compute(data, observation) == result
    assert result['financial_engine_version'] == '2.0.0-financial.1'
    assert result['inputs']['landed_purchase_cost']['provenance']['kind'] == 'manual_or_imported'
    assert result['price_selection']['market_reference']['provenance']['kind'] == 'official_measured'
    assert result['price_selection']['market_reference']['provenance']['snapshot_id'] == 12
    assert result['calculation_provenance']['kind'] == 'derived'


def test_v1_golden_outputs_are_unchanged_for_original_sample_and_all_seed_products():
    fixture = Path(__file__).parent / 'fixtures/scoring_v1_golden.json'
    for case in json.loads(fixture.read_text(encoding='utf-8')):
        assert calculate_scores(case['input']) == case['expected']


def test_api_uses_saved_market_and_never_modifies_database_or_v1_outputs(client):
    client, _ = client
    preview = fetch(client)
    preview['market'] = market(measured_at=datetime.now(timezone.utc).isoformat())
    saved = snapshots.save_snapshot(snapshots.previews.issue(preview))
    before = database.DB_PATH.read_bytes()
    products_before = client.get('/api/products').json()
    response = client.post('/api/financial/v2/calculate', json={'ean': EAN, 'market_snapshot_id': saved['id'], 'inputs': inputs()})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()['v2_financial']
    assert result['base']['contribution_per_unit'] == '6.0000'
    assert result['price_selection']['market_reference']['snapshot_id'] == saved['id']
    assert database.DB_PATH.read_bytes() == before
    assert client.get('/api/products').json() == products_before


def test_api_rejects_snapshot_for_other_ean_and_client_injected_market(client):
    client, _ = client
    stored = save(client, fetch(client)).json()
    assert client.post('/api/financial/v2/calculate', json={'ean': '0842776106209', 'market_snapshot_id': stored['id'], 'inputs': inputs()}).status_code == 404
    assert client.post('/api/financial/v2/calculate', json={'inputs': inputs(), 'market': market()}).status_code == 422
    assert client.post('/api/financial/v2/calculate', json={'inputs': inputs(), 'market_snapshot_id': 1}).status_code == 422


def test_api_missing_market_is_explicit_and_validation_does_not_write(client):
    client, _ = client
    before = database.DB_PATH.read_bytes()
    response = client.post('/api/financial/v2/calculate', json={'ean': EAN, 'inputs': inputs()})
    assert response.status_code == 200
    assert response.json()['v2_financial']['base']['status'] == 'incomplete'
    bad = inputs(landed_purchase_cost=cost(-1))
    assert client.post('/api/financial/v2/calculate', json={'inputs': bad}).status_code == 422
    assert database.DB_PATH.read_bytes() == before


def test_api_does_not_hide_newer_partial_snapshot_behind_old_complete_one(client):
    client, _ = client
    preview = fetch(client)
    current = datetime.now(timezone.utc)
    preview['market'] = market(measured_at=(current - timedelta(minutes=2)).isoformat())
    snapshots.save_snapshot(snapshots.previews.issue(preview))
    preview['market'] = market(status='partial', measured_at=current.isoformat())
    saved = snapshots.save_snapshot(snapshots.previews.issue(preview))
    result = client.post('/api/financial/v2/calculate', json={'ean': EAN, 'inputs': inputs()}).json()['v2_financial']
    assert result['price_selection']['market_reference']['snapshot_id'] == saved['id']
    assert result['base']['contribution_per_unit'] is None
