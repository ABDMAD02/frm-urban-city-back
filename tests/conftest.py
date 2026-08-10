"""Общие фикстуры тестов.

Тесты гоняются в in-memory режиме (`USE_DB=0`): `MemoryStore` пишет в модульные
списки `app.store` и в синглтоны `app.deps._memory` / `app.storage.platform_memory.STORE`.
Между тестами это состояние надо возвращать в исходное — иначе тесты зависят от
порядка (ровно та болячка, из-за которой `smoke_test.py` то зелёный, то красный).
"""
from __future__ import annotations

import copy
import os

import pytest

os.environ.setdefault("ENV", "development")
os.environ.setdefault("USE_DB", "0")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long!!")

from fastapi.testclient import TestClient  # noqa: E402

import app.store as store  # noqa: E402
from app.main import app  # noqa: E402
from app.user_helpers import temp_password  # noqa: E402

API = "/api/v1"

# Списки-хранилища in-memory демо-данных, которые мутируют операции.
_STORE_LISTS = (
    "DISTRICTS", "MICRODISTRICTS", "STREETS", "USERS", "OWNERS",
    "OBJECT_TYPES", "OBJECTS", "PHOTOS", "INSPECTIONS", "PRESCRIPTIONS",
    "HISTORY", "VERSIONS", "INSPECTION_TREND",
)


@pytest.fixture(autouse=True)
def _isolate_state():
    """Снимок демо-данных до теста, восстановление после + пересоздание синглтонов."""
    import app.deps as deps
    import app.storage.platform_memory as pm

    snapshot = {name: copy.deepcopy(getattr(store, name)) for name in _STORE_LISTS}
    counters = copy.deepcopy(store._counters)
    yield
    for name, value in snapshot.items():
        getattr(store, name)[:] = value
    store._counters.clear()
    store._counters.update(counters)
    # Синглтоны держат ссылки/хэши паролей — пересоздаём, чтобы тесты не текли друг в друга.
    deps._memory = deps.MemoryStore()
    pm.STORE = pm.MemoryPlatformStore()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post(f"{API}/auth/v2/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"логин {email} провалился: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def urbanist(client: TestClient) -> dict[str, str]:
    return _login(client, "a.nurlanova@uralsk.kz", "UC-0001-u1")


@pytest.fixture
def region_admin(client: TestClient) -> dict[str, str]:
    return _login(client, "a.kenzhebekov@uralsk.kz", "UC-0003-u3")


@pytest.fixture
def owner(client: TestClient) -> dict[str, str]:
    # d.saparov — владелец бизнеса, его объекты в сиде: o5, o12.
    return _login(client, "d.saparov", "UC-0002-u2")


@pytest.fixture
def superadmin(client: TestClient) -> dict[str, str]:
    return _login(client, "platform.admin@urban-city.kz", "Urb4n-SA-2026!")
