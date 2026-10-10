from copy import deepcopy
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import sqlite3,json
from threading import Event
from concurrent.futures import ThreadPoolExecutor
import pytest,httpx
from fastapi.testclient import TestClient
from app.main import app
from app.core import database
from app.api.bol import get_bol_client
from app.api.discovery_monitoring import ContextInput
from app.services import discovery as d,discovery_monitoring as m,discovery_provider as provider
from app.services.discovery_history import compare,evidence_summary,rating
from app.services.bol import BolClient,BolSettings,BolError
from test_scoring_v2 import case,NOW,EAN
from test_discovery import record

PARAMS=ContextInput(name='Auto onderhoud',search_term='auto onderhoud').parameters()


def point(days=0,count=10,position=4,**kw):
    when=NOW+timedelta(days=days)
    market=deepcopy(case()['market_snapshots'][0]['payload']);market['measured_at']=when.isoformat()
    for offer in market['offers']:offer['minDeliveryDate']=(when+timedelta(days=1)).date().isoformat();offer['maxDeliveryDate']=(when+timedelta(days=2)).date().isoformat()
    preview={'ean':EAN,'fetched_at':when.isoformat(),'status':'complete','api_version':'v10','source':'bol Retailer API v10','language':'nl',
             'endpoints':{'ratings':{'status':'ok','version':'v10','path':'products/{ean}/ratings'}},
             'catalog':{'title':'Fixture'},'ratings':{'count':count,'distribution':[{'rating':n,'count':count if n==5 else 0} for n in range(1,6)]},'market':market}
    result={'id':days+1,'candidate_id':1,'ean':EAN,'parameters':deepcopy(PARAMS),'measured_at':when.isoformat(),
            'payload':{'status':'complete','list_status':'observed','list_completeness':'complete','position':position,'preview':preview}}
    result.update(kw);return result


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'monitor.db');database.init_db()
    monkeypatch.setattr(m,'now',lambda:NOW)
    candidate=d.save_records([record()])[0];cid=m.save_context('Auto onderhoud',PARAMS);m.watch(cid,candidate)
    return cid,candidate


def rows(table):
    db=sqlite3.connect(database.DB_PATH)
    try:return db.execute('select * from '+table).fetchall()
    finally:db.close()


def mock_listing(client,*args):
    return {'status':'complete','records':[record()]}


class FixtureClient:
    def __init__(self,preview=None):self.value=preview or point()['payload']['preview'];self.calls=0
    def preview(self,ean):self.calls+=1;return deepcopy(self.value)


def test_append_only_idempotent_repeated_points(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',mock_listing);client=FixtureClient()
    before=rows('products');rid=str(uuid4());r=m.run(cid,rid,client)
    first=rows('discovery_monitoring_measurements')
    assert m.run(cid,rid,client)==r and client.calls==1
    # Same exact observed payload/time is not another historical measurement.
    m.run(cid,str(uuid4()),client);assert rows('discovery_monitoring_measurements')==first
    assert rows('products')==before and rows('financial_input_versions')==[]
    assert rows('bol_market_snapshots')==[] and len(rows('discovery_observations'))==1


def test_context_same_parameters_dedup_and_different_distinct(setup):
    cid,_=setup;assert m.save_context('Andere naam',PARAMS)==cid
    q={**PARAMS,'searchTerm':'andere zoekterm'};assert m.save_context('Andere context',q)!=cid
    with pytest.raises(Exception):ContextInput(name='Test',search_term='fixture',country='BE')


@pytest.mark.parametrize('days,usable',[(0,False),(1,False),(13.999,False),(14,True),(21,True),(60,True),(60.001,False)])
def test_rating_growth_interval(days,usable):
    a,b=point(),point(days,count=18);r=compare(a,b)
    assert (r['rating_growth_per_day'] is not None)==usable
    if days>0:assert r['rating_count_delta']==8
    if usable:assert r['rating_growth_per_30_days']==pytest.approx(8/days*30)


def test_different_context_or_identity_never_compared():
    a,b=point(),point(21);b['parameters']['page']=2
    assert compare(a,b)['rating_count_delta'] is None
    b=point(21);b['ean']='9781538744017';assert compare(a,b)['relevant_price_delta'] is None


def test_market_deltas_and_best_fulfilment_delivery_changes():
    a,b=point(),point(21,count=18,position=2)
    market=b['payload']['preview']['market'];market['offers'].append({**market['offers'][0],'offerId':'new','retailerId':'new_seller','bestOffer':False})
    offer=market['offers'][0];offer.update(price=30,offerId='changed',fulfilmentMethod='FBR',minDeliveryDate='2026-10-25',maxDeliveryDate='2026-10-26')
    a['payload']['preview']['market']['offers'][0]['fulfilmentMethod']='FBB'
    r=compare(a,b)
    assert r['offer_count_delta']==1 and r['seller_count_delta']==1
    assert r['relevant_price_delta'] is not None and r['list_position_delta']==-2
    assert r['best_offer_changed'] is True and r['fulfilment_changed'] is True and r['delivery_changed'] is True


def test_unchanged_is_zero_or_false_unknown_is_none():
    a,b=point(count=0),point(21,count=0)
    r=compare(a,b);assert r['rating_count_delta']==0 and r['rating_growth_per_day']==0
    assert r['seller_count_delta']==0 and r['best_offer_changed'] is False and r['delivery_changed'] is False
    b['payload']['preview']['ratings']=None
    assert compare(a,b)['rating_count_delta'] is None


def test_decreasing_ratings_not_negative_sales():
    r=compare(point(),point(21,count=3));assert r['rating_count_delta']==-7 and r['rating_growth_per_day'] is None
    assert r['metric_reasons']['rating_growth']=='rating_count_decreased'


def test_missing_product_and_partial_market_do_not_fake_trends():
    a,b=point(),point(21);b['payload']['list_status']='not_observed';b['payload']['position']=None
    b['payload']['preview']['market']['status']='partial'
    r=compare(a,b);assert r['list_position_delta'] is None and r['seller_count_delta'] is None
    assert r['rating_count_delta']==0


def test_missing_distribution_bucket_is_unknown():
    p=point();p['payload']['preview']['ratings']['distribution'].pop();assert rating(p) is None


def test_complete_zero_offers_is_known_zero_not_missing():
    a,b=point(),point(21)
    b['payload']['preview']['market']['offers']=[]
    r=compare(a,b)
    assert r['offer_count_delta']==-len(a['payload']['preview']['market']['offers'])
    assert r['seller_count_delta'] is not None and r['relevant_price_delta'] is None


def test_future_point_or_wrong_context_rolls_back(setup):
    cid,candidate=setup;rid=str(uuid4());m.reserve(cid,rid)
    p=point(1);p['candidate_id']=candidate
    with pytest.raises(Exception) as error:m.finish(cid,rid,[p],{'status':'complete'})
    assert error.value.status_code==422 and rows('discovery_monitoring_measurements')==[]


def test_summary_eligible_anchor_and_failure_gap():
    points=[point(),point(20,count=17),point(21,count=18)];s=evidence_summary(points)
    assert s['rating_history']=='bruikbaar' and s['rating_growth']['rating_count_delta']==8
    assert s['actual_sales_evidence'] is None and s['estimated_monthly_sales'] is None and s['demand_score'] is None
    points[1]['payload']['preview']['ratings']=None;assert evidence_summary(points)['rating_history']=='onvoldoende'


def test_failed_run_keeps_old_history_and_provenance(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',mock_listing)
    m.run(cid,str(uuid4()),FixtureClient());old=rows('discovery_monitoring_measurements')
    monkeypatch.setattr(m,'now',lambda:NOW+timedelta(days=1))
    def failed(*args):raise BolError(429,'Even wachten.')
    monkeypatch.setattr(provider,'product_list',failed);client=FixtureClient()
    r=m.run(cid,str(uuid4()),client);assert r['status']=='failed' and client.calls==0
    history=m.history(cid,candidate);assert len(history['points'])==2 and rows('discovery_monitoring_measurements')[0]==old[0]
    assert history['demand_evidence']['comparison']['relevant_price_delta'] is None
    assert history['points'][-1]['payload']['provenance']['list']['kind']=='derived'


def test_candidate_not_observed_still_has_separate_market_measurement(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',lambda *args:{'status':'complete','records':[]})
    m.run(cid,str(uuid4()),FixtureClient());p=m.history(cid,candidate)['points'][0]
    assert p['payload']['list_status']=='not_observed' and p['payload']['position'] is None
    assert p['payload']['preview']['market']['status']=='complete'


def test_concurrent_runs_one_chain(setup,monkeypatch):
    cid,_=setup;start=Event();release=Event();client=FixtureClient()
    def listing(*args):start.set();release.wait(5);return mock_listing(*args)
    monkeypatch.setattr(provider,'product_list',listing)
    with ThreadPoolExecutor(2) as pool:
        future=pool.submit(m.run,cid,str(uuid4()),client);assert start.wait(3)
        with pytest.raises(Exception) as error:m.run(cid,str(uuid4()),client)
        assert error.value.status_code==409;release.set();future.result()
    assert client.calls==1


def test_expired_lease_recovery_and_late_finish_rejected(setup,monkeypatch):
    cid,candidate=setup;rid=str(uuid4());m.reserve(cid,rid)
    assert m.history(cid,candidate)['points'][0]['payload']['status']=='running'
    monkeypatch.setattr(m,'now',lambda:NOW+timedelta(minutes=75,seconds=1))
    assert m.contexts()[0]['last_run']['lease_expired'] is True
    with pytest.raises(Exception) as error:m.finish(cid,rid,[],{'status':'complete'})
    assert error.value.status_code==409
    monkeypatch.setattr(provider,'product_list',mock_listing);m.run(cid,str(uuid4()),FixtureClient())
    assert rows('discovery_monitoring_runs')[0][5]=='interrupted'


def test_uuid_context_conflict_and_watch_limit(setup):
    cid,candidate=setup;rid=str(uuid4());m.reserve(cid,rid)
    other=m.save_context('Andere',{**PARAMS,'searchTerm':'andere'})
    with pytest.raises(Exception) as error:m.reserve(other,rid)
    assert error.value.status_code==409
    for i in range(4):
        # Additional valid fixture EANs; checkdigit generated for fixture-only identifiers.
        stem='12345678901'+str(i);check=(10-sum(int(n)*(1 if j%2==0 else 3) for j,n in enumerate(stem))%10)%10
        new=d.save_records([record(ean=stem+str(check))])[0];m.watch(cid,new)
    stem='223456789012';check=(10-sum(int(n)*(1 if j%2==0 else 3) for j,n in enumerate(stem))%10)%10
    new=d.save_records([record(ean=stem+str(check))])[0]
    with pytest.raises(Exception) as error:m.watch(cid,new)
    assert error.value.status_code==422


def test_bounded_proxy_reuses_client_and_blocks_extra_pages():
    calls=[]
    class Client:
        def _get(self,path,params=None):calls.append((path,params));return {}
    proxy=m.BoundedEnrichment(Client())
    proxy._get('products/fixture/offers',{'page':5})
    with pytest.raises(BolError):proxy._get('products/fixture/offers',{'page':6})
    assert len(calls)==1
    proxy.gets=35
    with pytest.raises(BolError):proxy._get('products/fixture/ratings')


def test_api_watch_history_no_live_on_gets(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',mock_listing);client=FixtureClient()
    app.dependency_overrides[get_bol_client]=lambda:client
    try:
        with TestClient(app) as api:
            assert api.get('/api/discovery/monitoring/contexts').status_code==200 and client.calls==0
            r=api.post(f'/api/discovery/monitoring/contexts/{cid}/runs',json={'request_id':str(uuid4())});assert r.status_code==200
            h=api.get(f'/api/discovery/monitoring/contexts/{cid}/candidates/{candidate}/history')
            assert h.status_code==200 and h.json()['demand_evidence']['actual_sales_evidence'] is None
            assert api.post('/api/discovery/monitoring/contexts',json={'name':'x','search_term':'fixture','page':2}).status_code==422
    finally:app.dependency_overrides.clear()


@pytest.mark.parametrize('field,value',[('api_version','v11'),('language','be'),('ean','9781538744017')])
def test_ratings_incompatible_endpoint_or_identity_unknown(field,value):
    a,b=point(),point(21);b['payload']['preview'][field]=value
    assert compare(a,b)['rating_count_delta'] is None


def test_conflicting_bol_id_blocks_all_deltas():
    a,b=point(),point(21);a['payload']['preview']['bol_product_id']='one';b['payload']['preview']['bol_product_id']='two'
    assert compare(a,b)['seller_count_delta'] is None and compare(a,b)['reason']=='conflicting_product_identity'


def test_partial_list_position_not_compared():
    a,b=point(),point(21);b['payload']['list_completeness']='partial'
    assert compare(a,b)['list_position_delta'] is None


def test_partial_enrichment_keeps_valid_market_not_fake_ratings(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',mock_listing)
    preview=point()['payload']['preview'];preview['status']='partial';preview['ratings']=None
    r=m.run(cid,str(uuid4()),FixtureClient(preview));assert r['status']=='partial'
    h=m.history(cid,candidate)['demand_evidence'];assert h['rating_measurements']==0 and h['market_measurements']==1


def test_lease_reservation_guards_other_context_without_process_lock(setup):
    cid,candidate=setup;m.reserve(cid,str(uuid4()))
    other=m.save_context('Other',{**PARAMS,'searchTerm':'another'});m.watch(other,candidate)
    with pytest.raises(Exception) as error:m.reserve(other,str(uuid4()))
    assert error.value.status_code==409


def test_no_watchlist_no_upstream_and_no_run(setup):
    cid,candidate=setup;m.watch(cid,candidate,False)
    with pytest.raises(Exception) as error:m.reserve(cid,str(uuid4()))
    assert error.value.status_code==422 and rows('discovery_monitoring_runs')==[]


def test_new_measurement_preserves_old_payload(setup,monkeypatch):
    cid,candidate=setup;monkeypatch.setattr(provider,'product_list',mock_listing)
    m.run(cid,str(uuid4()),FixtureClient());old=rows('discovery_monitoring_measurements')[0]
    monkeypatch.setattr(m,'now',lambda:NOW+timedelta(days=21))
    m.run(cid,str(uuid4()),FixtureClient(point(21,count=18)['payload']['preview']))
    assert rows('discovery_monitoring_measurements')[0]==old
    h=m.history(cid,candidate);assert len(h['points'])==2 and h['demand_evidence']['rating_growth']['rating_count_delta']==8


def test_same_list_timestamp_no_fake_position_change():
    a,b=point(),point(21,position=1)
    a['payload']['list_measured_at']=NOW.isoformat();b['payload']['list_measured_at']=NOW.isoformat()
    assert compare(a,b)['list_position_delta'] is None


def test_proxy_executes_existing_bol_preview_parser_and_token_reuse():
    from test_bol import setup_client
    api,client,calls=setup_client()
    try:
        proxy=m.BoundedEnrichment(client)
        preview=proxy.preview(EAN);proxy.preview(EAN)
        assert preview['catalog']['title']=='Testproduct' and preview['ratings']['count']==4
        assert sum(c.url.host=='login.bol.com' for c in calls)==1 and proxy.gets==6
    finally:api.close()
