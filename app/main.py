"""Urban City API — точка входа FastAPI.

Dev:       uvicorn app.main:app --reload
Production: gunicorn app.main:app -k uvicorn.workers.UvicornWorker (см. scripts/start.sh)
Swagger:   http://localhost:8000/docs     ·     ReDoc: http://localhost:8000/redoc

Роуты монтируются под /api/v1 (рекомендуемый префикс, на нём мобилка)
и дублируются под /api (совместимость с текущим веб-клиентом)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from . import config
from .deps import init_database
from .routers import (
    auth, objects, inspections, prescriptions, users, reference, analytics, misc,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_production_settings()
    init_database()
    yield


app = FastAPI(
    title="Urban City API",
    version="1.0.0",
    description="GovTech-платформа контроля дизайн-кода городской среды. Пилот — г. Уральск.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if config.ENV == "production":
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


_ROUTERS = [auth, objects, inspections, prescriptions, users, reference, analytics, misc]

for prefix in (config.API_PREFIX, config.LEGACY_PREFIX):
    for module in _ROUTERS:
        app.include_router(module.router, prefix=prefix)


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "Urban City API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "api_base": config.API_PREFIX,
    }


def _check_database() -> str | None:
    """None — БД не настроена или доступна; иначе текст ошибки."""
    if not os.getenv("DATABASE_URL"):
        return None
    try:
        from db.base import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:
        return str(exc)


@app.get("/health", include_in_schema=False)
def health():
    payload: dict[str, str] = {"status": "ok", "env": config.ENV}
    db_error = _check_database()
    if db_error:
        payload["status"] = "degraded"
        payload["database"] = db_error
        return JSONResponse(payload, status_code=503)
    if os.getenv("DATABASE_URL"):
        payload["database"] = "ok"
    return payload
