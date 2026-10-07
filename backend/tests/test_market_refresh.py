from copy import deepcopy
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import json
import sqlite3
import pytest
import httpx
from app.core import database
from app.main import app
from app.api.bol import get_bol_client
from app.api.decision import read_evidence
from app.api.financial import read_market
from app.services.freshness import classify, LEASE_SECONDS
from app.services.market_refresh import refresh, migrate_refresh
from app.services.bol import BolError
from app.services import snapshots
from test_comparison import readonly_client
from test_scoring_v2 import case, NOW, financial, EAN
from test_financial_profiles import profile, preview as finance_preview, save as finance_save
from test_bol import setup_client
from test_market import offer
from app.services.bol import BolClient
ORIGINAL_GET = BolClient._get


def record(age=0,**changes):
    r=deepcopy(case()['market_snapshots'][0]);when=(NOW-timedelta(hours=age)).isoformat()
    r['measured_at']=when;r['payload']['measured_at']=when;r['payload'].update(changes)
    return r


@pytest.mark.parametrize('age,status',[(0,'current'),(24,'current'),(24+1/3600,'stale'),(72,'stale'),(72+1/3600,'historical'),(144,'historical')])
def test_exact_freshness_boundaries(age,status):
    c=classify([record(age)],NOW)
    assert c['freshness']==status and c['age_hours']==pytest.approx(age)
    assert c['usable_for_current_analysis']==(status=='current') and c['freshness_kind']=='derived'
    assert c['data_kind']=='official_measured' and c['counts_kind']=='derived'


@pytest.mark.parametrize('changes,status,reason',[
    ({'status':'partial'},'incomplete','latest_measurement_incomplete'),
    ({'status':'unavailable'},'error','latest_measurement_failed'),
    ({'pagination_complete':False},'error','invalid_measurement'),
    ({'country':'BE'},'error','invalid_measurement'),
    ({'offers':[]},'missing','complete_measurement_without_offers'),
])
def test_bad_newest_never_falls_back(changes,status,reason):
    latest=record(1,**changes);older=record(2);older['id']=2
    c=classify([older,latest],NOW)
    assert c['freshness']==status and c['reason']==reason and not c['usable_for_current_analysis']
    assert c['price_min'] is None and c['unique_seller_count'] is None


def test_missing_invalid_future_and_conflicting_timestamp():
    assert classify([],NOW)['freshness']=='missing'
    for r in [record(-1),record(1,measured_at='bad')]:
        assert classify([r,record(5)],NOW)['freshness']=='error'
    r=record(1);r['measured_at']='bad';assert classify([r,record(5)],NOW)['reason']=='invalid_measurement'


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(snapshots,'previews',snapshots.PreviewStore())
    yield
    app.dependency_overrides.pop(get_bol_client,None)


def legacy_rows():
    with database.get_connection() as db:
        return {table:[tuple(r) for r in db.execute('SELECT * FROM '+table)] for table in ('products','financial_input_versions','bol_product_identities')}


def adapter(readonly_client,handler=None):
    _,bol,calls=setup_client(handler or (lambda request:httpx.Response(200,json={'offers':[offer(1,bestOffer=True)]}) if request.url.path.endswith('/offers') else None))
    # readonly_client intentionally blocks real _get; bind the original class
    # transport method from the fixture client without allowing any real network.
    bol._get=ORIGINAL_GET.__get__(bol,BolClient)
    app.dependency_overrides[get_bol_client]=lambda:bol
    return bol,calls


def request(client,rid=None,pid=1):
    return client.post(f'/api/products/{pid}/market-refresh',json={'request_id':rid or str(uuid4())})


def test_refresh_success_history_duplicate_profiles_and_v1_unchanged(readonly_client):
    client,path=readonly_client
    data=profile();finance_save(client,data,finance_preview(client,data).json()['preview_id'])
    original=legacy_rows();v1=client.get('/api/products/1').json();_,calls=adapter(readonly_client)
    with database.get_connection() as db: old={r['id']:r['payload'] for r in db.execute('SELECT * FROM bol_product_snapshots')}
    rid=str(uuid4());r=request(client,rid);assert r.status_code==200
    b=r.json();assert b['refresh']['outcome']=='saved' and b['market']['freshness']=='current'
    assert b['market']['offer_count']==1 and b['market']['unique_seller_count']==1
    assert b['market']['relevant_price']=='10.5000'
    count=len(calls);duplicate=request(client,rid).json();assert duplicate['refresh']['duplicate'] is True and len(calls)==count
    assert duplicate['refresh']['snapshot_id']==b['refresh']['snapshot_id']
    assert legacy_rows()==original and client.get('/api/products/1').json()==v1
    f=client.get('/api/products/1/financial-v2').json()
    assert f['financial_input_version']==1 and f['v2_financial']['price_selection']['selected_gross_price']=='10.5000'
    d=client.get('/api/products/1/decision-v2').json();assert d['market_freshness']['freshness']=='current'
    assert client.get('/api/comparison/products/1').json()['market']['freshness']=='current'
    with database.get_connection() as db:
        for sid,payload in old.items():assert db.execute('SELECT payload FROM bol_product_snapshots WHERE id=?',(sid,)).fetchone()[0]==payload
    before=path.read_bytes();status=client.get('/api/products/1/market-status');assert status.status_code==200 and len(status.json()['history'])==4
    assert path.read_bytes()==before


@pytest.mark.parametrize('code',[429,401,403,404,500])
def test_failed_refresh_persisted_latest_blocks_recent_old_price(readonly_client,code):
    client,path=readonly_client
    data=profile();finance_save(client,data,finance_preview(client,data).json()['preview_id'])
    assert client.get('/api/products/1/decision-v2').json()['analysis_v2']['opportunity_score'] is not None
    original=legacy_rows()
    def handler(r):return httpx.Response(code,json={'sensitive':'must not be returned'}) if 'catalog-products' in r.url.path else None
    _,calls=adapter(readonly_client,handler)
    rid=str(uuid4());b=request(client,rid).json()
    assert b['refresh']['outcome']=='failed' and b['market']['freshness']=='error'
    assert b['market']['price_min'] is None and len(b['history'])==4
    assert 'sensitive' not in json.dumps(b)
    markets=read_evidence(EAN)[2];assert markets[0]['payload']['status']=='unavailable' and markets[1]['payload']['status']=='complete'
    assert read_market(EAN,None)[0]['status']=='unavailable'
    comparison=client.get('/api/comparison/products/1').json()
    assert comparison['analysis_v2']['opportunity_score'] is None and comparison['primary_reason']['code']=='failed_market'
    count=len(calls);assert request(client,rid).json()['refresh']['duplicate'] and len(calls)==count
    assert legacy_rows()==original


def test_offer_pagination_failure_is_saved_not_low_competition(readonly_client):
    client,_=readonly_client
    def handler(r):
        if r.url.path.endswith('/offers'):
            return httpx.Response(200,json={'offers':[offer(i) for i in range(50)]}) if r.url.params['page']=='1' else httpx.Response(429,json={})
    adapter(readonly_client,handler);b=request(client).json()
    assert b['refresh']['error_code']==429 and b['market']['freshness']=='incomplete'
    assert b['market']['unique_seller_count'] is None
    assert client.get('/api/products/1/decision-v2').json()['analysis_v2']['opportunity_score'] is None


def test_concurrent_refreshes_and_interrupted_attempt(readonly_client):
    client,path=readonly_client;started=Event();release=Event()
    class Waiting:
        def preview(self,ean):
            started.set();assert release.wait(5);raise BolError(504,'safe timeout')
    first=str(uuid4())
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(refresh,EAN,first,Waiting());assert started.wait(5)
        assert client.get('/api/products/1/market-status').json()['market']['reason']=='refresh_in_progress'
        assert client.get('/api/products/1/decision-v2').json()['market_freshness']['freshness']=='error'
        with pytest.raises(BolError) as error:refresh(EAN,str(uuid4()),Waiting())
        assert error.value.status==409
        with pytest.raises(BolError):refresh(EAN,first,Waiting())
        release.set();assert pending.result()['error_code']==504
    when=(datetime.now(timezone.utc)-timedelta(seconds=LEASE_SECONDS+1)).isoformat()
    # Newer than all original fixtures, but deliberately expired lease.
    with database.get_connection() as db:
        # Put a complete measurement far enough back to demonstrate interrupted gating.
        db.execute('UPDATE bol_market_refresh_requests SET started_at=?,lease_until=?,state=? WHERE request_id=?',(when,when,'running',first))
        db.execute('DELETE FROM bol_market_snapshots WHERE snapshot_id=(SELECT snapshot_id FROM bol_market_refresh_requests WHERE request_id=?)',(first,))
        db.execute("UPDATE bol_market_snapshots SET measured_at=?",((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),))
    status=client.get('/api/products/1/market-status').json();assert status['market']['reason']=='refresh_interrupted'


def test_no_ean_invalid_ean_no_network_no_mutations(readonly_client):
    client,path=readonly_client;_,calls=adapter(readonly_client);before=path.read_bytes()
    assert not client.get('/api/products/2/market-status').json()['can_refresh']
    assert request(client,pid=2).status_code==400 and not calls and path.read_bytes()==before
    with database.get_connection() as db:db.execute('UPDATE products SET ean=? WHERE id=2',('4006381333932',))
    before=path.read_bytes()
    assert not client.get('/api/products/2/market-status').json()['can_refresh']
    assert request(client,pid=2).status_code==400 and not calls and path.read_bytes()==before
    assert request(client,pid=999).status_code==404
    assert client.post('/api/products/1/market-refresh',json={'request_id':'invalid'}).status_code==422
    assert path.read_bytes()==before


def test_atomic_refresh_save_rollback_gates_old_market(readonly_client):
    client,_=readonly_client;adapter(readonly_client)
    with database.get_connection() as db:
        old=db.execute('SELECT COUNT(*) FROM bol_product_snapshots').fetchone()[0]
        db.execute("CREATE TRIGGER fail_refresh BEFORE UPDATE ON bol_market_refresh_requests BEGIN SELECT RAISE(ABORT,'test'); END")
    r=request(client);assert r.status_code==503
    with database.get_connection() as db:assert db.execute('SELECT COUNT(*) FROM bol_product_snapshots').fetchone()[0]==old
    assert client.get('/api/products/1/market-status').json()['market']['reason']=='refresh_in_progress'
    assert read_market(EAN,None)[0]['status']=='unavailable'


def test_other_segment_does_not_replace_nl_new(readonly_client):
    client,_=readonly_client
    with database.get_connection() as db:db.execute("UPDATE bol_market_snapshots SET country='BE' WHERE snapshot_id=1")
    status=client.get('/api/products/1/market-status').json()['market'];assert status['snapshot_id']!=1
