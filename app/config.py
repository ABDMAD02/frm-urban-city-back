"""Настройки приложения. Значения берутся из окружения (.env), с дефолтами для dev."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Единый префикс API. Рекомендуется /api/v1 (на нём уже мобилка).
API_PREFIX = "/api/v1"
# Дополнительно монтируем /api для совместимости с текущим веб-клиентом
# (NEXT_PUBLIC_API_BASE_URL по умолчанию = /api).
LEGACY_PREFIX = "/api"

ENV = os.getenv("ENV", "development").lower()
PORT = int(os.getenv("PORT", "8000"))
WEB_CONCURRENCY = int(os.getenv("WEB_CONCURRENCY", "2"))

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-prod")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
ACCESS_TTL_MIN = int(os.getenv("ACCESS_TTL_MIN", "30"))
REFRESH_TTL_DAYS = int(os.getenv("REFRESH_TTL_DAYS", "14"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",")
    if o.strip()
]

# В демо даты заморожены — как в прототипе фронта.
DEMO_TODAY = os.getenv("DEMO_TODAY", "2026-07-02")

# PostgreSQL: USE_DB=1 или auto (DATABASE_URL задан в production).
_USE_DB = os.getenv("USE_DB", "auto").lower()


def use_database() -> bool:
    if _USE_DB in ("1", "true", "yes"):
        return True
    if _USE_DB in ("0", "false", "no"):
        return False
    # auto
    return bool(os.getenv("DATABASE_URL")) and ENV == "production"

_INSECURE_SECRETS = {"", "change-me-in-prod", "changeme", "secret"}


def validate_production_settings() -> None:
    """Fail-fast при небезопасной конфигурации в production."""
    if ENV != "production":
        return
    if JWT_SECRET in _INSECURE_SECRETS or len(JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET must be a random string of at least 32 characters in production"
        )
    if not CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must be set in production")
