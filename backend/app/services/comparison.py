"""Read-only presentation composition; both scoring engines remain unchanged."""
from math import isfinite

from app.analysis.scoring import calculate_scores
from app.analysis.scoring_v2 import ScoringInputs, calculate_decision, stamp
from app.api.decision import read_evidence
from app.services.bol import BolError, validate_ean


def reason_for_difference(v1, v2, market):
    """Deterministic explanation priority, not a claim of causal attribution."""
    if market['freshness'] == 'stale':
        return {'code': 'stale_market', 'text': 'Marktmeting ouder dan 24 uur: vernieuw de marktgegevens voor een actuele v2-beoordeling.'}
    codes = {s['code'] for s in v2['safeguards']}
    reasons = {
        'block': 'V2 ziet een bevestigde verkoopblokkade.',
        'loss': 'V2 berekent een niet-positieve bijdrage na de opgenomen kosten.',
        'stress_loss': 'De bijdrage wordt nul of negatief in de v2-stresstest.',
        'high_risk': 'V2 begrenst de score vanwege onderbouwd hoog risico.',
        'weak_demand': 'Het onderbouwde vraagsignaal is zwak.',
    }
    for code, text in reasons.items():
        if code in codes:
            return {'code': code, 'text': text}
    if v2['opportunity_score'] is None:
        return {'code': 'incomplete_evidence', 'text': 'V2 mist kritieke bewijsgegevens; de opgeslagen legacy-invoer bevat geen volledige financiële v2-basis.'}
    if 'confidence_below_50' in codes or 'confidence_below_75' in codes or 'unproven_demand' in codes:
        return {'code': 'low_confidence', 'text': 'V2 begrenst de beoordeling door onvoldoende datakwaliteit of vraagbewijs.'}
    competition = v2['subscores']['competition']
    if competition is not None and competition < 50 and v2['opportunity_score'] < v1['opportunity_score']:
        return {'code': 'competition', 'text': 'V2 ziet sterke concurrentiedruk in de opgeslagen bol-aanbiedingen.'}
    if v1['verdict'] == v2['verdict']:
        return {'code': 'agreement', 'text': 'Beide engines geven hetzelfde verdict; formules en bewijsbasis verschillen.'}
    return {'code': 'different_model', 'text': 'V2 gebruikt andere financiële definities, bewijsweging en veiligheidsgrenzen. Bekijk de drivers en caps.'}


def market_context(v2):
    evidence = v2['frozen_evidence']['market_snapshots']
    latest = evidence[0] if evidence else None
    payload = latest.get('payload', {}) if latest else {}
    measured = payload.get('measured_at')
    age = None
    try:
        age = (stamp(v2['as_of']) - stamp(measured)).total_seconds() / 3600
        if age < 0:
            age = None
    except (ValueError, TypeError):
        pass
    metrics = v2['metrics']['market']
    return {'snapshot_id': latest['id'] if latest else None, 'measured_at': measured,
            'age_hours': age, 'freshness': 'missing' if not latest else ('invalid' if age is None else ('stale' if age > 24 else 'fresh')),
            'source': payload.get('source'), 'api_version': payload.get('api_version'),
            'status': metrics['status'], 'price_min': metrics['price_min'], 'price_max': metrics['price_max'],
            'unique_seller_count': metrics['unique_seller_count'], 'offer_count': metrics['offer_count'],
            'data_kind': 'official_measured', 'counts_kind': 'derived'}


def present_comparison(product, v2):
    """Accepts engine results internally; never accepts client-provided analyses."""
    v1 = calculate_scores(product)
    market = market_context(v2)
    legacy = []
    for key, label, kind, unit in [
        ('sale_price', 'Geplande verkoopprijs', 'manual_or_imported', 'EUR'),
        ('purchase_price', 'Inkoopprijs', 'manual_or_imported', 'EUR'),
        ('shipping_cost', 'Verzendkosten', 'manual_or_imported', 'EUR'),
        ('commission_rate', 'Legacy commissiepercentage', 'manual_or_imported', '%'),
        ('monthly_sales_low', 'Ondergrens geschatte maandverkopen', 'estimated', 'per maand'),
        ('monthly_sales_high', 'Bovengrens geschatte maandverkopen', 'estimated', 'per maand'),
    ]:
        value = product.get(key)
        if not isinstance(value, (int, float)) or not isfinite(value):
            value = None
        legacy.append({'field': key, 'label': label, 'value': value, 'unit': unit,
                       'kind': kind, 'source': 'Opgeslagen ProductRadar-invoer', 'recorded_at': None,
                       'used_in_v2': False})
    return {'product': {k: product.get(k) for k in ('id', 'name', 'ean', 'category')},
            'evaluated_at': v2['as_of'], 'default_engine': 'v1', 'analysis_v1': v1,
            'analysis_v2': {k: v2[k] for k in ('decision_engine_version', 'score_config_version', 'analysis_id',
                'status', 'subscores', 'opportunity_score', 'verdict', 'verdict_reason', 'safeguards',
                'positive_drivers', 'negative_drivers', 'missing_critical_inputs', 'unknown_signals', 'readiness_missing')},
            'market': market, 'legacy_inputs': legacy,
            'primary_reason': reason_for_difference(v1, v2, market),
            'input_notice': ('De financiële v2-basis is onvolledig. Legacy-bedragen blijven zichtbaar, maar worden niet automatisch omgezet: btw-basis, volledige kosten, tariefcontext en brondatums moeten expliciet vastliggen.'
                             if v2['financial']['base']['status'] != 'complete' else
                             'De v2-berekening gebruikt expliciete financiële bewijsgegevens. De legacy-bedragen hieronder kunnen andere definities hebben en worden niet automatisch als v2-invoer behandeld.')
                             + ' Verkoopranges zonder vastgelegde scope of methode worden niet automatisch als v2-vraagbewijs gebruikt.',
            'difference_notice': 'De hoofdreden is een samenvatting van bewijs en safeguards; geen exacte causale uitsplitsing van het scoreverschil.'}


def compare_saved_product(product, as_of):
    ean = product.get('ean') or ''
    try:
        validate_ean(ean)
        identity, products, markets = read_evidence(ean)
    except BolError:
        identity, products, markets = None, [], []
    # Do not manufacture a VAT basis, missing costs or an input timestamp from legacy values.
    result = calculate_decision(ScoringInputs(financial={}), as_of=as_of, ean=ean,
                                identity=identity, product_snapshots=products, market_snapshots=markets)
    return present_comparison(product, result)
