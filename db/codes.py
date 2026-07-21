"""Публичный строковый id (o1, u1, …) для совместимости с API и фронтом."""
from __future__ import annotations

import uuid

# Фиксированный namespace — детерминированные UUID для сид-данных.
NS = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def uuid_for_code(code: str) -> uuid.UUID:
    return uuid.uuid5(NS, code)
