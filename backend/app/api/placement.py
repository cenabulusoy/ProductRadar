"""Explicit placement collection; local GET never requests bol."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Response
from app.api.bol import get_bol_client
from app.services import placement
from app.services.bol import BolError

router = APIRouter(prefix='/discovery/placement', tags=['webshop placement'])


class PlacementInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ean: str = Field(pattern=r'^[0-9]{13}$')
    country: Literal['NL', 'BE'] = 'NL'
    language: Literal['nl', 'nl-BE', 'fr-BE'] = 'nl'
    request_id: UUID


@router.get('/{ean}')
def history(ean: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return {'items': placement.stored(ean)}
    except BolError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.post('')
def measure(body: PlacementInput, response: Response, client=Depends(get_bol_client)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return placement.measure(client, body.ean, body.country, body.language, str(body.request_id))
    except BolError as exc:
        raise HTTPException(exc.status, str(exc), headers={'Cache-Control': 'no-store'}) from None
