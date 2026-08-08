"""Генерация логина и временного пароля для новых пользователей."""
from __future__ import annotations

import os
import re

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


def temp_password(seed: str) -> str:
    tail = re.sub(r"\D", "", seed)[-4:].rjust(4, "0")
    return f"UC-{tail}-{seed[-2:].rjust(2, '0')}"


# Пароль супер-админа платформы. В production задаётся через переменную окружения
# PLATFORM_SUPERADMIN_PASSWORD (config.validate_production_settings требует её и
# запрещает демо-значение). Демо-строка — только для локальной разработки.
DEMO_SUPERADMIN_PASSWORD = "Urb4n-SA-2026!"
PLATFORM_SUPERADMIN_PASSWORD = os.getenv("PLATFORM_SUPERADMIN_PASSWORD") or DEMO_SUPERADMIN_PASSWORD
PLATFORM_SUPERADMIN_LOGIN = "platform.admin"
PLATFORM_SUPERADMIN_EMAIL = "platform.admin@urban-city.kz"
