"""Хеширование и проверка паролей (PBKDF2-SHA256, stdlib)."""
from __future__ import annotations

import hashlib
import hmac
import secrets

_SCHEME = "pbkdf2_sha256"
_ITERATIONS = 260_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Вернуть строку вида ``pbkdf2_sha256$iters$salt_hex$hash_hex``."""
    if not password:
        raise ValueError("password must be non-empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_SCHEME}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, password_hash: str | None) -> bool:
    """Сравнить пароль с сохранённым хешем. Пустой/битый хеш → False."""
    if not password or not password_hash:
        return False
    try:
        scheme, iters_s, salt_hex, hash_hex = password_hash.split("$", 3)
        if scheme != _SCHEME:
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)
