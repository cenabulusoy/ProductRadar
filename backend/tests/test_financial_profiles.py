from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.core import database
from app.services import financial_profiles as service
from app.services.financial_profiles import Profile
from app.analysis.financial_v2 import FinancialInputs,calculate_financial
from app.main import app
from test_comparison import readonly_client
from test_scoring_v2 import financial


@pytest.fixture(autouse=True)
def receipt_store(monkeypatch):
    from app.services.snapshots import PreviewStore
    monkeypatch.setattr(service,'receipts',PreviewStore())


def profile(k=7):
    return {'schema_version':'1','financial':financial(k,datetime.now(timezone.utc)),'breakdown':{},'references':{}}


def preview(client,data=None,version=0,pid=1):
    return client.post(f'/api/products/{pid}/financial-inputs/preview',json={'profile':data if data is not None else profile(),'expected_version':version})


def save(client,data,receipt,version=0,pid=1,confirmed=True):
    return client.post(f'/api/products/{pid}/financial-inputs',json={'profile':data,'expected_version':version,'preview_id':receipt,'confirmed':confirmed})


def existing_data():
    with database.get_connection() as db:
        return {name:[tuple(row) for row in db.execute('SELECT * FROM '+name)] for name in ('products','bol_product_snapshots','bol_market_snapshots','bol_product_identities')}


def test_preview_readonly_save_atomic_versioned_and_legacy_unchanged(readonly_client):
    client,path=readonly_client
    original=existing_data()
    v1=client.get('/api/products/1').json()['analysis']
    before=path.read_bytes()
    data=profile()
    response=preview(client,data)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert path.read_bytes()==before
    result=response.json()['financial']
    assert result['base']['contribution_per_unit']=='6.0000'
    assert result['stress']['contribution_per_unit']=='3.8420'
    assert result==calculate_financial(FinancialInputs.model_validate(data['financial']),as_of=datetime.fromisoformat(result['as_of']),
           market_payload=result['price_selection']['market_reference'] and
           __import__('app.api.financial',fromlist=['read_market']).read_market(client.get('/api/products/1').json()['ean'],None)[0],snapshot_id=1)
    saved=save(client,data,response.json()['preview_id'])
    assert saved.status_code==200 and saved.json()['version']==1
    assert saved.json()['profile']==Profile.model_validate(data).model_dump(mode='json')
    assert existing_data()==original and client.get('/api/products/1').json()['analysis']==v1
    before=path.read_bytes()
    financial_result=client.get('/api/products/1/financial-v2').json()
    decision=client.get('/api/products/1/decision-v2').json()
    comparison=client.get('/api/comparison/products/1').json()
    assert financial_result['v2_financial']['base']['contribution_per_unit']=='6.0000'
    assert decision['analysis_v2']['opportunity_score'] is not None
    assert comparison['analysis_v2']['opportunity_score'] is not None
    assert comparison['financial_input_version']==1 and decision['financial_input_version']==1
    assert comparison['default_engine']=='v1' and path.read_bytes()==before


def test_changes_create_history_and_old_version_readable(readonly_client):
    client,_=readonly_client
    one=profile()
    saved1=save(client,one,preview(client,one).json()['preview_id']).json()
    two=profile(8)
    saved2=save(client,two,preview(client,two,1).json()['preview_id'],1).json()
    assert saved2['version']==2 and saved1['id']!=saved2['id']
    current=client.get('/api/products/1/financial-inputs').json()
    assert [r['version'] for r in current['history']]==[2,1]
    assert client.get('/api/products/1/financial-inputs?version=1').json()['saved']==saved1
    assert client.get('/api/products/1/financial-v2?version=1').json()['v2_financial']['base']['contribution_per_unit']=='6.0000'
    assert client.get('/api/products/1/financial-v2?version=2').json()['v2_financial']['base']['contribution_per_unit']=='5.0000'
    assert client.get('/api/products/1/decision-v2?version=1').json()['financial_profile_id']==saved1['id']
    assert client.get('/api/products/1/financial-inputs?version=99').status_code==404


def test_null_and_zero_preserved_with_import_provenance(readonly_client):
    client,_=readonly_client
    data=profile()
    data['financial']['advertising_cost']['amount']='0'
    data['financial']['other_allocated_cost']['amount']=None
    data['references']['financial.advertising_cost']={'import_reference':'invoice-fixture-1'}
    result=preview(client,data)
    assert result.status_code==200
    assert result.json()['financial']['base']['contribution_per_unit'] is None
    saved=save(client,data,result.json()['preview_id']).json()['profile']
    assert saved['financial']['advertising_cost']['amount']=='0'
    assert saved['financial']['other_allocated_cost']['amount'] is None
    assert saved['references']['financial.advertising_cost']['import_reference']=='invoice-fixture-1'


@pytest.mark.parametrize('field,value',[('landed_purchase_cost',-1),('planned_sale_price',0),('fulfilment_cost',True),('advertising_cost','NaN'),('other_allocated_cost','1.00001')])
def test_bad_economics_rejected_without_writes(readonly_client,field,value):
    client,path=readonly_client
    data=profile();data['financial'][field]['amount']=value
    before=path.read_bytes()
    assert preview(client,data).status_code==422
    assert path.read_bytes()==before


@pytest.mark.parametrize('change',[{'value':101},{'value':-1},{'value':True}])
def test_invalid_vat_rejected(readonly_client,change):
    client,_=readonly_client
    data=profile();data['financial']['sales_vat_rate'].update(change)
    assert preview(client,data).status_code==422


def test_future_and_missing_provenance_rejected(readonly_client):
    client,path=readonly_client
    data=profile();before=path.read_bytes()
    data['financial']['landed_purchase_cost']['provenance']['recorded_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert preview(client,data).status_code==422
    data=profile();del data['financial']['landed_purchase_cost']['provenance']
    assert preview(client,data).status_code==422
    assert path.read_bytes()==before


def test_changed_draft_confirmation_and_wrong_product_receipt_rejected(readonly_client):
    client,path=readonly_client
    data=profile();receipt=preview(client,data).json()['preview_id'];before=path.read_bytes()
    assert save(client,data,receipt,confirmed=False).status_code==422
    changed=deepcopy(data);changed['financial']['landed_purchase_cost']['amount']='8'
    assert save(client,changed,receipt).status_code==409
    assert save(client,data,receipt,pid=2).status_code==409
    assert save(client,data,'unknown-receipt-00000000000000').status_code==410
    assert path.read_bytes()==before


def test_idempotent_save_and_optimistic_concurrency(readonly_client):
    client,_=readonly_client
    data=profile()
    first=preview(client,data).json()['preview_id'];second=preview(client,data).json()['preview_id']
    saved=save(client,data,first)
    assert saved.status_code==200
    assert save(client,data,first).json()==saved.json()
    assert save(client,data,second).status_code==409
    assert preview(client,data,version=0).status_code==409
    assert len(client.get('/api/products/1/financial-inputs').json()['history'])==1


def test_atomic_rollback_when_insert_fails(readonly_client):
    client,_=readonly_client
    data=profile();receipt=preview(client,data).json()['preview_id']
    with database.get_connection() as db:
        db.execute("CREATE TRIGGER test_abort BEFORE INSERT ON financial_input_versions BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    original=existing_data()
    assert save(client,data,receipt).status_code==503
    assert client.get('/api/products/1/financial-inputs').json()['saved'] is None
    assert existing_data()==original
    with database.get_connection() as db: db.execute('DROP TRIGGER test_abort')
    assert save(client,data,receipt).status_code==200


def test_breakdown_requires_explicit_zero_and_consistent_confirmed_totals(readonly_client):
    client,_=readonly_client
    data=profile()
    data['breakdown']={'purchase_cost':deepcopy(data['financial']['landed_purchase_cost']),
                       'inbound_cost':deepcopy(data['financial']['advertising_cost'])}
    assert preview(client,data).status_code==200
    data['breakdown']['inbound_cost']['amount']='1'
    assert preview(client,data).status_code==422
    data['financial']['landed_purchase_cost']=None
    result=preview(client,data)
    assert result.status_code==200
    assert result.json()['proposals']['landed_purchase_cost']['amount']=='8'
    assert result.json()['proposals']['landed_purchase_cost']['kind']=='derived'
    assert result.json()['financial']['base']['contribution_per_unit'] is None
    data['financial']['landed_purchase_cost']=deepcopy(data['breakdown']['purchase_cost'])
    data['financial']['landed_purchase_cost']['amount']='8'
    assert preview(client,data).status_code==200


def test_logistic_breakdown_and_no_double_count(readonly_client):
    client,_=readonly_client
    data=profile()
    data['breakdown']={'shipping_cost':deepcopy(data['financial']['fulfilment_cost']),
                       'packaging_cost':deepcopy(data['financial']['advertising_cost']),
                       'handling_cost':deepcopy(data['financial']['advertising_cost'])}
    result=preview(client,data)
    assert result.status_code==200 and result.json()['financial']['base']['contribution_per_unit']=='6.0000'
    assert result.json()['proposals']['fulfilment_cost']['amount']=='3'


def test_official_kind_cannot_be_faked_but_verified_snapshot_price_supported(readonly_client):
    client,_=readonly_client
    data=profile()
    data['financial']['sales_vat_rate']['provenance']['kind']='official_measured'
    assert preview(client,data).status_code==422
    data=profile()
    from app.api.financial import read_market
    p=client.get('/api/products/1').json()
    market,sid=read_market(p['ean'],None)
    data['financial']['planned_sale_price']['provenance']={'kind':'official_measured','source':'bol relevant offer','recorded_at':market['measured_at'],'snapshot_id':sid}
    response=preview(client,data)
    assert response.status_code==200
    saved=save(client,data,response.json()['preview_id'])
    assert saved.status_code==200
    analyzed=client.get('/api/products/1/decision-v2')
    assert analyzed.status_code==200
    assert analyzed.json()['analysis_v2']['financial']['inputs']['planned_sale_price']['provenance']['kind']=='official_measured'
    data['financial']['planned_sale_price']['amount']='30'
    assert preview(client,data,version=1).status_code==422


def test_reference_validation_and_missing_product(readonly_client):
    client,_=readonly_client
    data=profile();data['references']={'unknown':{'import_reference':'fixture'}}
    assert preview(client,data).status_code==422
    data=profile();data['references']={'financial.planned_sale_price':{'snapshot_id':9999}}
    assert preview(client,data).status_code==404
    assert client.get('/api/products/999/financial-inputs').status_code==404


def test_old_database_readonly_backward_compatibility_and_repeatable_migration(readonly_client):
    client,path=readonly_client
    with database.get_connection() as db: db.execute('DROP TABLE financial_input_versions')
    before=path.read_bytes()
    assert client.get('/api/products/1/financial-inputs').json()['saved'] is None
    assert client.get('/api/comparison/products/1').status_code==200
    assert path.read_bytes()==before
    database.init_db();database.init_db()
    with database.get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM financial_input_versions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM products').fetchone()[0]==5


def test_stale_market_still_blocks_score_after_complete_financial_save(readonly_client):
    client,_=readonly_client
    with database.get_connection() as db:
        rows=db.execute('SELECT snapshot_id,payload FROM bol_market_snapshots').fetchall()
        for row in rows:
            p=json.loads(row['payload']);p['measured_at']=(datetime.now(timezone.utc)-timedelta(days=4)).isoformat()
            db.execute('UPDATE bol_market_snapshots SET measured_at=?,payload=? WHERE snapshot_id=?',(p['measured_at'],json.dumps(p),row['snapshot_id']))
    data=profile();result=preview(client,data)
    assert result.json()['financial']['base']['contribution_per_unit'] is None
    assert save(client,data,result.json()['preview_id']).status_code==200
    assert client.get('/api/products/1/decision-v2').json()['analysis_v2']['opportunity_score'] is None


def test_blank_profile_suggestions_never_automatically_confirm_legacy(readonly_client):
    client,_=readonly_client
    response=client.get('/api/products/1/financial-inputs').json()
    assert response['saved'] is None
    assert all(s['requires_confirmation'] and s['recorded_at'] is None for s in response['suggestions'])
    result=preview(client,{'financial':{}})
    assert result.status_code==200
    assert all(v is None for v in result.json()['financial']['base']['effective_costs'].values())
