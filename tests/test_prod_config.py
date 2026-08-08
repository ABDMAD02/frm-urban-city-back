"""Fail-fast прод-конфигурации (находка C3).

config читает окружение на импорте, поэтому проверяем в подпроцессе с чистым env.
"""
from __future__ import annotations

import subprocess
import sys

_CHECK = (
    "import app.config as c; c.validate_production_settings(); print('OK')"
)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _CHECK],
        capture_output=True, text=True, env=env,
    )


_BASE = {
    "ENV": "production",
    "JWT_SECRET": "x" * 40,
    "CORS_ORIGINS": "https://example.kz",
    "PATH": "/usr/bin:/bin",
}


def test_prod_fails_without_superadmin_password(monkeypatch):
    import os
    env = {**_BASE, "PYTHONPATH": os.getcwd()}
    r = _run(env)
    assert r.returncode != 0, r.stdout
    assert "PLATFORM_SUPERADMIN_PASSWORD" in r.stderr


def test_prod_fails_with_demo_superadmin_password():
    import os
    env = {**_BASE, "PYTHONPATH": os.getcwd(), "PLATFORM_SUPERADMIN_PASSWORD": "Urb4n-SA-2026!"}
    r = _run(env)
    assert r.returncode != 0, r.stdout
    assert "PLATFORM_SUPERADMIN_PASSWORD" in r.stderr


def test_prod_ok_with_strong_superadmin_password():
    import os
    env = {**_BASE, "PYTHONPATH": os.getcwd(), "PLATFORM_SUPERADMIN_PASSWORD": "S0me-Str0ng-Secret-2026"}
    r = _run(env)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
