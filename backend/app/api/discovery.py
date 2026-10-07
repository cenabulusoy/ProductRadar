"""Explicit bounded collection and enrichment, separate from ProductRadar products."""
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.api.bol import get_bol_client
from app.services.bol import BolError
from app.services import discovery as store
from app.services import discovery_provider as provider

router=APIRouter(prefix='/discovery',tags=['discovery'])
collection_lock=Lock()


class Search(BaseModel):
    model_config=ConfigDict(extra='forbid')
    search_term: str | None=Field(default=None,min_length=2,max_length=50,pattern=r'\S')
    category_id: str | None=Field(default=None,max_length=11,pattern=r'^[0-9]+$')
    @model_validator(mode='after')
    def scope(self):
        if not self.search_term and not self.category_id: raise ValueError('Search term or category required')
        return self


@router.get('/capabilities')
def capabilities(response:Response):
    response.headers['Cache-Control']='no-store'
    return {'product_list':{'status':'unverified','version':'v10','limit':'1 page, max 50 listings per explicit action'},
            'rankings':{'status':'not_integrated','reason':'Documented endpoint; account access not assumed.'},
            'catalog_ratings_offers':{'status':'existing_client','reason':'Per-EAN access can differ.'},
            'white_spots':provider.white_spots.capability()}


@router.get('/candidates')
def listing(response:Response,category:str|None=None,source:str|None=None,
            freshness:Literal['current','stale','historical','missing','incomplete','error']|None=None,
            max_sellers:int|None=Query(None,ge=0),min_price:float|None=Query(None,ge=0,le=1e9),
            max_price:float|None=Query(None,ge=0,le=1e9),min_quality:int=Query(0,ge=0,le=100),
            sort:Literal['discovered','quality','sellers']='discovered',offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
    response.headers['Cache-Control']='no-store'
    if min_price is not None and max_price is not None and min_price>max_price:
        raise HTTPException(422,'Ongeldige prijsrange.')
    items=store.filter_candidates(store.candidates(),category=category,source=source,freshness=freshness,
                                  max_sellers=max_sellers,min_price=min_price,max_price=max_price,min_quality=min_quality,sort=sort)
    return {'items':[ {k:v for k,v in x.items() if k not in ('evidence','market_history')} for x in items[offset:offset+limit]],
            'total':len(items),'offset':offset,'limit':limit,'default_engine':'v1'}


def get_candidate(cid):
    item=next((x for x in store.candidates() if x['id']==cid),None)
    if item is None: raise HTTPException(404,'Kandidaat niet gevonden.')
    return item


@router.get('/candidates/{cid}')
def detail(cid:int,response:Response):
    response.headers['Cache-Control']='no-store'
    return get_candidate(cid)


@router.post('/collect')
def collect(body:Search,response:Response,client=Depends(get_bol_client)):
    response.headers['Cache-Control']='no-store'
    if not collection_lock.acquire(False): raise HTTPException(409,'Er loopt al een discovery-aanvraag.')
    try:
        result=provider.product_list(client,body.search_term,body.category_id)
        ids=store.save_records(result['records'])
        return {k:v for k,v in result.items() if k!='records'} | {'candidate_ids':ids,'saved_candidates':len(ids)}
    except BolError as exc:
        raise HTTPException(exc.status,str(exc)) from None
    finally: collection_lock.release()


@router.post('/candidates/{cid}/measure')
def measure(cid:int,response:Response,client=Depends(get_bol_client)):
    response.headers['Cache-Control']='no-store'
    item=get_candidate(cid)
    if not collection_lock.acquire(False): raise HTTPException(409,'Er loopt al een discovery-aanvraag.')
    try:
        kind='official_measured'
        try:
            preview=client.preview(item['ean'])
            when=preview['market']['measured_at']
        except BolError as exc:
            kind='derived'
            when=datetime.now(timezone.utc).isoformat()
            preview={'market':{'measured_at':when,'source':'bol Retailer API','api_version':'v10',
                               'country':'NL','condition':'NEW','currency':'EUR','status':'unavailable',
                               'pagination_complete':False,'offers':[]},'error_code':exc.status}
        store.save_records([{'ean':item['ean'],'source':'bol_ean_preview','endpoint':'catalog/ratings/offers',
                             'api_version':'v10','kind':kind,'measured_at':when,'preview':preview}])
        return get_candidate(cid)
    finally: collection_lock.release()


@router.get('/candidates/{cid}/promotion-preview')
def promotion(cid:int,response:Response):
    response.headers['Cache-Control']='no-store'
    item=get_candidate(cid)
    with store.connection() as db:
        existing=[r[0] for r in db.execute('SELECT id FROM products WHERE ean=?',(item['ean'],))]
    return {'candidate_id':cid,'ean':item['ean'],'title_proposal':item['title'],
            'existing_product_ids':existing,'can_promote':False,'writes_products':False,
            'notice':'Alleen preview. Identiteit controleren en financiële gegevens expliciet bevestigen; geen markt- of schattingsvelden kopiëren.'}
