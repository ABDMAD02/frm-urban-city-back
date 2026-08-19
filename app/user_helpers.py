"""Генерация логина и временного пароля для новых пользователей."""
from __future__ import annotations

import os
import re
import secrets

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "қ": "q", "ә": "a", "і": "i", "ң": "n", "ғ": "g", "ү": "u", "ұ": "u",
    "һ": "h", "ө": "o",
}


def _translit(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif re.match(r"[a-z0-9]", ch):
            out.append(ch)
    return "".join(out)


def login_for(name: str) -> str:
    parts = name.strip().split()
    first = _translit(parts[0]) if parts else "user"
    first = first or "user"
    last = _translit(parts[1]) if len(parts) > 1 else ""
    return f"{first[0]}.{last}" if last else first


def unique_login(base: str, taken) -> str:
    """Разрешение коллизии логина: base, base2, base3… пока не занято.

    Логины уникальны глобально (в т.ч. между городами), а генератор из имени
    легко даёт совпадения (``t.testov`` у админа другого города). ``taken`` —
    предикат ``login -> bool`` (True = занят). Без этого ``POST /owners`` падал
    на уникальном ограничении логина и оператор читал это как «дубль БИН».
    """
    if not taken(base):
        return base
    for n in range(2, 1000):
        candidate = f"{base}{n}"
        if not taken(candidate):
            return candidate
    raise RuntimeError(f"не удалось подобрать уникальный логин для «{base}»")


def temp_password(seed: str) -> str:
    """Детерминированный демо-пароль по коду. ТОЛЬКО для сид-данных (демо-логины).

    Предсказуем по коду (u2 → UC-0002-u2), поэтому для операционного создания и
    сброса паролей использовать random_temp_password() — см. находку C2 аудита.
    """
    tail = re.sub(r"\D", "", seed)[-4:].rjust(4, "0")
    return f"UC-{tail}-{seed[-2:].rjust(2, '0')}"


# Алфавит без похожих символов (0/O, 1/I) — человекочитаемо при диктовке.
_TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def random_temp_password() -> str:
    """Непредсказуемый временный пароль формата UC-XXXX-YYYY.

    Для реального создания/сброса учётных записей: пароль нельзя вычислить из
    логина или последовательного кода пользователя.
    """
    block = lambda: "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(4))
    return f"UC-{block()}-{block()}"


# Пароль супер-админа платформы. В production задаётся через переменную окружения
# PLATFORM_SUPERADMIN_PASSWORD (config.validate_production_settings требует её и
# запрещает демо-значение). Демо-строка — только для локальной разработки.
DEMO_SUPERADMIN_PASSWORD = "Urb4n-SA-2026!"
PLATFORM_SUPERADMIN_PASSWORD = os.getenv("PLATFORM_SUPERADMIN_PASSWORD") or DEMO_SUPERADMIN_PASSWORD
PLATFORM_SUPERADMIN_LOGIN = "platform.admin"
PLATFORM_SUPERADMIN_EMAIL = "platform.admin@urban-city.kz"
