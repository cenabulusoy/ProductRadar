from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json,sqlite3
import pytest,httpx
from fastapi.testclient import TestClient
from app.main import app
from app.core import database
from app.api.bol import get_bol_client
from app.services.bol import BolClient,BolSettings,BolError
from app.services import discovery as d,discovery_provider as p
from test_scoring_v2 import case,NOW,EAN


def record(source='bol_product_list',**kw):
    value={'ean':EAN,'title':'Fixture product','category':'123','kind':'official_measured',
           'source':source,'api_version':'v10','endpoint':'products/list','measured_at':NOW.isoformat(),
           'query':{'searchTerm':'fixture','countryCode':'NL','sort':'RELEVANCE','page':1},'list_position':1}
    value.update(kw);return value


@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'test.db');database.init_db()
    return database.DB_PATH


def contents(path,table):
    with sqlite3.connect(path) as db:return db.execute('select * from '+table).fetchall()


def enriched(age=0,**changes):
    market=deepcopy(case()['market_snapshots'][0]['payload'])
    when=(NOW-timedelta(hours=age)).isoformat();market['measured_at']=when;market.update(changes)
    return record('bol_ean_preview',measured_at=when,preview={'market':market,'catalog':{'title':'Catalog title','brand':'Fixture','classification_id':'GPC'},
                              'ratings':{'count':20,'average':4.5,'distribution':[{'rating':5,'count':20}]}})


def test_candidate_dedup_sources_idempotence_and_products_unchanged(db):
    before=contents(db,'products');one=d.save_records([record()]);assert d.save_records([record()])==one
    d.save_records([enriched()]);x=d.candidates(NOW)[0]
    assert x['sources']==['bol_ean_preview','bol_product_list'] and len(x['evidence'])==2
    assert x['opportunity_score'] is None and x['signals']['sales_volume']['value'] is None
    assert x['signals']['visibility']['provenance']['kind']=='derived'
    assert x['signals']['catalog']['provenance']['kind']=='official_measured'
    assert x['market']['counts_kind']=='derived' and contents(db,'products')==before
    assert contents(db,'bol_product_snapshots')==[] and contents(db,'financial_input_versions')==[]


def test_atomic_invalid_batch_and_migration(db):
    with pytest.raises(BolError):d.save_records([record(),record(ean='invalid')])
    assert d.candidates()==[]
    with sqlite3.connect(db) as conn:d.migrate_discovery(conn);d.migrate_discovery(conn)
    assert contents(db,'products')


@pytest.mark.parametrize('age,status',[(24,'current'),(24.001,'stale'),(72,'stale'),(72.001,'historical')])
def test_central_freshness(db,age,status):
    d.save_records([enriched(age)]);x=d.candidates(NOW)[0]
    assert x['market']['freshness']==status
    assert not d.filter_candidates([x],min_price=0) if age>24 else d.filter_candidates([x],min_price=0)


@pytest.mark.parametrize('status',['partial','unavailable'])
def test_bad_newest_does_not_fallback(db,status):
    d.save_records([enriched(2),enriched(1,status=status)]);x=d.candidates(NOW)[0]
    assert x['market']['relevant_price'] is None and not x['market']['usable_for_current_analysis']
    assert len(x['market_history'])==2 and x['market_history'][1]['usable_for_current_analysis']


def test_unknown_zero_filters_sort(db):
    d.save_records([record()]);x=d.candidates(NOW)[0]
    assert x['market']['unique_seller_count'] is None
    assert not d.filter_candidates([x],max_sellers=0)
    assert d.filter_candidates([x],source='bol_product_list',category='123')==[x]
    y=deepcopy(x);y['id']=2;y['market'].update(usable_for_current_analysis=True,unique_seller_count=0,relevant_price='10')
    assert d.filter_candidates([x,y],max_sellers=0)==[y]
    assert d.filter_candidates([x,y],sort='sellers')==[y,x]
    assert d.filter_candidates([x,y],min_price=11)==[]


def test_old_visibility_quality_decays_and_gpc_not_search_category(db):
    old=record(measured_at=(NOW-timedelta(days=4)).isoformat())
    d.save_records([old,enriched(96)])
    x=d.candidates(NOW)[0]
    assert x['evidence_quality']==35 and x['category']=='123' and x['catalog_classification_id']=='GPC'
    assert x['market']['usable_for_current_analysis'] is False


def setup(body,status=200):
    calls=[]
    def handler(req):
        calls.append(req)
        if req.url.host=='login.bol.com':return httpx.Response(200,json={'access_token':'fixture-token','expires_in':300})
        return httpx.Response(status,json=body)
    return BolClient(BolSettings('fixture-id','fixture-secret'),transport=httpx.MockTransport(handler)),calls


def test_list_normalized_scoped_alias_eans_and_token_reuse():
    client,calls=setup({'sort':'RELEVANCE','products':[{'title':'Fixture fixture-secret','eans':[{'ean':EAN},{'ean':'invalid'}]}]})
    result=p.product_list(client,'fixture');p.product_list(client,'fixture')
    assert len(calls)==3 and result['status']=='partial'
    assert result['records'][0]['title']=='Fixture [afgeschermd]' and result['records'][0]['list_position']==1
    body=json.loads(calls[1].content);assert body['page']==1 and body['sort']=='RELEVANCE'
    assert calls[1].headers['content-type']=='application/json'
    assert calls[1].headers['accept']=='application/vnd.retailer.v10+json'
    assert result['pagination_complete'] is False


@pytest.mark.parametrize('body',[{}, {'products':None},{'products':[{}]*51}])
def test_list_malformed(body):
    client,_=setup(body)
    with pytest.raises(BolError):p.product_list(client,'fixture')


@pytest.mark.parametrize('status',[403,429,500,415])
def test_provider_access_rate_errors(status):
    client,_=setup({},status)
    with pytest.raises(BolError) as exc:p.product_list(client,'fixture')
    assert exc.value.status==(429 if status==429 else 503 if status==403 else 502)


def test_white_spots_unverified_and_interface(monkeypatch):
    assert p.white_spots.capability()['status']=='unverified'
    with pytest.raises(BolError):p.white_spots.collect()
    class VerifiedFixture:
        def capability(self):return {'status':'fixture_only','beta':True}
        def collect(self):return []
    monkeypatch.setattr(p,'white_spots',VerifiedFixture())
    assert p.white_spots.capability()['status']=='fixture_only' and p.white_spots.collect()==[]


def test_api_collect_readonly_promotion_and_no_claims(db):
    client,_=setup({'sort':'RELEVANCE','products':[{'title':'Fixture','eans':[{'ean':EAN}]}]})
    app.dependency_overrides[get_bol_client]=lambda:client
    before=contents(db,'products')
    try:
        with TestClient(app) as api:
            assert api.post('/api/discovery/collect',json={}).status_code==422
            r=api.post('/api/discovery/collect',json={'search_term':'fixture'});assert r.status_code==200
            cid=r.json()['candidate_ids'][0]
            x=api.get('/api/discovery/candidates').json()['items'][0]
            assert x['opportunity_score'] is None and x['signals']['sales_volume']['value'] is None
            assert api.get('/api/discovery/candidates?max_sellers=0').json()['items']==[]
            assert api.get('/api/discovery/candidates?min_price=20&max_price=10').status_code==422
            result=api.get(f'/api/discovery/candidates/{cid}/promotion-preview').json()
            assert result['writes_products'] is False and result['can_promote'] is False
            assert api.get('/api/discovery/capabilities').json()['white_spots']['status']=='unverified'
    finally:app.dependency_overrides.clear()
    assert before==contents(db,'products')


def test_failed_measure_persists_failure_no_old_market(db):
    class Failed:
        def preview(self,ean):raise BolError(429,'Bol vraagt om te wachten.')
    cid=d.save_records([record(),enriched(1)])[0]
    app.dependency_overrides[get_bol_client]=lambda:Failed()
    try:
        with TestClient(app) as api:
            r=api.post(f'/api/discovery/candidates/{cid}/measure');assert r.status_code==200
            assert r.json()['market']['freshness']=='error' and r.json()['market']['relevant_price'] is None
            assert len(r.json()['market_history'])==2
    finally:app.dependency_overrides.clear()


def test_concurrent_collect_rejected_without_client_call(db):
    from app.api.discovery import collection_lock
    collection_lock.acquire()
    try:
        with TestClient(app) as api:
            assert api.post('/api/discovery/collect',json={'search_term':'fixture'}).status_code==409
    finally:collection_lock.release()


def test_successful_measure_stays_in_candidate_domain(db):
    cid=d.save_records([record()])[0];before=contents(db,'products')
    class Success:
        def preview(self,ean):return enriched()['preview']
    app.dependency_overrides[get_bol_client]=lambda:Success()
    try:
        with TestClient(app) as api:
            r=api.post(f'/api/discovery/candidates/{cid}/measure');assert r.status_code==200
            assert len(r.json()['evidence'])==2 and r.json()['signals']['rating_average']['value']==4.5
    finally:app.dependency_overrides.clear()
    assert contents(db,'products')==before and contents(db,'bol_market_snapshots')==[]


def test_concurrent_database_dedup(db):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool: ids=list(pool.map(lambda _:d.save_records([record()]),range(2)))
    assert ids[0]==ids[1] and len(d.candidates(NOW)[0]['evidence'])==1


def test_empty_list_does_not_invent_candidates():
    client,_=setup({'sort':'RELEVANCE','products':[]})
    assert p.product_list(client,'fixture')['records']==[]


def test_alternative_eans_keep_same_context_not_merge_identity():
    client,_=setup({'sort':'RELEVANCE','products':[{'title':'Fixture','eans':[{'ean':EAN},{'ean':'9781538744017'}]}]})
    result=p.product_list(client,'fixture')
    assert len(result['records'])==2 and all(x['list_position']==1 for x in result['records'])


def test_untrusted_sort_does_not_claim_relevance_rank():
    client,_=setup({'sort':'POPULARITY','products':[]})
    with pytest.raises(BolError):p.product_list(client,'fixture')
