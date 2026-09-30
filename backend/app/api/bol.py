from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field
from app.services.snapshots import previews, save_snapshot, history
from app.services.bol import validate_ean

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
        preview = client.preview(ean)
        return {**preview, "preview_id": previews.issue(preview)}
    except BolError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc),
                            headers={"Cache-Control": "no-store"}) from None


class SavePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/snapshots")
def save_preview(body: SavePreview, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return save_snapshot(body.preview_id)
    except BolError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc),
                            headers={"Cache-Control": "no-store"}) from None


@router.get("/products/{ean}/snapshots")
def product_snapshots(ean: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        validate_ean(ean)
        return history(ean)
    except BolError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc),
                            headers={"Cache-Control": "no-store"}) from None
