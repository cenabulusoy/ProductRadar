"""Product-scoped market status and explicit refresh; no manual product writes."""
from datetime import datetime, timezone
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, HTTPException, Response
from app.api.bol import get_bol_client
from app.api.comparison import read_products
from app.api.decision import read_evidence
from app.services.bol import BolError, validate_ean
from app.services.freshness import classify
from app.services.market_refresh import refresh, error_message

router = APIRouter(prefix='/products',tags=['market refresh'])


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


def product(pid):
    rows,_ = read_products(product_id=pid)
    if not rows:
        raise HTTPException(404,'Product niet gevonden.')
    return rows[0]


def status(p):
    ean=p.get('ean') or ''
    try:
        validate_ean(ean)
        can_refresh=True
    except BolError:
        can_refresh=False
    _,_,records=read_evidence(ean)
    now=datetime.now(timezone.utc)
    data=classify(records,now)
    # Saved data only; older rows are context, never fallback for current selection.
    history=[classify([r],now) for r in records if r['id']][:50]
    return {'product_id':p['id'],'ean':ean,'can_refresh':can_refresh,'default_engine':'v1',
            'market':data,'history':history,'identity_notice':None if can_refresh else 'Een geldige EAN/productidentiteit is eerst nodig.'}


@router.get('/{product_id}/market-status')
def market_status(product_id:int,response:Response):
    response.headers['Cache-Control']='no-store'
    return status(product(product_id))


@router.post('/{product_id}/market-refresh')
def market_refresh(product_id:int,body:RefreshRequest,response:Response,client=Depends(get_bol_client)):
    response.headers['Cache-Control']='no-store'
    p=product(product_id)
    try:
        result=refresh(p.get('ean') or '',str(body.request_id),client)
    except BolError as exc:
        raise HTTPException(exc.status,str(exc),headers={'Cache-Control':'no-store'}) from None
    # Persisted failed/partial attempts are returned as an explicit result, not a
    # fake success. Transport/configuration codes remain visible without secrets.
    return {**status(p), 'refresh':{**result,'outcome':'failed' if result['error_code'] else 'saved',
                                  'message':error_message(result['error_code']) if result['error_code'] else 'Nieuwe marktmeting opgeslagen.'}}
