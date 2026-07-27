"""Cloudflare R2 object storage (S3-compatible API via boto3)."""
from __future__ import annotations

import mimetypes
import re
import uuid
from functools import lru_cache
from typing import Optional

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app import config

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class R2NotConfiguredError(RuntimeError):
    pass


def r2_configured() -> bool:
    return bool(
        config.R2_ACCESS_KEY_ID
        and config.R2_SECRET_ACCESS_KEY
        and config.R2_ENDPOINT_URL
        and config.R2_BUCKET
    )


@lru_cache(maxsize=1)
def _client() -> BaseClient:
    if not r2_configured():
        raise R2NotConfiguredError(
            "R2 is not configured (need R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "R2_ENDPOINT_URL, R2_BUCKET)"
        )
    return boto3.client(
        "s3",
        endpoint_url=config.R2_ENDPOINT_URL.rstrip("/"),
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
        region_name=config.R2_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _safe_filename(name: Optional[str]) -> str:
    raw = (name or "photo.bin").strip().split("/")[-1]
    cleaned = _SAFE_NAME.sub("_", raw).strip("._") or "photo.bin"
    return cleaned[:180]


def build_object_key(*, object_id: Optional[str], filename: Optional[str]) -> str:
    folder = object_id.strip() if object_id and object_id.strip() else "orphan"
    return f"photos/{folder}/{uuid.uuid4().hex}_{_safe_filename(filename)}"


def public_url_for_key(key: str) -> str:
    base = (config.R2_PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}/{key}"
    # Fallback: path-style URL on the S3 API endpoint (works only if bucket is public).
    endpoint = config.R2_ENDPOINT_URL.rstrip("/")
    return f"{endpoint}/{config.R2_BUCKET}/{key}"


def upload_bytes(
    data: bytes,
    *,
    filename: Optional[str],
    content_type: Optional[str],
    object_id: Optional[str] = None,
) -> str:
    """Upload file bytes to R2 and return a public URL for photo.url."""
    if not data:
        raise ValueError("empty file")
    if len(data) > config.R2_MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large (max {config.R2_MAX_UPLOAD_BYTES} bytes)")

    ctype = content_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    if config.R2_ALLOWED_CONTENT_TYPES and ctype not in config.R2_ALLOWED_CONTENT_TYPES:
        raise ValueError(f"unsupported content type: {ctype}")

    key = build_object_key(object_id=object_id, filename=filename)
    client = _client()
    extra = {"ContentType": ctype}
    if config.R2_CACHE_CONTROL:
        extra["CacheControl"] = config.R2_CACHE_CONTROL

    client.put_object(
        Bucket=config.R2_BUCKET,
        Key=key,
        Body=data,
        **extra,
    )
    return public_url_for_key(key)


def reset_client_cache() -> None:
    """Test helper."""
    _client.cache_clear()
