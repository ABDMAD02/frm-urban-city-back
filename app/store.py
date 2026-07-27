"""In-memory хранилище + сид-данные (пилот — Уральск).
Порт frontend/src/data/mock-data.ts. В проде заменяется на БД (PostgreSQL),
но контракт (эти же коллекции) сохраняется."""
from __future__ import annotations
import math
from .models import (
    District, Microdistrict, User, Owner, Photo, ChecklistItem, Inspection,
    Prescription, HistoryEvent, ObjectVersion, CityObject, TrendPoint,
)
from .enums import (
    Role, AccountStatus, LegalForm, PhotoKind, ChecklistValue, InspectionResult,
    PrescriptionStatus, HistoryType, ObjectStatus,
)

DISTRICTS = [
    District(id="d1", name="Центральный район"),
    District(id="d2", name="Зачаганск"),
    District(id="d3", name="Затон"),
]

MICRODISTRICTS = [
    Microdistrict(id="m1", districtId="d1", name="мкр. Астана"),
    Microdistrict(id="m2", districtId="d1", name="мкр. Женис"),
    Microdistrict(id="m3", districtId="d1", name="мкр. Кунаева"),
    Microdistrict(id="m4", districtId="d2", name="мкр. Строитель"),
    Microdistrict(id="m5", districtId="d2", name="мкр. Сарыарка"),
    Microdistrict(id="m6", districtId="d3", name="мкр. Атамекен"),
    Microdistrict(id="m7", districtId="d3", name="мкр. Мирлан"),
]

STREETS = [
    "пр. Абулхаир хана", "ул. Достык-Дружба", "ул. Курмангазы", "ул. Сарайшык",
    "пр. Евразия", "ул. Ихсанова", "ул. Ментешева", "ул. Жангир хана",
]

USERS = [
    User(id="u1", name="Айгерим Нурланова", role=Role.urbanist,
         position="Главный специалист отдела урбанистики",
         microdistrictIds=["m1", "m2", "m3"], login="a.nurlanova",
         status=AccountStatus.active, createdAt="2026-05-12", regionId="uralsk"),
    User(id="u2", name="Данияр Сапаров", role=Role.owner, position="ИП «Сапаров»",
         ownerObjectIds=["o5", "o12"], login="d.saparov",
         status=AccountStatus.active, createdAt="2026-05-20", regionId="uralsk"),
    User(id="u3", name="Асхат Кенжебеков", role=Role.region_admin,
         position="Администратор региона", login="a.kenzhebekov",
         status=AccountStatus.active, createdAt="2026-05-01", regionId="uralsk"),
    User(id="sa1", name="Platform Superadmin", role=Role.platform_superadmin,
         position="Супер-администратор платформы", login="platform.admin",
         email="platform.admin@urban-city.kz", status=AccountStatus.active, createdAt="2026-05-01",
         regionId=None),
]

OWNERS = [
    Owner(id="w1", name="ТОО «Урал-Строй»", legalForm=LegalForm.too, bin="180140012345", phone="+7 711 234-56-78"),
    Owner(id="w2", name="ИП «Сапаров Д.»", legalForm=LegalForm.ip, bin="870615300123", phone="+7 705 111-22-33", email="saparov@mail.kz"),
    Owner(id="w3", name="ТОО «Гранд Плаза»", legalForm=LegalForm.too, bin="160240067890", phone="+7 711 555-10-20"),
    Owner(id="w4", name="Акимат г. Уральск", legalForm=LegalForm.gosorgan, phone="+7 711 500-00-00"),
    Owner(id="w5", name="ИП «Ахметова Г.»", legalForm=LegalForm.ip, bin="920310450678", phone="+7 747 900-80-70"),
    Owner(id="w6", name="ТОО «Каспий Ритейл»", legalForm=LegalForm.too, bin="140540098765", phone="+7 711 322-45-67"),
    Owner(id="w7", name="ИП «Мукашев Т.»", legalForm=LegalForm.ip, bin="881122300456", phone="+7 700 654-32-10"),
    Owner(id="w8", name="Физлицо Оспанов К.", legalForm=LegalForm.fizlico, phone="+7 778 123-45-67"),
]

TYPES = [
    ("Магазин", "Торговля"), ("Кафе", "Общепит"), ("Торговый центр", "Торговля"),
    ("Ресторан", "Общепит"), ("Аптека", "Медицина"), ("Банк", "Финансы"),
    ("Административное здание", "Госучреждения"), ("Жилой дом", "Жильё"),
    ("Рекламная конструкция", "Реклама"), ("Билборд", "Реклама"),
    ("Гостиница", "Гостиничный бизнес"), ("Бизнес-центр", "Офисы"),
    ("Остановка", "Инфраструктура"), ("Парк", "Благоустройство"),
]
OBJECT_TYPES = [t[0] for t in TYPES]

NAMES = [
    "Магазин «Береке»", "Кафе «Достар»", "ТРЦ «Атриум»", "Ресторан «Урал»",
    "Аптека «Дару»", "Отделение Halyk Bank", "Дом культуры", "ЖК «Наурыз»",
    "Билборд №14", "LED-экран пр. Евразия", "Гостиница «Пушкинъ»", "БЦ «Евразия»",
    "Остановка «Центр»", "Сквер Абая", "Супермаркет «Магнум»", "Кофейня «Bir Kofe»",
    "Салон «Ажар»", "Автомойка «Аква»", "Пекарня «Тандыр»", "Фитнес «Energy»",
    "Магазин «Смолл»", "Кафе «Шелковый путь»", "Аптека 36,6", "Отделение Kaspi",
    "Офис «Казпочта»", "Магазин «Технодом»", "Ресторан «Астана»", "ЖК «Family»",
    "Рекламный щит №22", "Павильон «Пресса»", "Гостиница «Сафари»", "БЦ «Премьер»",
    "Магазин «Anvar»", "Кафе «Лагман Хаус»", "Аптека «Здоровье»", "Клиника «Медикер»",
]

STATUS_POOL = [
    "compliant", "compliant", "compliant", "has_remarks", "has_remarks",
    "prescription_issued", "prescription_issued", "awaiting_reinspection",
    "violation_fixed", "not_inspected", "not_inspected", "new", "closed", "archived",
]

CENTER = (51.2255, 51.3667)


def _seeded(i: int, salt: int = 1) -> float:
    x = math.sin(i * 999 + salt * 17) * 10000
    return x - math.floor(x)


def _build_objects() -> list[CityObject]:
    out: list[CityObject] = []
    for i in range(len(NAMES)):
        t = TYPES[i % len(TYPES)]
        md = MICRODISTRICTS[i % len(MICRODISTRICTS)]
        status = STATUS_POOL[i % len(STATUS_POOL)]
        owner = OWNERS[i % len(OWNERS)]
        lat = CENTER[0] + (_seeded(i, 1) - 0.5) * 0.06
        lng = CENTER[1] + (_seeded(i, 2) - 0.5) * 0.09
        street = STREETS[i % len(STREETS)]
        house = 1 + int(_seeded(i, 3) * 120)
        out.append(CityObject(
            id=f"o{i + 1}", name=NAMES[i], type=t[0], category=t[1],
            address=f"{street}, {house}", lat=lat, lng=lng,
            districtId=md.districtId, microdistrictId=md.id, street=street,
            ownerId=owner.id, status=ObjectStatus(status),
            responsible="Айгерим Нурланова",
            createdAt=f"2025-0{1 + (i % 6)}-{10 + (i % 18)}",
            updatedAt=f"2026-0{1 + (i % 6)}-{5 + (i % 20)}",
        ))
    # объекты владельца-демо (u2 → w2)
    out[4].ownerId = "w2"; out[4].status = ObjectStatus.prescription_issued
    out[11].ownerId = "w2"; out[11].status = ObjectStatus.awaiting_reinspection
    return out


OBJECTS = _build_objects()

PHOTOS = [
    Photo(id="p1", kind=PhotoKind.before, caption="Фасад до устранения — незаконная вывеска", color="#b45309", date="2026-05-12", author="Айгерим Нурланова"),
    Photo(id="p2", kind=PhotoKind.before, caption="Рекламная конструкция без паспорта", color="#92400e", date="2026-05-12", author="Айгерим Нурланова"),
    Photo(id="p3", kind=PhotoKind.after, caption="Фасад после устранения", color="#15803d", date="2026-06-20", author="Данияр Сапаров"),
    Photo(id="p4", kind=PhotoKind.general, caption="Общий вид объекта", color="#0b5cad", date="2026-05-12", author="Айгерим Нурланова"),
    Photo(id="p5", kind=PhotoKind.before, caption="Входная группа — нарушение дизайн-кода", color="#a16207", date="2026-04-03", author="Айгерим Нурланова"),
    Photo(id="p6", kind=PhotoKind.after, caption="Входная группа приведена в соответствие", color="#0f766e", date="2026-05-01", author="Данияр Сапаров"),
]


def _checklist(issues: list[str]) -> list[ChecklistItem]:
    base = [("facade", "Фасад"), ("signboard", "Вывеска"), ("ads", "Рекламные конструкции"),
            ("entrance", "Входная группа"), ("design_code", "Соответствие дизайн-коду"),
            ("cleanliness", "Чистота прилегающей территории")]
    return [ChecklistItem(key=k, label=l,
                          value=ChecklistValue.issue if k in issues else ChecklistValue.ok,
                          comment="Выявлено несоответствие дизайн-коду" if k in issues else None)
            for k, l in base]


INSPECTIONS = [
    Inspection(id="insp1", objectId="o5", inspector="Айгерим Нурланова", date="2026-05-12",
               result=InspectionResult.has_remarks, checklist=_checklist(["signboard", "ads"]),
               comment="Вывеска и рекламная конструкция не соответствуют дизайн-коду.",
               photoIds=["p1", "p2", "p4"]),
    Inspection(id="insp2", objectId="o12", inspector="Айгерим Нурланова", date="2026-04-03",
               result=InspectionResult.has_remarks, checklist=_checklist(["entrance", "facade"]),
               comment="Входная группа и фасад требуют приведения в соответствие.", photoIds=["p5"]),
    Inspection(id="insp3", objectId="o1", inspector="Айгерим Нурланова", date="2026-06-01",
               result=InspectionResult.compliant, checklist=_checklist([]),
               comment="Объект соответствует дизайн-коду.", photoIds=["p4"]),
]

PRESCRIPTIONS = [
    Prescription(id="pr1", objectId="o5", inspectionId="insp1",
                 title="Демонтаж незаконной вывески и рекламной конструкции",
                 description="Привести вывеску и рекламную конструкцию в соответствие с дизайн-кодом. Демонтировать несогласованные элементы.",
                 issuedAt="2026-05-12", deadline="2026-06-12", reinspectionDate="2026-06-15",
                 status=PrescriptionStatus.overdue),
    Prescription(id="pr2", objectId="o12", inspectionId="insp2",
                 title="Приведение входной группы в соответствие",
                 description="Восстановить архитектурный облик входной группы и фасада согласно дизайн-коду.",
                 issuedAt="2026-04-03", deadline="2026-05-03", reinspectionDate="2026-07-10",
                 status=PrescriptionStatus.fixed),
]

HISTORY = [
    HistoryEvent(id="h1", objectId="o5", type=HistoryType.object_created, actor="Айгерим Нурланова", date="2025-03-14", text="Объект создан и добавлен на карту"),
    HistoryEvent(id="h2", objectId="o5", type=HistoryType.inspection_done, actor="Айгерим Нурланова", date="2026-05-12", text="Проведена проверка — выявлены замечания"),
    HistoryEvent(id="h4", objectId="o5", type=HistoryType.prescription_issued, actor="Айгерим Нурланова", date="2026-05-12", text="Выдано предписание, срок устранения — 12.06.2026"),
    HistoryEvent(id="h6", objectId="o12", type=HistoryType.object_created, actor="Айгерим Нурланова", date="2025-02-20", text="Объект создан"),
    HistoryEvent(id="h9", objectId="o12", type=HistoryType.photos_uploaded, actor="Данияр Сапаров", date="2026-04-28", text="Владелец загрузил фотографии «после устранения»"),
    HistoryEvent(id="h12", objectId="o1", type=HistoryType.object_created, actor="Айгерим Нурланова", date="2025-01-10", text="Объект создан"),
    HistoryEvent(id="h13", objectId="o1", type=HistoryType.inspection_done, actor="Айгерим Нурланова", date="2026-06-01", text="Проведена проверка — соответствует дизайн-коду"),
]

VERSIONS = [
    ObjectVersion(id="v1", objectId="o5", date="2025-03-14", author="Айгерим Нурланова", label="Версия 1 — создание", changes=["Создан цифровой паспорт объекта", "Заданы координаты и адрес"]),
    ObjectVersion(id="v2", objectId="o5", date="2026-05-12", author="Айгерим Нурланова", label="Версия 2 — проверка", changes=["Изменён статус: Предписание выдано", "Добавлены фото фасада «до»"]),
    ObjectVersion(id="v3", objectId="o12", date="2025-02-20", author="Айгерим Нурланова", label="Версия 1 — создание", changes=["Создан цифровой паспорт объекта"]),
]

INSPECTION_TREND = [
    TrendPoint(month="Янв", value=8), TrendPoint(month="Фев", value=12),
    TrendPoint(month="Мар", value=17), TrendPoint(month="Апр", value=14),
    TrendPoint(month="Май", value=22), TrendPoint(month="Июн", value=26),
]

# Счётчики для генерации id новых записей.
_counters = {"o": len(OBJECTS), "insp": len(INSPECTIONS), "pr": len(PRESCRIPTIONS),
             "d": len(DISTRICTS), "m": len(MICRODISTRICTS),
             "h": 100, "u": 100, "w": 100, "p": 100, "v": 100}


def next_id(prefix: str) -> str:
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}{_counters[prefix]}"


def find_object(oid: str) -> CityObject | None:
    return next((o for o in OBJECTS if o.id == oid), None)
