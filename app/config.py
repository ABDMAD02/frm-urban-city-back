"""Настройки приложения. Значения берутся из окружения (.env), с дефолтами для dev."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Единый префикс API.
API_PREFIX = "/api/v1"

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
PRESCRIPTION_DEADLINE_DAYS = int(os.getenv("PRESCRIPTION_DEADLINE_DAYS", "30"))
REINSPECTION_DELAY_DAYS = int(os.getenv("REINSPECTION_DELAY_DAYS", "30"))

# Cloudflare R2 (S3-compatible). Bucket: frm-urban-city
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET = os.getenv("R2_BUCKET", "frm-urban-city").strip()
R2_REGION = os.getenv("R2_REGION", "auto").strip() or "auto"
# Public base for stored photo.url, e.g. https://pub-xxxx.r2.dev or custom domain.
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "").strip()
# Optional Cloudflare API token (not required for S3 put_object).
R2_API_TOKEN = os.getenv("R2_API_TOKEN", "").strip()
R2_MAX_UPLOAD_BYTES = int(os.getenv("R2_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
R2_CACHE_CONTROL = os.getenv("R2_CACHE_CONTROL", "public, max-age=31536000, immutable").strip()
# TTL for SigV4 GET URLs issued by GET /photos (not stored in DB).
R2_PRESIGN_TTL_SECONDS = int(os.getenv("R2_PRESIGN_TTL_SECONDS", "3600"))
_R2_ALLOWED = os.getenv(
    "R2_ALLOWED_CONTENT_TYPES",
    "image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif",
)
R2_ALLOWED_CONTENT_TYPES = {t.strip() for t in _R2_ALLOWED.split(",") if t.strip()}

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


def today_date() -> date:
    """Runtime date: real clock in production, frozen demo date elsewhere."""
    if ENV == "production":
        return datetime.now(UTC).date()
    return date.fromisoformat(DEMO_TODAY)


def today_str() -> str:
    return today_date().isoformat()


def plus_days_str(days: int) -> str:
    return (today_date() + timedelta(days=days)).isoformat()


def now_iso() -> str:
    if ENV == "production":
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return DEMO_TODAY + "T09:00:00Z"


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
    # Пароль платформенного суперадмина не должен оставаться демо-значением,
    # захардкоженным в открытом репозитории.
    superadmin_pw = os.getenv("PLATFORM_SUPERADMIN_PASSWORD", "")
    if not superadmin_pw or superadmin_pw == "Urb4n-SA-2026!":
        raise RuntimeError(
            "PLATFORM_SUPERADMIN_PASSWORD must be set to a non-demo value in production"
        )
    # Photo uploads require R2 in production (optional only if explicitly disabled).
    require_r2 = os.getenv("R2_REQUIRED", "0").lower() in ("1", "true", "yes")
    if require_r2:
        missing = [
            name
            for name, val in (
                ("R2_ENDPOINT_URL", R2_ENDPOINT_URL),
                ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
                ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
                ("R2_BUCKET", R2_BUCKET),
                ("R2_PUBLIC_BASE_URL", R2_PUBLIC_BASE_URL),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Cloudflare R2 is required in production; missing: " + ", ".join(missing)
            )