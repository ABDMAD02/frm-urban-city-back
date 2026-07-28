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
check("GET /objects → 34 active", len(objs) == 34)
check("GET /inspections", c.get(f"{B}/inspections").status_code == 200)
check("GET /prescriptions", c.get(f"{B}/prescriptions").status_code == 200)
check("GET /owners", len(c.get(f"{B}/owners").json()) == 8)
check("GET /districts", len(c.get(f"{B}/districts").json()) == 3)
check("GET /object-types", "Билборд" in c.get(f"{B}/object-types").json())
check("GET /analytics/summary", c.get(f"{B}/analytics/summary").json()["total"] == 36)
check("GET /analytics/status-distribution", isinstance(c.get(f"{B}/analytics/status-distribution").json(), dict))

# auth
login = c.post(f"{B}/auth/v2/login", json={"email": "a.nurlanova@uralsk.kz", "password": "UC-0001-u1"})
check("POST /auth/v2/login", login.status_code == 200 and "access_token" in login.json())
tok = login.json()["access_token"]
urbanist_h = {"Authorization": f"Bearer {tok}"}
me = c.get(f"{B}/auth/me", headers={"Authorization": f"Bearer {tok}"})
check("GET /auth/me по токену = урбанист", me.json()["role"] == "urbanist")
bad = c.post(f"{B}/auth/v2/login", json={"email": "a.nurlanova@uralsk.kz", "password": "wrong"})
check("POST /auth/v2/login bad password → 401", bad.status_code == 401)
admin_login = c.post(f"{B}/auth/v2/login", json={"email": "a.kenzhebekov@uralsk.kz", "password": "UC-0003-u3"})
check("POST /auth/v2/login region_admin", admin_login.status_code == 200 and "access_token" in admin_login.json())
admin_tok = admin_login.json()["access_token"]
admin_h = {"Authorization": f"Bearer {admin_tok}"}

# создание объекта
new = c.post(f"{B}/objects", json={"name": "Тест-объект", "type": "Магазин", "lat": 51.2, "lng": 51.3})
check("POST /objects → new", new.status_code == 201 and new.json()["status"] == "new")
nid = new.json()["id"]

# FSM: недопустимый переход new → closed = 409
bad = c.patch(f"{B}/objects/{nid}", json={"patch": {"status": "closed"}})
check("PATCH недопустимый переход → 409", bad.status_code == 409)
check("PATCH недопустимый переход envelope", bad.json()["code"] == "http_409" and "Недопустимый переход" in bad.json()["message"])
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

# DELETE object: no token → 401, urbanist → 403, region_admin → 204
del_anon = c.delete(f"{B}/objects/{nid}")
check("DELETE /objects without token → 401", del_anon.status_code == 401)
del_forbidden = c.delete(f"{B}/objects/{nid}", headers=urbanist_h)
check("DELETE /objects as urbanist → 403", del_forbidden.status_code == 403)
del_ok = c.delete(f"{B}/objects/{nid}", headers=admin_h)
check("DELETE /objects as region_admin → 204", del_ok.status_code == 204)
gone = c.get(f"{B}/objects/{nid}", headers=admin_h)
check("GET deleted object → 404", gone.status_code == 404)
check("GET deleted object envelope", gone.json()["code"] == "http_404")

# bulk-delete: create two, delete with missing id mixed in
b1 = c.post(f"{B}/objects", json={"name": "Bulk-1", "type": "Магазин", "lat": 51.2, "lng": 51.3}, headers=admin_h)
b2 = c.post(f"{B}/objects", json={"name": "Bulk-2", "type": "Магазин", "lat": 51.21, "lng": 51.31}, headers=admin_h)
bulk_ids = [b1.json()["id"], b2.json()["id"], "missing-id", b1.json()["id"]]
bulk_forbidden = c.post(f"{B}/objects/bulk-delete", json={"ids": bulk_ids}, headers=urbanist_h)
check("POST /objects/bulk-delete as urbanist → 403", bulk_forbidden.status_code == 403)
bulk_ok = c.post(f"{B}/objects/bulk-delete", json={"ids": bulk_ids}, headers=admin_h)
check(
    "POST /objects/bulk-delete → deleted=2",
    bulk_ok.status_code == 200 and bulk_ok.json().get("deleted") == 2,
)
bulk_again = c.post(f"{B}/objects/bulk-delete", json={"ids": bulk_ids}, headers=admin_h)
check(
    "POST /objects/bulk-delete idempotent → deleted=0",
    bulk_again.status_code == 200 and bulk_again.json().get("deleted") == 0,
)

# создать пользователя → логин+пароль
usr_forbidden = c.post(f"{B}/users", json={"name": "Ержан Абдуллин", "role": "urbanist", "position": "спец"}, headers=urbanist_h)
check("POST /users as urbanist → 403", usr_forbidden.status_code == 403)
usr = c.post(f"{B}/users", json={"name": "Ержан Абдуллин", "role": "urbanist", "position": "спец"}, headers=admin_h)
uj = usr.json()
check("POST /users → login+tempPassword", usr.status_code == 201 and uj["credentials"]["login"] == "e.abdullin")

# DELETE user: only region_admin
del_user_target = c.post(
    f"{B}/users",
    json={"name": "Удаляемый Юзер", "role": "urbanist", "position": "спец"},
    headers=admin_h,
)
del_uid = del_user_target.json()["user"]["id"]
del_user_anon = c.delete(f"{B}/users/{del_uid}")
check("DELETE /users without token → 401", del_user_anon.status_code == 401)
del_user_forbidden = c.delete(f"{B}/users/{del_uid}", headers=urbanist_h)
check("DELETE /users as urbanist → 403", del_user_forbidden.status_code == 403)
del_self = c.delete(f"{B}/users/u3", headers=admin_h)
check("DELETE /users self → 403", del_self.status_code == 403)
del_user_ok = c.delete(f"{B}/users/{del_uid}", headers=admin_h)
check("DELETE /users as region_admin → 204", del_user_ok.status_code == 204)
users_after = c.get(f"{B}/users", headers=admin_h)
check(
    "GET /users after delete excludes removed",
    users_after.status_code == 200 and all(u["id"] != del_uid for u in users_after.json()),
)

# аккаунт-владелец + несколько ТОО (ownerUserId)
own_acc = c.post(
    f"{B}/users",
    json={"name": "Тест Владелец", "role": "owner", "position": "Владелец бизнеса"},
    headers=admin_h,
)
check("POST /users role=owner → 201", own_acc.status_code == 201)
own_uid = own_acc.json()["user"]["id"]
biz1 = c.post(
    f"{B}/owners",
    json={
        "name": "ТОО «Мади»",
        "legalForm": "ТОО",
        "bin": "121203550179",
        "phone": "87086272471",
        "email": "owner@mail.kz",
        "ownerUserId": own_uid,
    },
    headers=admin_h,
)
check("POST /owners with ownerUserId → 201", biz1.status_code == 201 and biz1.json().get("ownerUserId") == own_uid)
biz2 = c.post(
    f"{B}/owners",
    json={
        "name": "ИП «Мади»",
        "legalForm": "ИП",
        "bin": "900101300123",
        "phone": "87086272471",
        "ownerUserId": own_uid,
    },
    headers=admin_h,
)
check("POST second Owner same account → 201", biz2.status_code == 201)
filt = c.get(f"{B}/owners", params={"ownerUserId": own_uid})
check("GET /owners?ownerUserId= → 2", filt.status_code == 200 and len(filt.json()) == 2)
bad_link = c.post(
    f"{B}/owners",
    json={
        "name": "ТОО Bad",
        "legalForm": "ТОО",
        "bin": "121203550180",
        "phone": "87086272471",
        "ownerUserId": "u1",
    },
    headers=admin_h,
)
check("POST /owners ownerUserId=urbanist → 422", bad_link.status_code == 422)

# owner scope: my businesses + per-business filters + foreign business denied
owner_login = c.post(f"{B}/auth/v2/login", json={"email": "d.saparov@uralsk.kz", "password": "UC-0002-u2"})
check("POST /auth/v2/login owner", owner_login.status_code == 200 and "access_token" in owner_login.json())
owner_tok = owner_login.json()["access_token"]
owner_h = {"Authorization": f"Bearer {owner_tok}"}
mybiz = c.get(f"{B}/owners/my", headers=owner_h)
check("GET /owners/my → 1", mybiz.status_code == 200 and len(mybiz.json()) == 1 and mybiz.json()[0]["id"] == "w2")
own_objs = c.get(f"{B}/objects", params={"ownerId": "w2"}, headers=owner_h)
check(
    "GET /objects?ownerId=own scoped",
    own_objs.status_code == 200
    and len(own_objs.json()) >= 1
    and all(obj["ownerId"] == "w2" for obj in own_objs.json()),
)
foreign_objs = c.get(f"{B}/objects", params={"ownerId": "w1"}, headers=owner_h)
check("GET /objects?ownerId=foreign → 403", foreign_objs.status_code == 403)
own_pr = c.get(f"{B}/prescriptions", params={"ownerId": "w2"}, headers=owner_h)
check("GET /prescriptions?ownerId=own → 2", own_pr.status_code == 200 and len(own_pr.json()) == 2)
foreign_pr = c.get(f"{B}/prescriptions", params={"ownerId": "w1"}, headers=owner_h)
check("GET /prescriptions?ownerId=foreign → 403", foreign_pr.status_code == 403)
owner_ph = c.get(f"{B}/photos", headers=owner_h)
check("GET /photos owner-scoped", owner_ph.status_code == 200 and len(owner_ph.json()) >= 1)
owner_hist = c.get(f"{B}/history", headers=owner_h)
check("GET /history owner-scoped", owner_hist.status_code == 200 and all(h["objectId"] in {"o5", "o12"} for h in owner_hist.json()))
owner_notifs = c.get(f"{B}/notifications", headers=owner_h)
check("GET /notifications owner-scoped", owner_notifs.status_code == 200 and all(n["objectId"] in {"o5", "o12"} for n in owner_notifs.json()))
audit_forbidden = c.get(f"{B}/audit", headers=urbanist_h)
check("GET /audit as urbanist → 403", audit_forbidden.status_code == 403)
audit_admin = c.get(f"{B}/audit", headers=admin_h)
check("GET /audit as region_admin → 200", audit_admin.status_code == 200)

# отправка предписания по email
pid = c.get(f"{B}/prescriptions").json()[0]["id"]
snd = c.post(f"{B}/prescriptions/{pid}/send", json={})
check("POST /prescriptions/{id}/send", snd.status_code == 200 and snd.json()["sent"] is True)

print(f"\nИТОГ: {ok} успешно, {len(fail)} провалено")
if fail:
    print("Провалено:", fail)
    raise SystemExit(1)
print("ВСЁ ЗЕЛЁНОЕ ✓")
