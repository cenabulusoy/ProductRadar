"""Explicit visibility fetch; GET only reads local measurements."""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from app.api.bol import get_bol_client
from app.services import rankings
from app.services.bol import BolError

router = APIRouter(prefix='/discovery/rankings', tags=['visibility'])


class RankingInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ean: str = Field(pattern=r'^[0-9]{13}$')
    report_date: str
    context_type: Literal['SEARCH', 'BROWSE'] | None = None
    request_id: UUID


@router.get('/{ean}')
def history(ean: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return {'items': rankings.stored(ean), 'latest_allowed_date': (rankings.today() - rankings.timedelta(days=1)).isoformat()}
    except BolError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.post('')
def measure(body: RankingInput, response: Response, client=Depends(get_bol_client)):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return rankings.measure(client, body.ean, body.report_date, body.context_type, str(body.request_id))
    except BolError as exc:
        raise HTTPException(exc.status, str(exc), headers={'Cache-Control': 'no-store'}) from None
