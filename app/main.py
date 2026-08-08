"""Urban City API — точка входа FastAPI.

Dev:       uvicorn app.main:app --reload
Production: gunicorn app.main:app -k uvicorn.workers.UvicornWorker (см. scripts/start.sh)
Swagger:   http://localhost:8000/docs     ·     ReDoc: http://localhost:8000/redoc

Роуты монтируются под /api/v1."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from . import config
from .deps import init_database
from .routers import (
    auth, objects, inspections, prescriptions, users, reference, analytics, misc, platform,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        config.validate_production_settings()
        init_database()
    except Exception:
        # Иначе gunicorn пишет только «Worker failed to boot» без traceback.
        # Структурный лог с трейсбеком вместо print — попадает в общий logging pipeline.
        logger.exception("Application startup failed during lifespan init")
        raise
    yield


# В production закрываем интерактивную документацию и схему: анонимная карта
# всех 66 ручек — лишняя поверхность для разведки. В dev остаётся открытой.
_docs_enabled = config.ENV != "production"

app = FastAPI(
    title="Urban City API",
    version="1.0.0",
    description="GovTech-платформа контроля дизайн-кода городской среды. Пилот — г. Уральск.",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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


_ROUTERS = [auth, objects, inspections, prescriptions, users, reference, analytics, misc, platform]

for module in _ROUTERS:
    app.include_router(module.router, prefix=config.API_PREFIX)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Все HTTPException → плоский {message, code} со стабильными code."""
    _CODES = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "too_many_requests",
        500: "internal_error",
        502: "bad_gateway",
        503: "service_unavailable",
    }
    if isinstance(exc.detail, dict) and "message" in exc.detail and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    if isinstance(exc.detail, dict) and "message" in exc.detail:
        content = {
            "message": str(exc.detail["message"]),
            "code": exc.detail.get("code") or _CODES.get(exc.status_code, f"http_{exc.status_code}"),
        }
        for key, value in exc.detail.items():
            if key not in content:
                content[key] = value
        return JSONResponse(status_code=exc.status_code, content=content)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": str(exc.detail),
            "code": _CODES.get(exc.status_code, f"http_{exc.status_code}"),
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        clean = {}
        for key, value in err.items():
            if key == "ctx" and isinstance(value, dict):
                clean[key] = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v) for k, v in value.items()}
            else:
                try:
                    json.dumps(value)
                    clean[key] = value
                except TypeError:
                    clean[key] = str(value)
        errors.append(clean)
    return JSONResponse(
        status_code=422,
        content={
            "message": "Ошибка валидации запроса",
            "code": "validation_error",
            "errors": errors,
        },
    )


@app.exception_handler(OperationalError)
async def database_operational_error_handler(request: Request, exc: OperationalError):
    logger.warning(
        "OperationalError on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=503,
        content={
            "message": "База данных временно недоступна (лимит соединений или сеть)",
            "code": "database_unavailable",
        },
    )


@app.exception_handler(IntegrityError)
async def database_integrity_error_handler(request: Request, exc: IntegrityError):
    """DB check/unique violations → 422 instead of opaque 500."""
    raw = str(getattr(exc, "orig", None) or exc)
    logger.warning(
        "IntegrityError on %s %s: %s",
        request.method,
        request.url.path,
        raw,
    )
    if "bin_format" in raw:
        message, code = "БИН/ИИН должен состоять из 12 цифр", "invalid_bin"
    elif "email_format" in raw:
        message, code = "Некорректный email", "invalid_email"
    elif "unique" in raw.lower() or "duplicate" in raw.lower():
        message, code = "Запись с такими данными уже существует", "duplicate"
    else:
        message, code = "Нарушение ограничения данных", "integrity_error"
    return JSONResponse(
        status_code=422,
        content={"message": message, "code": code},
    )


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
