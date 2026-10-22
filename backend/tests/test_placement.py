from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import json,sqlite3
import httpx,pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.api.bol import get_bol_client
from app.core import database
from app.services import placement as p
from app.services.bol import BolClient,BolSettings,BolError

EAN='5407012560150'
BODY={'url':'https://www.bol.com/nl/nl/p/fixture/1/','categories':[
    {'categoryId':'1','categoryName':'Auto & Motor','subcategories':[
        {'id':'2','name':'Acculaders','subcategories':[{'id':'3','name':'Onderhoudsladers'}]},
        {'id':'4','name':'Accessoires'}]}]}


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'placement.db');database.init_db()


def client(body=BODY,status=200):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='login.bol.com':return httpx.Response(200,json={'access_token':'fixture-token','expires_in':300})
        return httpx.Response(status,json=body)
    return BolClient(BolSettings('fixture-id','fixture-secret'),httpx.MockTransport(handler)),calls


def test_official_contract_and_hierarchy(setup):
    c,calls=client();v=p.fetch(c,EAN)
    q=calls[-1];assert q.method=='GET' and q.url.path==f'/retailer/products/{EAN}/placement'
    assert dict(q.url.params)=={'country-code':'NL'} and q.headers['accept-language']=='nl'
    assert q.headers['accept']=='application/vnd.retailer.v10+json'
    assert v['query']=={'country_code':'NL','language':'nl'}
    assert v['provenance']['kind']=='official_measured' and v['provenance']['api_version']=='v10'
    root=v['official']['categories'][0];assert root['categoryId']=='1' and root['subcategories'][0]['id']=='2'
    assert len(root['subcategories'])==2 and root['subcategories'][1]['subcategories'] is None
    assert v['status']=='complete' and v['completeness']['kind']=='derived'


def test_multiple_roots_remain_distinct(setup):
    b=deepcopy(BODY);b['categories'].append({'categoryId':'5','categoryName':'Motoren','subcategories':[]})
    c,_=client(b);v=p.fetch(c,EAN);assert [x['categoryId'] for x in v['official']['categories']]==['1','5']


def test_empty_valid_response_not_fake_categories(setup):
    c,_=client({'url':'https://www.bol.com/nl/','categories':[]});v=p.fetch(c,EAN)
    assert v['official']['categories']==[] and v['status']=='complete'


@pytest.mark.parametrize('node',[{}, {'id':None}, {'id':'0','name':None},{'name':'Naam','subcategories':None}])
def test_missing_optional_values_remain_null_partial(setup,node):
    b=deepcopy(BODY);b['categories'][0]['subcategories']=[node];c,_=client(b);v=p.fetch(c,EAN)
    row=v['official']['categories'][0]['subcategories'][0]
    assert row['id']==node.get('id') and row['name']==node.get('name') and v['status']=='partial'


@pytest.mark.parametrize('body',[{}, {'categories':[]},{'url':'x'},{'url':None,'categories':[]},
    {'url':'x','categories':None},{'url':'x','categories':[{}]},
    {'url':'x','categories':[{'categoryId':None,'categoryName':'N'}]},
    {'url':'x','categories':[{'categoryId':'1','categoryName':2}]},
    {'url':'x','categories':[{'categoryId':'1','categoryName':'N','subcategories':{}}]},
    {'url':'x','categories':[{'categoryId':'1','categoryName':'N','subcategories':[{'id':3}]}]},
    {'url':'x','categories':[{'categoryId':'1','categoryName':'N','subcategories':[None]}]}])
def test_invalid_contract_rejected_not_zero(setup,body):
    c,_=client(body)
    with pytest.raises(BolError):p.fetch(c,EAN)


@pytest.mark.parametrize('ean',['5407012560151','123','','abcdefghijklm'])
def test_invalid_ean_before_oauth(setup,ean):
    c,calls=client()
    with pytest.raises(BolError):p.fetch(c,ean)
    assert not calls


@pytest.mark.parametrize('country,language',[('NL','nl'),('BE','nl-BE'),('BE','fr-BE')])
def test_country_language_contract(setup,country,language):
    c,calls=client();p.fetch(c,EAN,country,language)
    assert calls[-1].url.params['country-code']==country and calls[-1].headers['accept-language']==language


@pytest.mark.parametrize('status',[400,401,403,404,406,415,429,500])
def test_error_no_retry_no_secret_no_storage(setup,status):
    c,calls=client({'detail':'fixture-secret fixture-token'},status)
    with pytest.raises(BolError) as e:p.measure(c,EAN,'NL','nl',str(uuid4()))
    assert len(calls)==2 and p.stored(EAN)==[]
    assert 'fixture-secret' not in str(e.value) and 'fixture-token' not in str(e.value)
    if status==429:assert c._blocked_until>0


def test_history_idempotency_and_original_data(setup):
    db=sqlite3.connect(database.DB_PATH);names=[v[0] for v in db.execute("select name from sqlite_master where type='table' and name not in ('sqlite_sequence','discovery_placement_measurements')")]
    before={n:db.execute('select * from '+n).fetchall() for n in names}
    c,calls=client();rid=str(uuid4());first=p.measure(c,EAN,'NL','nl',rid)
    assert p.measure(c,EAN,'NL','nl',rid)==first and len(calls)==2
    with pytest.raises(HTTPException):p.measure(c,EAN,'BE','fr-BE',rid)
    second=p.measure(c,EAN,'NL','nl',str(uuid4()))
    assert first['id']!=second['id'] and len(p.stored(EAN))==2
    assert p.stored(EAN)[-1]==first
    assert before=={n:db.execute('select * from '+n).fetchall() for n in names}
    assert db.execute('pragma integrity_check').fetchone()[0]=='ok' and not db.execute('pragma foreign_key_check').fetchall();db.close()


def test_bad_or_partial_new_result_never_overwrites(setup):
    c,_=client();first=p.measure(c,EAN,'NL','nl',str(uuid4()))
    c,_=client({})
    with pytest.raises(BolError):p.measure(c,EAN,'NL','nl',str(uuid4()))
    assert p.stored(EAN)==[first]
    b=deepcopy(BODY);b['categories'][0]['subcategories']=[{}];c,_=client(b)
    partial=p.measure(c,EAN,'NL','nl',str(uuid4()))
    assert partial['status']=='partial' and p.stored(EAN)[-1]==first


def test_bounds_and_unknown_context(setup):
    for b in [{'url':'x','categories':[{'categoryId':'1','categoryName':'N'}]*501}]:
        c,_=client(b)
        with pytest.raises(BolError):p.fetch(c,EAN)
    b=deepcopy(BODY);current=b['categories'][0]
    for n in range(22):current['subcategories']=[{'id':str(n),'name':'N'}];current=current['subcategories'][0]
    c,_=client(b)
    with pytest.raises(BolError):p.fetch(c,EAN)
    for country,lang in [('DE','nl'),('NL','en')]:
        c,calls=client()
        with pytest.raises(BolError):p.fetch(c,EAN,country,lang)
        assert not calls


def test_concurrency_one_chain(setup,monkeypatch):
    start,release=Event(),Event();c,calls=client();original=p.fetch
    def blocked(*args):start.set();assert release.wait(5);return original(*args)
    monkeypatch.setattr(p,'fetch',blocked)
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(p.measure,c,EAN,'NL','nl',str(uuid4()));assert start.wait(5)
        with pytest.raises(HTTPException):p.measure(c,EAN,'NL','nl',str(uuid4()))
        release.set();pending.result()
    assert len(calls)==2


def test_api_reads_only_and_validates_input(setup):
    c,calls=client();app.dependency_overrides[get_bol_client]=lambda:c
    try:
        with TestClient(app) as api:
            assert api.get('/api/discovery/placement/'+EAN).json()['items']==[] and not calls
            result=api.post('/api/discovery/placement',json={'ean':EAN,'request_id':str(uuid4())});assert result.status_code==200
            assert result.headers['cache-control']=='no-store'
            assert api.get('/api/discovery/placement/'+EAN).json()['items']==[result.json()] and len(calls)==2
            assert api.post('/api/discovery/placement',json={'ean':EAN,'request_id':str(uuid4()),'categories':[]}).status_code==422
    finally:app.dependency_overrides.clear()


def test_secret_redaction(setup):
    b=deepcopy(BODY);b['categories'][0]['categoryName']='fixture-secret';c,_=client(b)
    assert 'fixture-secret' not in json.dumps(p.fetch(c,EAN))


def test_atomic_migration_rollback(setup,monkeypatch):
    db=sqlite3.connect(database.DB_PATH);db.execute('drop table discovery_placement_measurements');db.commit()
    original=p.migrate_placement
    def failure(connection):original(connection);raise sqlite3.OperationalError('fixture failure')
    monkeypatch.setattr(p,'migrate_placement',failure)
    with pytest.raises(sqlite3.OperationalError):database.init_db()
    assert not db.execute("select 1 from sqlite_master where name='discovery_placement_measurements'").fetchone();db.close()


def test_blank_unknown_values_become_null(setup):
    c,_=client({'url':'  ','categories':[{'categoryId':'','categoryName':' ','subcategories':[{'id':'','name':' '}]}]})
    value=p.fetch(c,EAN);root=value['official']['categories'][0]
    assert value['official']['url'] is None and root['categoryId'] is None and root['categoryName'] is None
    assert root['subcategories'][0]['id'] is None and root['subcategories'][0]['name'] is None
    assert value['status']=='partial'
