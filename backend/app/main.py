from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.products import router as products_router
from app.core.database import init_db

app = FastAPI(title="ProductRadar API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
 allow_origins=[
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
],
)
app.include_router(products_router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": "ProductRadar"}
