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

# health (public)
health = c.get("/health").json()
check("GET /health", health.get("status") == "ok")

# anonymous must not reach operational routes
check("GET /objects anon → 401", c.get(f"{B}/objects").status_code == 401)
check("POST /objects anon → 401", c.post(f"{B}/objects", json={"name": "x", "type": "Магазин", "lat": 1, "lng": 1}).status_code == 401)
check("GET /analytics/summary anon → 401", c.get(f"{B}/analytics/summary").status_code == 401)
check("GET /geocode/reverse anon → 401", c.get(f"{B}/geocode/reverse", params={"lat": 51.2, "lng": 51.3}).status_code == 401)

# auth
login = c.post(f"{B}/auth/v2/login", json={"email": "a.nurlanova@uralsk.kz", "password": "UC-0001-u1"})
check("POST /auth/v2/login", login.status_code == 200 and "access_token" in login.json())
tok = login.json()["access_token"]
urbanist_h = {"Authorization": f"Bearer {tok}"}
me = c.get(f"{B}/auth/me", headers=urbanist_h)
check(
    "GET /auth/me по токену = урбанист",
    me.status_code == 200 and me.json()["role"] == "urbanist" and me.json().get("regionId") == "uralsk",
)
bad = c.post(f"{B}/auth/v2/login", json={"email": "a.nurlanova@uralsk.kz", "password": "wrong"})
check("POST /auth/v2/login bad password → 401", bad.status_code == 401)
admin_login = c.post(f"{B}/auth/v2/login", json={"email": "a.kenzhebekov@uralsk.kz", "password": "UC-0003-u3"})
check("POST /auth/v2/login region_admin", admin_login.status_code == 200 and "access_token" in admin_login.json())
admin_tok = admin_login.json()["access_token"]
admin_h = {"Authorization": f"Bearer {admin_tok}"}

# чтения под admin
objs = c.get(f"{B}/objects", headers=admin_h).json()
check("GET /objects → 34 active", len(objs) == 34)
photos_admin = c.get(f"{B}/photos", headers=admin_h)
check(
    "GET /photos admin → seeded with objectId",
    photos_admin.status_code == 200
    and len(photos_admin.json()) >= 1
    and all(p.get("objectId") for p in photos_admin.json()),
)
# upload photo then list includes it
upload = c.post(
    f"{B}/photos",
    headers=admin_h,
    files={"file": ("facade.jpg", b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg")},
    data={"kind": "before", "caption": "smoke facade", "objectId": "o1"},
)
check(
    "POST /photos → 201 with url+objectId",
    upload.status_code == 201
    and upload.json().get("objectId") == "o1"
    and bool(upload.json().get("url"))
    and bool(upload.json().get("id")),
)
photos_after = c.get(f"{B}/photos", headers=admin_h).json()
check(
    "GET /photos includes uploaded",
    any(p["id"] == upload.json()["id"] and p.get("objectId") == "o1" for p in photos_after),
)
# HEIC → JPEG on upload (browser-visible)
try:
    from io import BytesIO
    from PIL import Image
    import pillow_heif

    pillow_heif.register_heif_opener()
    _heic_buf = BytesIO()
    Image.new("RGB", (32, 32), (30, 120, 200)).save(_heic_buf, format="HEIF")
    heic_bytes = _heic_buf.getvalue()
    heic_up = c.post(
        f"{B}/photos",
        headers=admin_h,
        files={"file": ("iphone.HEIC", heic_bytes, "image/heic")},
        data={"kind": "general", "caption": "heic", "objectId": "o1", "id": "ph-heic-smoke"},
    )
    heic_url = (heic_up.json().get("url") or "").lower()
    check(
        "POST /photos HEIC → JPEG stored",
        heic_up.status_code == 201
        and heic_up.json().get("id") == "ph-heic-smoke"
        and ("iphone.jpg" in heic_url or heic_url.endswith(".jpg")),
    )
except Exception as exc:  # pragma: no cover
    check(f"POST /photos HEIC skipped ({exc.__class__.__name__})", False)
# Client id on upload → same id in inspection.photoIds → GET /photos resolves it
client_ph = "ph-smoke-client-1"
up_client = c.post(
    f"{B}/photos",
    headers=admin_h,
    files={"file": ("b.jpg", b"\xff\xd8\xffclient", "image/jpeg")},
    data={"kind": "general", "caption": "client-id", "objectId": "o1", "id": client_ph},
)
check(
    "POST /photos with client id",
    up_client.status_code == 201 and up_client.json().get("id") == client_ph,
)
o_flow = c.post(
    f"{B}/objects",
    json={"name": "Photo-persist", "type": "Магазин", "lat": 51.22, "lng": 51.32},
    headers=admin_h,
)
oid_flow = o_flow.json()["id"]
c.patch(f"{B}/objects/{oid_flow}", json={"patch": {"status": "not_inspected"}, "note": "ok"}, headers=admin_h)
# re-upload bound to new object with same client id pattern
client_ph2 = "ph-smoke-client-2"
c.post(
    f"{B}/photos",
    headers=admin_h,
    files={"file": ("c.jpg", b"\xff\xd8\xffc", "image/jpeg")},
    data={"kind": "before", "caption": "flow", "objectId": oid_flow, "id": client_ph2},
)
insp_flow = c.post(
    f"{B}/objects/{oid_flow}/inspections",
    headers=admin_h,
    json={
        "inspection": {
            "id": "",
            "objectId": oid_flow,
            "inspector": "Тест",
            "date": "2026-07-02",
            "result": "compliant",
            "checklist": [],
            "photoIds": [client_ph2],
        },
        "status": "compliant",
        "photos": [],
    },
)
check(
    "POST inspection photoIds-only (pre-uploaded) → 201",
    insp_flow.status_code == 201 and client_ph2 in insp_flow.json()["inspection"]["photoIds"],
)
photos_flow = c.get(f"{B}/photos", headers=admin_h, params={"ids": client_ph2}).json()
check(
    "GET /photos?ids= resolves inspection photo",
    len(photos_flow) == 1
    and photos_flow[0]["id"] == client_ph2
    and photos_flow[0].get("objectId") == oid_flow
    and bool(photos_flow[0].get("url")),
)
one = c.get(f"{B}/photos/{client_ph2}", headers=admin_h)
check("GET /photos/{id} → 200", one.status_code == 200 and one.json()["id"] == client_ph2)
check("GET /inspections", c.get(f"{B}/inspections", headers=admin_h).status_code == 200)
check("GET /prescriptions", c.get(f"{B}/prescriptions", headers=admin_h).status_code == 200)
check("GET /owners", len(c.get(f"{B}/owners", headers=admin_h).json()) == 8)
check("GET /districts", len(c.get(f"{B}/districts", headers=admin_h).json()) == 3)
check("GET /object-types", "Билборд" in c.get(f"{B}/object-types", headers=admin_h).json())
check("GET /analytics/summary", c.get(f"{B}/analytics/summary", headers=admin_h).json()["total"] >= 34)
check("GET /analytics/status-distribution", isinstance(c.get(f"{B}/analytics/status-distribution", headers=admin_h).json(), dict))
check("GET /geocode/reverse auth", c.get(f"{B}/geocode/reverse", params={"lat": 51.2, "lng": 51.3}, headers=admin_h).status_code == 200)

# создание объекта
new = c.post(f"{B}/objects", json={"name": "Тест-объект", "type": "Магазин", "lat": 51.2, "lng": 51.3}, headers=admin_h)
check("POST /objects → new", new.status_code == 201 and new.json()["status"] == "new")
nid = new.json()["id"]

# FSM: недопустимый переход new → closed = 409
bad = c.patch(f"{B}/objects/{nid}", json={"patch": {"status": "closed"}}, headers=admin_h)
check("PATCH недопустимый переход → 409", bad.status_code == 409)
check("PATCH недопустимый переход envelope", bad.json()["code"] == "conflict" and "Недопустимый переход" in bad.json()["message"])
# допустимый new → not_inspected
good = c.patch(f"{B}/objects/{nid}", json={"patch": {"status": "not_inspected"}, "note": "ок"}, headers=admin_h)
check("PATCH допустимый переход → 200", good.status_code == 200 and good.json()["status"] == "not_inspected")

# проверка с замечаниями авто-создаёт предписание и меняет статус
insp = c.post(f"{B}/objects/{nid}/inspections", headers=admin_h, json={
    "inspection": {"id": "", "objectId": nid, "inspector": "Тест", "date": "2026-07-02",
                   "result": "has_remarks", "checklist": [], "photoIds": []},
    "status": "prescription_issued", "note": "нарушение",
    "photos": [{"id": "pz", "kind": "before", "caption": "фото", "date": "2026-07-02", "author": "Тест"}],
})
j = insp.json()
check("POST inspection has_remarks → предписание создано", insp.status_code == 201 and j["prescription"] is not None)
check("  статус объекта → prescription_issued", j["object"]["status"] == "prescription_issued")

# проверка без фото → 400
nofoto = c.post(f"{B}/objects/{nid}/inspections", headers=admin_h, json={
    "inspection": {"id": "", "objectId": nid, "inspector": "Т", "date": "2026-07-02",
                   "result": "compliant", "checklist": [], "photoIds": []},
    "status": "compliant", "photos": [],
})
check("POST inspection без фото → 400", nofoto.status_code == 400)

# повторная проверка fixed → violation_fixed
re = c.post(f"{B}/objects/{nid}/reinspections", headers=admin_h, json={"result": "fixed"})
check("POST reinspection fixed → violation_fixed", re.status_code == 200 and re.json()["status"] == "violation_fixed")

# DELETE object: no token → 401, urbanist → 403, region_admin → 204 (soft-archive)
del_anon = c.delete(f"{B}/objects/{nid}")
check("DELETE /objects without token → 401", del_anon.status_code == 401)
del_forbidden = c.delete(f"{B}/objects/{nid}", headers=urbanist_h)
check("DELETE /objects as urbanist → 403", del_forbidden.status_code == 403)
del_ok = c.delete(f"{B}/objects/{nid}", headers=admin_h)
check("DELETE /objects as region_admin → 204", del_ok.status_code == 204)
gone = c.get(f"{B}/objects/{nid}", headers=admin_h)
check("GET deleted object → 404", gone.status_code == 404)
check("GET deleted object envelope", gone.json()["code"] == "not_found")

# bulk-delete: same soft-archive semantics
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
check("GET bulk-deleted object → 404", c.get(f"{B}/objects/{b1.json()['id']}", headers=admin_h).status_code == 404)
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
filt = c.get(f"{B}/owners", params={"ownerUserId": own_uid}, headers=admin_h)
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

# PATCH без ownerUserId не должен затирать связь
patch_keep = c.patch(
    f"{B}/owners/{biz1.json()['id']}",
    headers=admin_h,
    json={"name": "ТОО Альфа (правка)", "legalForm": "ТОО", "phone": "+77001110001"},
)
check(
    "PATCH /owners omit ownerUserId → keeps link",
    patch_keep.status_code == 200 and patch_keep.json().get("ownerUserId") == own_uid,
)

bad_bin = c.post(
    f"{B}/owners",
    json={
        "name": "ТОО Bad BIN",
        "legalForm": "ТОО",
        "bin": "123123",
        "phone": "87086272471",
    },
    headers=admin_h,
)
check(
    "POST /owners invalid bin → 422",
    bad_bin.status_code == 422
    and (
        bad_bin.json().get("code") in {"invalid_bin", "validation_error"}
        or "12" in str(bad_bin.json())
    ),
)

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
own_obj_ids = {o["id"] for o in own_objs.json()}
check(
    "GET /history owner-scoped",
    owner_hist.status_code == 200 and all(h["objectId"] in own_obj_ids for h in owner_hist.json()),
)
owner_notifs = c.get(f"{B}/notifications", headers=owner_h)
check(
    "GET /notifications owner-scoped",
    owner_notifs.status_code == 200 and all(n["objectId"] in own_obj_ids for n in owner_notifs.json()),
)
owner_summary = c.get(f"{B}/analytics/summary", headers=owner_h)
check(
    "GET /analytics/summary owner-scoped",
    owner_summary.status_code == 200 and owner_summary.json()["total"] == len(own_objs.json()),
)
audit_forbidden = c.get(f"{B}/audit", headers=urbanist_h)
check("GET /audit as urbanist → 403", audit_forbidden.status_code == 403)
audit_admin = c.get(f"{B}/audit", headers=admin_h)
check("GET /audit as region_admin → 200", audit_admin.status_code == 200)

# checklist template + geo + streets
cl = c.get(f"{B}/checklist-template", headers=admin_h)
check(
    "GET /checklist-template → 6 visible",
    cl.status_code == 200 and len(cl.json()) == 6 and all(i["isVisible"] for i in cl.json()),
)
hide = c.post(
    f"{B}/checklist-template/manage",
    headers=admin_h,
    json={
        "items": [
            {
                "id": cl.json()[0]["id"],
                "key": cl.json()[0]["key"],
                "titleRu": cl.json()[0]["titleRu"],
                "titleKz": cl.json()[0].get("titleKz", ""),
                "category": cl.json()[0].get("category", ""),
                "sortOrder": cl.json()[0].get("sortOrder", 1),
                "isVisible": False,
            }
        ]
    },
)
check("POST /checklist-template/manage hide → 200", hide.status_code == 200)
cl2 = c.get(f"{B}/checklist-template", headers=admin_h)
check("GET /checklist-template after hide → 5", cl2.status_code == 200 and len(cl2.json()) == 5)
# restore visibility for other tests
c.post(
    f"{B}/checklist-template/manage",
    headers=admin_h,
    json={
        "items": [
            {
                "id": cl.json()[0]["id"],
                "key": cl.json()[0]["key"],
                "titleRu": cl.json()[0]["titleRu"],
                "titleKz": cl.json()[0].get("titleKz", ""),
                "category": cl.json()[0].get("category", ""),
                "sortOrder": cl.json()[0].get("sortOrder", 1),
                "isVisible": True,
            }
        ]
    },
)

geo = c.get(f"{B}/cities/uralsk/geo-config", headers=admin_h)
check(
    "GET /cities/uralsk/geo-config",
    geo.status_code == 200
    and geo.json().get("addressSchema") == "microdistrict,street,house"
    and geo.json().get("hasStreets") is True,
)
geo_forbidden = c.get(f"{B}/cities/othercity/geo-config", headers=admin_h)
check("GET geo-config other city → 403", geo_forbidden.status_code == 403)

cur = c.get(f"{B}/cities/current", headers=admin_h)
check(
    "GET /cities/current → uralsk",
    cur.status_code == 200
    and cur.json().get("id") == "uralsk"
    and cur.json().get("name") == "Уральск"
    and cur.json().get("addressSchema") == "microdistrict,street,house",
)
geo_patch = c.patch(
    f"{B}/cities/uralsk/geo-config",
    headers=admin_h,
    json={"hasStreets": True, "addressSchema": "microdistrict,street,house", "oblast": "ЗКО"},
)
check("PATCH /cities/uralsk/geo-config → 200", geo_patch.status_code == 200 and geo_patch.json().get("oblast") == "ЗКО")
geo_patch_forbidden = c.patch(
    f"{B}/cities/uralsk/geo-config",
    headers=urbanist_h,
    json={"hasStreets": False},
)
check("PATCH geo-config as urbanist → 403", geo_patch_forbidden.status_code == 403)

st = c.post(
    f"{B}/streets",
    headers=admin_h,
    json={"name": "Кунаева", "microdistrictId": "m1"},
)
check("POST /streets → 201", st.status_code == 201 and st.json()["name"] == "Кунаева")
sts = c.get(f"{B}/streets", headers=admin_h)
check("GET /streets → >=1", sts.status_code == 200 and len(sts.json()) >= 1)
st_patch = c.patch(f"{B}/streets/{st.json()['id']}", headers=admin_h, json={"name": "Кунаева пр."})
check("PATCH /streets → 200", st_patch.status_code == 200 and st_patch.json()["name"] == "Кунаева пр.")
# restore name for address test
c.patch(f"{B}/streets/{st.json()['id']}", headers=admin_h, json={"name": "Кунаева"})
st_del_forbidden = c.delete(f"{B}/streets/{st.json()['id']}", headers=urbanist_h)
check("DELETE /streets as urbanist → 403", st_del_forbidden.status_code == 403)

md_free = c.post(
    f"{B}/microdistricts/manage",
    headers=admin_h,
    json={"name": "Без района", "districtId": None},
)
check("POST microdistrict without district → 201", md_free.status_code == 201 and md_free.json().get("districtId") is None)

addr_obj = c.post(
    f"{B}/objects",
    headers=admin_h,
    json={
        "name": "Адрес-тест",
        "type": "Магазин",
        "lat": 51.2,
        "lng": 51.3,
        "microdistrictId": "m1",
        "streetId": st.json()["id"],
        "house": "12",
    },
)
check(
    "POST /objects builds address",
    addr_obj.status_code == 201
    and "Кунаева" in addr_obj.json().get("address", "")
    and "12" in addr_obj.json().get("address", ""),
)
c.delete(f"{B}/objects/{addr_obj.json()['id']}", headers=admin_h)
st_del = c.delete(f"{B}/streets/{st.json()['id']}", headers=admin_h)
check("DELETE /streets → 204", st_del.status_code == 204)
check("GET /streets after delete excludes removed", all(s["id"] != st.json()["id"] for s in c.get(f"{B}/streets", headers=admin_h).json()))

# platform provision creates city + 6 checklist items
from app.user_helpers import PLATFORM_SUPERADMIN_EMAIL, PLATFORM_SUPERADMIN_PASSWORD

sa_login = c.post(
    f"{B}/auth/v2/login",
    json={"email": PLATFORM_SUPERADMIN_EMAIL, "password": PLATFORM_SUPERADMIN_PASSWORD},
)
check("POST /auth/v2/login platform_superadmin", sa_login.status_code == 200)
sa_h = {"Authorization": f"Bearer {sa_login.json()['access_token']}"}
prov = c.post(
    f"{B}/platform/regions",
    headers=sa_h,
    json={
        "code": "smoke-city",
        "name": "Smoke City",
        "adminName": "Smoke Admin",
        # hasDistricts=True by default (как Актау) — география всё равно пустая
        "hasDistricts": True,
        "hasMicrodistricts": True,
        "hasStreets": True,
        "addressSchema": "street,house",
        "cityType": "city",
        "oblast": "ЗКО",
    },
)
check(
    "POST /platform/regions → 201 + geo",
    prov.status_code == 201
    and prov.json()["region"]["id"] == "smoke-city"
    and prov.json()["region"].get("hasDistricts") is True
    and len(prov.json()["region"].get("addressSchema", "")) > 0,
)
# operational store checklist seeded for new city (memory parity)
from app.deps import _memory

check(
    "provision seeds 6 checklist items",
    len(_memory._checklist.get("smoke-city", [])) == 6,
)
check(
    "provision does not copy Uralsk districts",
    _memory._districts.get("smoke-city") == [],
)
check(
    "provision does not copy Uralsk microdistricts",
    _memory._microdistricts.get("smoke-city") == [],
)
check(
    "provision streets empty",
    _memory._streets.get("smoke-city") == [],
)
# login as new city admin → geography lists empty
new_admin = prov.json()["credentials"]
city_login = c.post(
    f"{B}/auth/v2/login",
    json={"email": new_admin["login"], "password": new_admin["tempPassword"]},
)
check("POST /auth/v2/login new city admin", city_login.status_code == 200)
city_h = {"Authorization": f"Bearer {city_login.json()['access_token']}"}
check(
    "GET /districts new city → []",
    c.get(f"{B}/districts", headers=city_h).json() == [],
)
check(
    "GET /microdistricts new city → []",
    c.get(f"{B}/microdistricts", headers=city_h).json() == [],
)
check(
    "GET /streets new city → []",
    c.get(f"{B}/streets", headers=city_h).json() == [],
)
check(
    "GET /checklist-template new city → 6",
    len(c.get(f"{B}/checklist-template", headers=city_h).json()) == 6,
)

# отправка предписания по email
pid = c.get(f"{B}/prescriptions", headers=admin_h).json()[0]["id"]
snd = c.post(f"{B}/prescriptions/{pid}/send", json={}, headers=admin_h)
check("POST /prescriptions/{id}/send", snd.status_code == 200 and snd.json()["sent"] is True)

print(f"\nИТОГ: {ok} успешно, {len(fail)} провалено")
if fail:
    print("Провалено:", fail)
    raise SystemExit(1)
print("ВСЁ ЗЕЛЁНОЕ ✓")
