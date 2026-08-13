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

catalog = c.get("/api/v1/platform/geo-catalog/cities", headers=H)
check("GET /platform/geo-catalog/cities", catalog.status_code == 200 and len(catalog.json()) >= 1)

# catalog provision → active + geo
prov = c.post(
    "/api/v1/platform/regions",
    headers=H,
    json={
        "code": "aktau-test",
        "name": "Актау (тест)",
        "adminName": "Данияр Тестов",
        "geo": {"source": "catalog", "cityCatalogId": "kz-aktau"},
    },
)
check("POST /platform/regions catalog → active", prov.status_code == 201 and prov.json()["region"]["status"] == "active")
if prov.status_code == 201:
    rid = prov.json()["region"]["id"]
    geo = c.get(f"/api/v1/platform/regions/{rid}/districts", headers=H)
    check("GET platform districts seeded", geo.status_code == 200 and len(geo.json()) >= 1)

# manual provision → provisioning
prov2 = c.post(
    "/api/v1/platform/regions",
    headers=H,
    json={
        "code": "manual-test",
        "name": "Manual City",
        "adminName": "Admin Manual",
        "geo": {
            "source": "manual",
            "config": {
                "hasDistricts": True,
                "hasMicrodistricts": True,
                "hasStreets": True,
                "addressSchema": "microdistrict,street,house",
            },
        },
    },
)
check("POST /platform/regions manual → provisioning", prov2.status_code == 201 and prov2.json()["region"]["status"] == "provisioning")
if prov2.status_code == 201:
    rid2 = prov2.json()["region"]["id"]
    act_fail = c.post(f"/api/v1/platform/regions/{rid2}/activate", headers=H)
    check("POST activate without geo → 422", act_fail.status_code == 422 and act_fail.json().get("code") == "geo_incomplete")
    imp = c.post(
        f"/api/v1/platform/regions/{rid2}/geo/import",
        headers=H,
        json={
            "districts": [{"name": "Центр"}],
            "microdistricts": [{"name": "мкр. 1", "districtName": "Центр"}],
            "streets": [{"name": "ул. Абая", "districtName": "Центр"}],
        },
    )
    check("POST geo/import", imp.status_code == 200 and imp.json()["added"]["districts"] == 1)
    act_ok = c.post(f"/api/v1/platform/regions/{rid2}/activate", headers=H)
    check("POST activate after geo → active", act_ok.status_code == 200 and act_ok.json()["status"] == "active")

check("GET /platform/plans → 404", c.get("/api/v1/platform/plans", headers=H).status_code == 404)

admins = c.get("/api/v1/platform/admin-users", headers=H)
check("GET /platform/admin-users", admins.status_code == 200 and len(admins.json()) >= 1)

audit = c.get("/api/v1/platform/audit", headers=H)
check("GET /platform/audit", audit.status_code == 200 and len(audit.json()) >= 1)

logout = c.post("/api/v1/auth/v2/logout", headers=H)
check("POST /auth/v2/logout", logout.status_code == 204)

print(f"\nИТОГ: {ok} успешно, {len(fail)} провалено")
if fail:
    print("FAIL:", fail)
    raise SystemExit(1)
print("PLATFORM GREEN ✓")
