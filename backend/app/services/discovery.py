"""Separate append-only discovery evidence; never writes legacy product/snapshot tables."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from fastapi import HTTPException
from app.core import database
from app.services.bol import validate_ean
from app.services.freshness import classify


def migrate_discovery(db):
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ean TEXT UNIQUE,
        discovered_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS discovery_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL REFERENCES discovery_candidates(id),
        source TEXT NOT NULL, measured_at TEXT NOT NULL, fingerprint TEXT NOT NULL,
        payload TEXT NOT NULL, UNIQUE(candidate_id,fingerprint))''')
    db.execute('CREATE INDEX IF NOT EXISTS discovery_observation_candidate ON discovery_observations(candidate_id,id)')


@contextmanager
def connection(write=False):
    if not database.DB_PATH.exists():
        raise HTTPException(503, 'Database nog niet beschikbaar.')
    db = sqlite3.connect(database.DB_PATH.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    except sqlite3.Error:
        raise HTTPException(503, 'Discovery-opslag tijdelijk niet beschikbaar.') from None
    finally:
        db.close()


def save_records(records):
    """Only server-normalized provider evidence, no caller-injected official claims."""
    ids = []
    with connection(True) as db:
        db.execute('BEGIN IMMEDIATE')
        migrate_discovery(db)
        for record in records:
            validate_ean(record['ean'])
            when = datetime.fromisoformat(record['measured_at'])
            if when.utcoffset() is None or when > datetime.now(timezone.utc):
                raise ValueError('Invalid observation time')
            db.execute('INSERT OR IGNORE INTO discovery_candidates(ean,discovered_at) VALUES (?,?)',
                       (record['ean'], record['measured_at']))
            cid = db.execute('SELECT id FROM discovery_candidates WHERE ean=?', (record['ean'],)).fetchone()[0]
            raw = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            db.execute('''INSERT OR IGNORE INTO discovery_observations
                          (candidate_id,source,measured_at,fingerprint,payload) VALUES (?,?,?,?,?)''',
                       (cid, record['source'], record['measured_at'], sha256(raw.encode()).hexdigest(), raw))
            ids.append(cid)
    return sorted(set(ids))


def candidates(as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    with connection() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_candidates'").fetchone():
            return []
        result = []
        for candidate in db.execute('SELECT * FROM discovery_candidates ORDER BY id'):
            rows = db.execute('SELECT id,payload FROM discovery_observations WHERE candidate_id=? ORDER BY measured_at DESC,id DESC', (candidate['id'],)).fetchall()
            evidence = [{'observation_id': r['id'], **json.loads(r['payload'])} for r in rows]
            result.append(present(dict(candidate), evidence, as_of))
        return result


def present(candidate, evidence, as_of):
    listing = next((r for r in evidence if r['source']=='bol_product_list'), None)
    enrichment = next((r for r in evidence if r['source']=='bol_ean_preview'), None)
    preview = enrichment.get('preview', {}) if enrichment else {}
    catalog = preview.get('catalog') or {}
    ratings = preview.get('ratings')
    market_records = [{'id': r['observation_id'], 'measured_at': r['measured_at'],
                       'payload': r['preview']['market']} for r in evidence
                      if r['source']=='bol_ean_preview' and r.get('preview', {}).get('market')]
    market = classify(market_records, as_of)
    now = as_of.isoformat()
    def signal(value, record, kind=None):
        return {'value': value, 'provenance': None if not record else
                {'kind': kind or record['kind'], 'source': record['source'], 'endpoint': record['endpoint'],
                 'api_version': record['api_version'], 'recorded_at': record['measured_at'],
                 'observation_id': record['observation_id']}}
    signals = {
        'product_identity': signal({'ean':candidate['ean'],'bol_product_id':preview.get('bol_product_id')}, listing or enrichment),
        'title': signal(catalog.get('title') or (listing['title'] if listing else None), enrichment if catalog.get('title') else listing),
        'brand': signal(catalog.get('brand'), enrichment),
        'search_category': signal(listing.get('category') if listing else None, listing, 'derived'),
        'catalog': signal(catalog or None, enrichment),
        'rating_distribution': signal(ratings.get('distribution') if ratings else None, enrichment),
        'rating_average': signal(ratings.get('average') if ratings else None, enrichment, 'derived'),
        'rating_count': signal(ratings.get('count') if ratings else None, enrichment, 'derived'),
        'offers': signal(preview.get('market', {}).get('offers') if enrichment and preview.get('market', {}).get('status')=='complete' else None, enrichment),
        'visibility': signal({'list_position': listing['list_position'], 'query': listing['query']} if listing else None, listing, 'derived'),
        'ranking_impressions': signal(None, None), 'white_spots': signal(None, None),
        'sales_volume': signal(None, None), 'rating_growth': signal(None, None),
    }
    latest = evidence[0] if evidence else None
    age = (as_of-datetime.fromisoformat(latest['measured_at'])).total_seconds()/3600 if latest else None
    # Transparent evidence coverage, not commercial merit or probability.
    groups = {'identity': bool(candidate['ean']), 'catalog': bool(catalog.get('title')),
              'ratings': ratings is not None, 'market': market['usable_for_current_analysis'], 'visibility': listing is not None}
    def freshness_weight(record):
        if not record: return 0
        hours=(as_of-datetime.fromisoformat(record['measured_at'])).total_seconds()/3600
        return 1 if 0<=hours<=24 else .5 if 24<hours<=72 else .25 if hours>72 else 0
    weights={'identity':1,'catalog':freshness_weight(enrichment),'ratings':freshness_weight(enrichment),
             'market':1,'visibility':freshness_weight(listing)}
    quality = sum(20*weights[k] for k,v in groups.items() if v)
    reasons = []
    if market['usable_for_current_analysis'] and market['unique_seller_count'] is not None and market['unique_seller_count'] >= 20:
        status = 'Hoge concurrentie'; reasons.append('Actuele volledige marktmeting: minstens 20 unieke verkopers (onderzoekslabel, geen inkoopadvies).')
    elif listing and freshness_weight(listing)==1 and market['usable_for_current_analysis'] and ratings and (ratings.get('average') or 0)>=4 and ratings.get('count',0)>=10:
        status = 'Interessant signaal'; reasons.append('Zichtbaar in zoekcontext, minimaal 10 ratings met gemiddelde ≥4 en actuele marktmeting; vraag niet bewezen.')
    elif market['usable_for_current_analysis'] or listing:
        status = 'Verder onderzoeken'; reasons.append('Zoekzichtbaarheid of actuele marktinformatie beschikbaar; vraag en financiële haalbaarheid nog onderzoeken.')
    else:
        status = 'Onvoldoende bewijs'; reasons.append('Geen actuele volledige marktmeting of lijstzichtbaarheid beschikbaar.')
    title = catalog.get('title') or (listing['title'] if listing else None)
    return {**candidate, 'title': title, 'brand': catalog.get('brand'),
            'bol_product_id': preview.get('bol_product_id'),
            'category': listing.get('category') if listing else None,
            'catalog_classification_id': catalog.get('classification_id'),
            'category_notice': 'Catalogus-GPC en zoekcategorie zijn verschillende classificaties; geen afgeleide placement.',
            'last_measured_at': latest['measured_at'] if latest else None, 'age_hours': age,
            'sources': sorted({r['source'] for r in evidence}), 'signals': signals,
            'signal_groups': {'demand':['visibility','rating_average','rating_count','rating_growth','sales_volume'],
                              'competition':['unique_seller_count','offer_count'],
                              'price_market':['relevant_price','price_min','price_max','offers'],
                              'evidence_quality':['evidence_groups','freshness']},
            'completeness': {'list_scope':'page_1_only' if listing else None,
                             'market':market['status'],'ratings_available':ratings is not None},
            'market': market, 'market_history': [classify([r], as_of) for r in market_records],
            'evidence_quality': quality, 'evidence_groups': groups, 'evidence_kind': 'derived',
            'quality_notice': 'Bewijsdekking: maximaal 20 per groep (identifier, catalogus, ratings, actuele markt, zoekzichtbaarheid). Catalogus/ratings/zichtbaarheid wegen 100% ≤24u, 50% ≤72u, 25% ouder; actuele markt anders 0. Geen verkoopkans.',
            'status': status, 'reasons': reasons, 'opportunity_score': None,
            'financial_notice': 'Nog geen inkoopadvies — financiële gegevens ontbreken',
            'missing': [k for k,v in groups.items() if not v]+['financial_profile','verified_demand','sales_volume'],
            'evidence': evidence, 'evaluated_at': now}


def filter_candidates(items, *, category=None, source=None, freshness=None, max_sellers=None,
                      min_price=None, max_price=None, min_quality=0, sort='discovered'):
    def matches(x):
        m=x['market']; price=m['relevant_price'] if m['usable_for_current_analysis'] else None
        sellers=m['unique_seller_count'] if m['usable_for_current_analysis'] else None
        return ((category is None or x['category']==category) and (source is None or source in x['sources'])
                and (freshness is None or m['freshness']==freshness) and x['evidence_quality']>=min_quality
                and (max_sellers is None or sellers is not None and sellers<=max_sellers)
                and (min_price is None or price is not None and float(price)>=min_price)
                and (max_price is None or price is not None and float(price)<=max_price))
    selected=[x for x in items if matches(x)]
    if sort=='quality': selected.sort(key=lambda x:(-x['evidence_quality'],x['id']))
    elif sort=='sellers': selected.sort(key=lambda x:(not x['market']['usable_for_current_analysis'] or x['market']['unique_seller_count'] is None,
                                                    x['market']['unique_seller_count'] if x['market']['usable_for_current_analysis'] and x['market']['unique_seller_count'] is not None else 0,x['id']))
    else: selected.sort(key=lambda x:(x['discovered_at'],x['id']),reverse=True)
    return selected
