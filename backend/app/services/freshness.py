"""One market selection/classification for presentation and read-only API adapters.

Financial/scoring formulae are unchanged. A failed or interrupted refresh is
evidence of unavailable current data, never a reason to reuse an older price.
"""
from datetime import datetime, timezone, timedelta
import json
from app.analysis.scoring_v2 import observed_market, stamp

LEASE_SECONDS = 4500  # Bounded lease; interrupted runs remain fail-closed on reads.


def order(record):
    try:
        return stamp(record['measured_at']), record.get('id') or 0
    except (ValueError, TypeError, KeyError):
        return datetime.max.replace(tzinfo=timezone.utc), record.get('id') or 0


def relevant(records):
    # Invalid payloads fail closed; a corrupted newest row must not disappear.
    # DB loader scopes by persisted NL/NEW columns. Never discard the newest
    # scoped row because its payload has conflicting or malformed metadata.
    return sorted(records, key=order, reverse=True)


def load_market_records(db, ean):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = []
    if 'bol_market_snapshots' in tables:
        columns={r[1] for r in db.execute('PRAGMA table_info(bol_market_snapshots)')}
        segment=" AND country='NL' AND condition='NEW'" if {'country','condition'} <= columns else ''
        raw = db.execute('SELECT snapshot_id, measured_at, payload FROM bol_market_snapshots WHERE ean=?'+segment+
                         ' ORDER BY measured_at DESC, snapshot_id DESC LIMIT 2001', (ean,)).fetchall()
        for sid, when, body in raw:
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, TypeError):
                payload = {}
            allowed={'source','api_version','endpoint','country','condition','currency','measured_at',
                     'status','pagination_complete','offers','refresh_error_code'}
            rows.append({'id': sid, 'measured_at': when, 'payload': {k:v for k,v in payload.items() if k in allowed}})
    if 'bol_market_refresh_requests' in tables:
        attempt = db.execute('''SELECT request_id, started_at, state, snapshot_id FROM bol_market_refresh_requests
                                WHERE ean=? ORDER BY started_at DESC, request_id DESC LIMIT 1''', (ean,)).fetchone()
        if attempt and attempt[2] == 'running':
            # Also blocks after an interrupted process/expired lease; a subsequent
            # explicit refresh may replace the attempt. No reads mutate the database.
            payload = {'source': 'bol Retailer API', 'api_version': 'v10',
                       'endpoint': 'products/{ean}/offers', 'country': 'NL', 'condition': 'NEW',
                       'currency': 'EUR', 'measured_at': attempt[1], 'status': 'unavailable',
                       'pagination_complete': False, 'offers': [], 'refresh_pending': True}
            rows.append({'id': 0, 'measured_at': attempt[1], 'payload': payload})
    return relevant(rows)


def classify(records, as_of):
    records = relevant(records)
    latest = records[0] if records else None
    p = latest.get('payload', {}) if latest else {}
    result = {'freshness': 'missing', 'reason': 'no_market_measurement', 'age_hours': None,
              'measured_at': p.get('measured_at'), 'snapshot_id': latest['id'] if latest and latest['id'] else None,
              'source': p.get('source'), 'api_version': p.get('api_version'), 'status': 'unknown',
              'usable_for_current_analysis': False, 'price_min': None, 'price_max': None,
              'offer_count': None, 'unique_seller_count': None, 'relevant_offer': None,
              'relevant_price': None, 'offer_data_kind': 'official_measured' if p.get('offers') else None,
              'data_kind': 'official_measured' if p.get('offers') else None,
              'counts_kind': 'derived', 'freshness_kind': 'derived', 'as_of': as_of.isoformat(),
              'freshness_version':'market-freshness/1.0',
              'freshness_provenance':{'kind':'derived','source':'ProductRadar market-freshness/1.0',
                                     'recorded_at':as_of.isoformat(),'snapshot_id':latest['id'] if latest and latest['id'] else None}}
    if latest is None:
        return result
    result.update(freshness='error', reason='invalid_measurement')
    try:
        measured = stamp(p['measured_at'])
        if measured != stamp(latest['measured_at']) or measured > as_of:
            return result
        age = as_of - measured
        result['age_hours'] = age.total_seconds() / 3600
        if p.get('refresh_pending'):
            running = age <= timedelta(seconds=LEASE_SECONDS)
            result['reason'] = 'refresh_in_progress' if running else 'refresh_interrupted'
            return result
        if p.get('status') != 'complete':
            result['freshness'] = 'incomplete' if p.get('status') == 'partial' else 'error'
            result['reason'] = 'latest_measurement_incomplete' if p.get('status') == 'partial' else 'latest_measurement_failed'
            return result
        metrics = observed_market(latest, as_of)
        if metrics['status'] != 'complete':
            return result
        if not metrics['offer_count']:
            result['freshness'], result['reason'] = 'missing', 'complete_measurement_without_offers'
            return result
        status = 'current' if age <= timedelta(hours=24) else ('stale' if age <= timedelta(hours=72) else 'historical')
        result.update(freshness=status, reason='complete_within_24_hours' if status == 'current' else
                      ('older_than_24_hours' if status == 'stale' else 'older_than_72_hours'), status='complete',
                      usable_for_current_analysis=status == 'current',
                      price_min=metrics['price_min'], price_max=metrics['price_max'],
                      offer_count=metrics['offer_count'], unique_seller_count=metrics['unique_seller_count'],
                      relevant_offer=metrics['relevant_offer'], relevant_price=metrics['reference']['price'])
    except (ValueError, TypeError, KeyError, ArithmeticError):
        pass
    return result
