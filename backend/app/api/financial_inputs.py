"""Explicit financial editor API; immutable revisions and read-only calculations."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, Query
from pydantic import Field

from app.analysis.financial_v2 import Model, calculate_financial
from app.api.comparison import read_products
from app.api.financial import read_market
from app.api.decision import read_evidence
from app.analysis.scoring_v2 import calculate_decision
from app.services.financial_profiles import Profile, read_profile, history, preview_profile, save_profile, validate_evidence, scoring_inputs
from app.services.bol import BolError

router=APIRouter(prefix='/products',tags=['financial inputs v2'])


class Draft(Model):
    profile: Profile
    expected_version: int = Field(ge=0,strict=True)


class Save(Draft):
    preview_id: str = Field(min_length=20,max_length=100)
    confirmed: bool = Field(strict=True)


def product(product_id):
    rows,_=read_products(product_id=product_id)
    if not rows:
        raise HTTPException(404,'Product niet gevonden.')
    return rows[0]


def safe_action(action):
    try:
        return action()
    except BolError as exc:
        raise HTTPException(exc.status,str(exc)) from None
    except (ValueError,TypeError,KeyError,ArithmeticError):
        raise HTTPException(422,'Controleer bedragen, btw, brongegevens, datums en kostentotalen.') from None


@router.get('/{product_id}/financial-inputs')
def get_inputs(product_id:int,response:Response,version:int|None=Query(None,gt=0)):
    response.headers['Cache-Control']='no-store'
    p=product(product_id)
    saved=read_profile(product_id,version)
    if version is not None and saved is None:
        raise HTTPException(404,'Financiële versie niet gevonden.')
    return {'saved':saved,'history':history(product_id),'default_engine':'v1',
            'suggestions':[{'field':field,'value':p.get(old),'kind':'manual_or_imported','source':'Bestaande ProductRadar-invoer',
                            'recorded_at':None,'requires_confirmation':True}
                           for field,old in [('planned_sale_price','sale_price'),('purchase_cost','purchase_price'),('shipping_cost','shipping_cost')]]}


@router.post('/{product_id}/financial-inputs/preview')
def preview(product_id:int,body:Draft,response:Response):
    response.headers['Cache-Control']='no-store'
    p=product(product_id)
    return safe_action(lambda:preview_profile(p,body.profile,body.expected_version,datetime.now(timezone.utc)))


@router.post('/{product_id}/financial-inputs')
def save(product_id:int,body:Save,response:Response):
    response.headers['Cache-Control']='no-store'
    if not body.confirmed:
        raise HTTPException(422,'Bevestig de financiële invoer expliciet vóór opslaan.')
    p=product(product_id)
    return safe_action(lambda:save_profile(p,body.profile,body.expected_version,body.preview_id,datetime.now(timezone.utc)))


@router.get('/{product_id}/financial-v2')
def stored_financial(product_id:int,response:Response,version:int|None=Query(None,gt=0)):
    response.headers['Cache-Control']='no-store'
    p=product(product_id)
    saved=read_profile(product_id,version)
    if version is not None and saved is None:
        raise HTTPException(404,'Financiële versie niet gevonden.')
    profile=Profile.model_validate(saved['profile']) if saved else Profile(financial={})
    now=datetime.now(timezone.utc)
    payload,sid=read_market(p.get('ean') or '',None) if p.get('ean') else (None,None)
    output=safe_action(lambda:calculate_financial(profile.financial,as_of=now,market_payload=payload,snapshot_id=sid))
    return {'financial_input_version':saved['version'] if saved else None,'financial_profile_id':saved['id'] if saved else None,'v2_financial':output}


@router.get('/{product_id}/decision-v2')
def stored_decision(product_id:int,response:Response,version:int|None=Query(None,gt=0)):
    response.headers['Cache-Control']='no-store'
    p=product(product_id)
    saved=read_profile(product_id,version)
    if version is not None and saved is None:
        raise HTTPException(404,'Financiële versie niet gevonden.')
    profile=Profile.model_validate(saved['profile']) if saved else Profile(financial={})
    identity,products,markets=read_evidence(p.get('ean') or '')
    now=datetime.now(timezone.utc)
    def calculation():
        validate_evidence(profile,p,now)
        return calculate_decision(scoring_inputs(profile),as_of=now,ean=p.get('ean') or '',identity=identity,product_snapshots=products,market_snapshots=markets)
    output=safe_action(calculation)
    return {'financial_input_version':saved['version'] if saved else None,'financial_profile_id':saved['id'] if saved else None,'analysis_v2':output}
