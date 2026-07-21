"""Дымовой тест: поднимает приложение через TestClient и дёргает ключевые эндпоинты."""
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
B = "/api/v1"
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


# схема openapi
schema = c.get("/openapi.json").json()
paths = schema["paths"]
print(f"OpenAPI сгенерирован: {len(paths)} путей")

# health
health = c.get("/health").json()
check("GET /health", health.get("status") == "ok")

# чтения
objs = c.get(f"{B}/objects").json()
check("GET /objects → 36", len(objs) == 36)
check("GET /inspections", c.get(f"{B}/inspections").status_code == 200)
check("GET /prescriptions", c.get(f"{B}/prescriptions").status_code == 200)
check("GET /owners", len(c.get(f"{B}/owners").json()) == 8)
check("GET /districts", len(c.get(f"{B}/districts").json()) == 3)
check("GET /object-types", "Билборд" in c.get(f"{B}/object-types").json())
check("GET /analytics/summary", c.get(f"{B}/analytics/summary").json()["total"] == 36)
check("GET /analytics/status-distribution", isinstance(c.get(f"{B}/analytics/status-distribution").json(), dict))

# legacy-префикс /api тоже работает
check("legacy GET /api/objects", len(c.get("/api/objects").json()) == 36)

# auth
login = c.post(f"{B}/auth/v2/login", json={"email": "a.nurlanova@uralsk.kz", "password": "x"})
check("POST /auth/v2/login", login.status_code == 200 and "access_token" in login.json())
tok = login.json()["access_token"]
me = c.get(f"{B}/auth/me", headers={"Authorization": f"Bearer {tok}"})
check("GET /auth/me по токену = урбанист", me.json()["role"] == "urbanist")

# создание объекта
new = c.post(f"{B}/objects", json={"name": "Тест-объект", "type": "Магазин", "lat": 51.2, "lng": 51.3})
check("POST /objects → new", new.status_code == 201 and new.json()["status"] == "new")
nid = new.json()["id"]

# FSM: недопустимый переход new → closed = 409
bad = c.patch(f"{B}/objects/{nid}", json={"patch": {"status": "closed"}})
check("PATCH недопустимый переход → 409", bad.status_code == 409)
# допустимый new → not_inspected
good = c.patch(f"{B}/objects/{nid}", json={"patch": {"status": "not_inspected"}, "note": "ок"})
check("PATCH допустимый переход → 200", good.status_code == 200 and good.json()["status"] == "not_inspected")

# проверка с замечаниями авто-создаёт предписание и меняет статус
insp = c.post(f"{B}/objects/{nid}/inspections", json={
    "inspection": {"id": "", "objectId": nid, "inspector": "Тест", "date": "2026-07-02",
                   "result": "has_remarks", "checklist": [], "photoIds": []},
    "status": "prescription_issued", "note": "нарушение",
    "photos": [{"id": "pz", "kind": "before", "caption": "фото", "date": "2026-07-02", "author": "Тест"}],
})
j = insp.json()
check("POST inspection has_remarks → предписание создано", insp.status_code == 201 and j["prescription"] is not None)
check("  статус объекта → prescription_issued", j["object"]["status"] == "prescription_issued")

# проверка без фото → 400
nofoto = c.post(f"{B}/objects/{nid}/inspections", json={
    "inspection": {"id": "", "objectId": nid, "inspector": "Т", "date": "2026-07-02",
                   "result": "compliant", "checklist": [], "photoIds": []},
    "status": "compliant", "photos": [],
})
check("POST inspection без фото → 400", nofoto.status_code == 400)

# повторная проверка fixed → violation_fixed
re = c.post(f"{B}/objects/{nid}/reinspections", json={"result": "fixed"})
check("POST reinspection fixed → violation_fixed", re.status_code == 200 and re.json()["status"] == "violation_fixed")

# создать пользователя → логин+пароль
usr = c.post(f"{B}/users", json={"name": "Ержан Абдуллин", "role": "urbanist", "position": "спец"})
uj = usr.json()
check("POST /users → login+tempPassword", usr.status_code == 201 and uj["credentials"]["login"] == "e.abdullin")

# отправка предписания по email
pid = c.get(f"{B}/prescriptions").json()[0]["id"]
snd = c.post(f"{B}/prescriptions/{pid}/send", json={})
check("POST /prescriptions/{id}/send", snd.status_code == 200 and snd.json()["sent"] is True)

print(f"\nИТОГ: {ok} успешно, {len(fail)} провалено")
if fail:
    print("Провалено:", fail)
    raise SystemExit(1)
print("ВСЁ ЗЕЛЁНОЕ ✓")
