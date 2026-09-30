from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Response

from app.services.bol import BolClient, BolError, BolSettings

router = APIRouter(prefix="/bol", tags=["bol preview"])


@lru_cache(maxsize=1)
def get_bol_client():
    return BolClient(BolSettings.from_environment())


@router.get("/ean-preview/{ean}")
def ean_preview(ean: str, response: Response, client: BolClient = Depends(get_bol_client)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return client.preview(ean)
    except BolError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc),
                            headers={"Cache-Control": "no-store"}) from None
