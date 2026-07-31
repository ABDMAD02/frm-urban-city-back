"""Нормализация загружаемых фото для веба: HEIC/HEIF → JPEG."""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

_HEIC_TYPES = {
    "image/heic",
    "image/heif",
    "image/heic-sequence",
    "image/heif-sequence",
}
_HEIC_BRANDS = {b"heic", b"heif", b"mif1", b"msf1", b"heix", b"hevc", b"heim", b"heis"}


def is_heic_like(
    data: bytes,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in _HEIC_TYPES:
        return True
    name = (filename or "").lower()
    if name.endswith((".heic", ".heif", ".heics", ".heifs")):
        return True
    # ISO Base Media File Format: size(4) + 'ftyp' + brand(4)
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return True
    return False


def _jpg_filename(filename: Optional[str]) -> str:
    raw = (filename or "photo.heic").rsplit("/", 1)[-1]
    base = raw.rsplit(".", 1)[0] if "." in raw else raw
    base = base.strip() or "photo"
    return f"{base}.jpg"


def normalize_image_for_web(
    data: bytes,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    jpeg_quality: int = 85,
) -> tuple[bytes, str, str]:
    """Если HEIC/HEIF — конвертирует в JPEG. Иначе возвращает как есть.

    Returns:
        (bytes, filename, content_type)
    """
    if not data:
        return data, filename or "photo.bin", content_type or "application/octet-stream"

    ctype = (content_type or "").split(";")[0].strip() or None
    name = filename or "photo.bin"

    if not is_heic_like(data, filename=name, content_type=ctype):
        guessed = ctype or "application/octet-stream"
        return data, name, guessed

    try:
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        with Image.open(BytesIO(data)) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif img.mode == "L":
                img = img.convert("RGB")
            out = BytesIO()
            img.save(out, format="JPEG", quality=max(40, min(95, int(jpeg_quality))), optimize=True)
            converted = out.getvalue()
    except Exception as exc:
        logger.exception("HEIC→JPEG conversion failed")
        raise ValueError(f"не удалось конвертировать HEIC/HEIF в JPEG: {exc}") from exc

    return converted, _jpg_filename(name), "image/jpeg"
