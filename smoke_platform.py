"""Smoke: платформенный control-plane API (memory mode)."""
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
ok = 0
fail = []


def check(name, cond):
    global ok
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail.append(name)
        print(f"  ✗ {name}")


# no token → 401 on platform
r = c.get("/api/v1/platform/regions")
check("GET /platform/regions without token → 401", r.status_code == 401)

# login superadmin
login = c.post("/api/v1/auth/v2/login", json={"email": "platform.admin@urban-city.kz", "password": "Urb4n-SA-2026!"})
check("POST /auth/v2/login superadmin", login.status_code == 200 and "access_token" in login.json())
tok = login.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

bad = c.post("/api/v1/auth/v2/login", json={"email": "platform.admin@urban-city.kz", "password": "wrong"})
check("POST /auth/v2/login bad password → 401", bad.status_code == 401)

me = c.get("/api/v1/auth/v2/me", headers=H)
check("GET /auth/v2/me", me.status_code == 200 and me.json().get("role") == "platform_superadmin")

regions = c.get("/api/v1/platform/regions", headers=H)
check("GET /platform/regions", regions.status_code == 200 and len(regions.json()) >= 1)

# Подписки/тарифы удалены — ручек /plans и /subscriptions больше нет.
check("GET /platform/plans → 404", c.get("/api/v1/platform/plans", headers=H).status_code == 404)
check("GET /platform/subscriptions → 404", c.get("/api/v1/platform/subscriptions", headers=H).status_code == 404)

admins = c.get("/api/v1/platform/admin-users", headers=H)
check("GET /platform/admin-users", admins.status_code == 200 and len(admins.json()) >= 1)

ras = c.get("/api/v1/platform/region-admin-accounts", headers=H)
check("GET /platform/region-admin-accounts", ras.status_code == 200 and len(ras.json()) >= 1)

prov = c.post(
    "/api/v1/platform/regions",
    headers=H,
    json={
        "code": "astana",
        "name": "Астана",
        "timezone": "Asia/Almaty",
        "locale": "ru",
        "mapProvider": "2gis",
        "adminName": "Ерлан Тестов",
    },
)
check("POST /platform/regions provision", prov.status_code == 201 and "credentials" in prov.json())
check("  провижн НЕ возвращает subscription", "subscription" not in prov.json())
if prov.status_code == 201:
    check("  credentials login", bool(prov.json()["credentials"]["login"]))
    rid = prov.json()["region"]["id"]
    st = c.patch(f"/api/v1/platform/regions/{rid}/status", headers=H, json={"status": "active"})
    check("PATCH status → active", st.status_code == 200 and st.json()["status"] == "active")
    re = c.post(
        f"/api/v1/platform/regions/{rid}/admin-account",
        headers=H,
        json={"name": "Новый Админ"},
    )
    check("POST reissue admin", re.status_code == 201 and "credentials" in re.json())

audit = c.get("/api/v1/platform/audit", headers=H)
check("GET /platform/audit", audit.status_code == 200 and len(audit.json()) >= 1)

logout = c.post("/api/v1/auth/v2/logout", headers=H)
check("POST /auth/v2/logout", logout.status_code == 204)

print(f"\nИТОГ: {ok} успешно, {len(fail)} провалено")
if fail:
    print("FAIL:", fail)
    raise SystemExit(1)
print("PLATFORM GREEN ✓")
