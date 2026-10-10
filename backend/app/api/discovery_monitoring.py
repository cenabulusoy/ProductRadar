"""Monitoring inputs; official evidence can only arrive through the server client."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,model_validator
from fastapi import APIRouter,Depends,Response
from app.api.bol import get_bol_client
from app.services import discovery_monitoring as service

router=APIRouter(prefix='/discovery/monitoring',tags=['discovery monitoring'])


class ContextInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=100,pattern=r'\S')
    search_term:str|None=Field(None,min_length=2,max_length=50,pattern=r'\S')
    category_id:str|None=Field(None,max_length=11,pattern=r'^[0-9]+$')
    country:Literal['NL']='NL'
    sort:Literal['RELEVANCE']='RELEVANCE'
    page:Literal[1]=1
    @model_validator(mode='after')
    def scope(self):
        if not self.search_term and not self.category_id:raise ValueError('Search context required')
        return self
    def parameters(self):
        return {'countryCode':self.country,'sort':self.sort,'page':self.page,'language':'nl',
                'searchTerm':self.search_term,'categoryId':self.category_id,'filterRanges':[],'filterValues':[]}


class WatchInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidate_id:int=Field(gt=0,strict=True)
    followed:bool=Field(default=True,strict=True)


class RunInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID


@router.get('/contexts')
def contexts(response:Response):
    response.headers['Cache-Control']='no-store'
    return {'items':service.contexts(),'scheduler':False,'max_watched_per_context':5}


@router.post('/contexts')
def save_context(body:ContextInput,response:Response):
    response.headers['Cache-Control']='no-store'
    return {'id':service.save_context(body.name,body.parameters())}


@router.post('/contexts/{cid}/watchlist')
def watch(cid:int,body:WatchInput,response:Response):
    response.headers['Cache-Control']='no-store'
    service.watch(cid,body.candidate_id,body.followed)
    return {'followed':body.followed}


@router.post('/contexts/{cid}/runs')
def run(cid:int,body:RunInput,response:Response,client=Depends(get_bol_client)):
    response.headers['Cache-Control']='no-store'
    return service.run(cid,str(body.request_id),client)


@router.get('/contexts/{cid}/candidates/{candidate_id}/history')
def history(cid:int,candidate_id:int,response:Response):
    response.headers['Cache-Control']='no-store'
    return service.history(cid,candidate_id)
