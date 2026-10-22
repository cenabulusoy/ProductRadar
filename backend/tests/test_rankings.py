from copy import deepcopy
from datetime import date, datetime, timezone
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import json, sqlite3
import httpx, pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.core import database
from app.services import rankings as r
from app.services.bol import BolClient, BolSettings, BolError
from app.api.bol import get_bol_client
from app.main import app

EAN='5407012560150'
DAY='2026-10-21'
BODY={'ranks':[{'rank':1,'impressions':0,'wasSponsored':False,'searchTerm':'auto onderhoud'},
               {'rank':12,'impressions':25,'wasSponsored':True,'categoryId':'43646'}], 'hasNextPage':False}


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'rankings.db');database.init_db()
    monkeypatch.setattr(r,'today',lambda:date(2026,10,22))


def client(body=BODY,status=200):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='login.bol.com':return httpx.Response(200,json={'access_token':'fixture-token','expires_in':300})
        return httpx.Response(status,json=body)
    return BolClient(BolSettings('fixture-id','fixture-secret'),httpx.MockTransport(handler)),calls


def test_contract_and_provenance(setup):
    c,calls=client();v=r.fetch(c,EAN,DAY)
    q=calls[-1]
    assert q.method=='GET' and q.url.path=='/retailer/insights/product-ranks'
    assert dict(q.url.params)=={'ean':EAN,'date':DAY,'page':'1'}
    assert q.headers['accept']=='application/vnd.retailer.v10+json' and q.headers['accept-language']=='nl-NL'
    assert v['country'] is None and v['provenance']['kind']=='official_measured'
    assert v['records'][0]['official']['impressions']==0
    assert v['records'][0]['official']['wasSponsored'] is False
    assert v['records'][0]['official']['categoryId'] is None
    assert [x['derived']['context_type'] for x in v['records']]==['SEARCH','BROWSE']
    assert datetime.fromisoformat(v['retrieved_at']).utcoffset() is not None


@pytest.mark.parametrize('body',[{'ranks':[],'hasNextPage':False},{'ranks':[],'hasNextPage':True},
    {'ranks':[{'rank':0,'impressions':0,'wasSponsored':False}],'hasNextPage':False}])
def test_empty_optional_zero_pagination(setup,body):
    c,calls=client(body);v=r.fetch(c,EAN,DAY)
    assert len(calls)==2 and v['has_next_page']==body['hasNextPage']
    assert v['status']==('partial' if body['hasNextPage'] else 'complete')
    if v['records']:assert v['records'][0]['derived']['context_type'] is None


@pytest.mark.parametrize('field,value',[('rank',None),('rank',True),('rank',-1),('rank',1.2),('rank',2147483648),
    ('impressions',None),('impressions',False),('impressions',-1),('wasSponsored',None),('wasSponsored',0),('searchTerm',3),('categoryId',[])])
def test_invalid_required_or_context_never_zero(setup,field,value):
    b=deepcopy(BODY);b['ranks'][0][field]=value;c,_=client(b)
    with pytest.raises(BolError):r.fetch(c,EAN,DAY)


@pytest.mark.parametrize('body',[{}, {'ranks':[]}, {'ranks':{},'hasNextPage':False},
    {'ranks':[None],'hasNextPage':False},{'ranks':[],'hasNextPage':0}, {'ranks':[BODY['ranks'][0]]*51,'hasNextPage':True}])
def test_invalid_envelope(setup,body):
    c,_=client(body)
    with pytest.raises(BolError):r.fetch(c,EAN,DAY)


@pytest.mark.parametrize('day,valid',[('2026-10-21',True),('2026-07-22',True),('2026-07-21',False),
    ('2026-10-22',False),('2026-10-23',False),('20261021',False),('invalid',False)])
def test_date_limits(setup,day,valid):
    c,calls=client()
    if valid:r.fetch(c,EAN,day)
    else:
        with pytest.raises(BolError):r.fetch(c,EAN,day)
        assert not calls


def test_month_end_and_amsterdam_midnight(setup):
    r.validate_query(EAN,'2026-02-28',as_of=date(2026,5,31))
    with pytest.raises(BolError):r.validate_query(EAN,'2026-02-27',as_of=date(2026,5,31))
    from zoneinfo import ZoneInfo
    assert datetime(2026,10,21,22,30,tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Amsterdam')).date()==date(2026,10,22)


@pytest.mark.parametrize('status',[400,401,403,404,406,415,429,500])
def test_errors_one_ranking_attempt_safe(setup,status):
    c,calls=client({'detail':'fixture-secret fixture-token'},status)
    with pytest.raises(BolError) as e:r.fetch(c,EAN,DAY)
    assert len(calls)==2 and 'fixture-secret' not in str(e.value) and 'fixture-token' not in str(e.value)
    if status==429:assert c._blocked_until>0


def test_page_boundaries_and_type(setup):
    for page in [0,2,200,201,True]:
        with pytest.raises(BolError):r.validate_query(EAN,DAY,page=page)
    for context in ['SEARCH','BROWSE']:
        c,calls=client();r.fetch(c,EAN,DAY,context);assert calls[-1].url.params['type']==context
    with pytest.raises(BolError):r.validate_query(EAN,DAY,'OTHER')


def test_storage_idempotency_immutable_data(setup):
    db=sqlite3.connect(database.DB_PATH)
    before=db.execute('select * from products').fetchall();db.close()
    c,calls=client();rid=str(uuid4());v=r.measure(c,EAN,DAY,None,rid)
    assert r.measure(c,EAN,DAY,None,rid)==v and len(calls)==2
    assert len(r.stored(EAN))==1
    with pytest.raises(HTTPException):r.measure(c,EAN,DAY,'SEARCH',rid)
    db=sqlite3.connect(database.DB_PATH)
    assert before==db.execute('select * from products').fetchall()
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert not db.execute('pragma foreign_key_check').fetchall();db.close()


def test_concurrent_one_request(setup,monkeypatch):
    start,release=Event(),Event();c,calls=client();fetch=r.fetch
    def blocked(*a,**k):start.set();assert release.wait(5);return fetch(*a,**k)
    monkeypatch.setattr(r,'fetch',blocked)
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(r.measure,c,EAN,DAY,None,str(uuid4()));assert start.wait(5)
        with pytest.raises(HTTPException) as e:r.measure(c,EAN,DAY,None,str(uuid4()))
        assert e.value.status_code==409;release.set();pending.result()
    assert len(calls)==2


def test_api_get_read_only_post_explicit(setup):
    c,calls=client();app.dependency_overrides[get_bol_client]=lambda:c
    try:
        with TestClient(app) as api:
            assert api.get('/api/discovery/rankings/'+EAN).json()['items']==[] and not calls
            response=api.post('/api/discovery/rankings',json={'ean':EAN,'report_date':DAY,'request_id':str(uuid4())})
            assert response.status_code==200 and response.headers['cache-control']=='no-store'
            assert len(api.get('/api/discovery/rankings/'+EAN).json()['items'])==1 and len(calls)==2
            assert api.post('/api/discovery/rankings',json={'ean':EAN,'report_date':DAY,'request_id':str(uuid4()),'page':2}).status_code==422
    finally:app.dependency_overrides.clear()


def test_secret_redaction_and_ambiguous_context(setup):
    b=deepcopy(BODY);b['ranks'][0]['searchTerm']='fixture-secret';b['ranks'][0]['categoryId']='12'
    c,_=client(b);v=r.fetch(c,EAN,DAY)
    assert 'fixture-secret' not in json.dumps(v) and v['records'][0]['derived']['context_type'] is None


def test_identical_payload_keeps_first_retrieval_and_single_row(setup):
    c,calls=client();first=r.measure(c,EAN,DAY,None,str(uuid4()))
    second=r.measure(c,EAN,DAY,None,str(uuid4()))
    assert first==second and len(r.stored(EAN))==1


def test_migration_failure_rolls_back_new_table(setup,monkeypatch):
    db=sqlite3.connect(database.DB_PATH)
    db.execute('DROP TABLE discovery_ranking_measurements');db.commit()
    original=r.migrate_rankings
    def fail(connection):
        original(connection)
        raise sqlite3.OperationalError('fixture migration failure')
    monkeypatch.setattr(r,'migrate_rankings',fail)
    with pytest.raises(sqlite3.OperationalError):database.init_db()
    assert not db.execute("select 1 from sqlite_master where name='discovery_ranking_measurements'").fetchone()
    assert db.execute('select count(*) from products').fetchone()[0]>0
    db.close()


def test_malformed_json_and_timeout_never_persist(setup):
    def handler(request):
        if request.url.host=='login.bol.com':return httpx.Response(200,json={'access_token':'fixture-token','expires_in':300})
        return httpx.Response(200,text='not json')
    c=BolClient(BolSettings('fixture-id','fixture-secret'),httpx.MockTransport(handler))
    with pytest.raises(BolError):r.measure(c,EAN,DAY,None,str(uuid4()))
    assert r.stored(EAN)==[]
    def timeout(request):raise httpx.ReadTimeout('private transport details',request=request)
    c.transport=httpx.MockTransport(timeout)
    with pytest.raises(BolError) as e:r.fetch(c,EAN,DAY)
    assert e.value.status==504 and 'private' not in str(e.value)


def test_known_sources_and_original_tables_unchanged(setup):
    db=sqlite3.connect(database.DB_PATH)
    names=[v[0] for v in db.execute("select name from sqlite_master where type='table' and name not in ('sqlite_sequence','discovery_ranking_measurements')")]
    before={n:db.execute('select * from '+n).fetchall() for n in names}
    c,_=client();r.measure(c,EAN,DAY,None,str(uuid4()))
    assert before=={n:db.execute('select * from '+n).fetchall() for n in names}
    db.close()
