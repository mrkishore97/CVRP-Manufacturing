"""Identifier suggestion and uniqueness, matching the backend ID rules.

Backend identifiers must match ``^[A-Za-z0-9][A-Za-z0-9._:-]*$`` and be at most 120
characters. Planners should not have to invent IDs, so these helpers suggest one from
a name and keep it unique.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date

MAX_ID_LENGTH = 120
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_NOT_ALLOWED = re.compile(r"[^A-Z0-9]+")
_TASK_NUMBER = re.compile(r"^TASK-(\d+)$")


def is_valid_id(value: str) -> bool:
    """Whether ``value`` is accepted by the backend as an identifier."""
    return bool(value) and len(value) <= MAX_ID_LENGTH and bool(ID_PATTERN.fullmatch(value))


def slugify_id(name: str, *, fallback: str = "ITEM") -> str:
    """Turn a display name into an upper-case ID: ``"Acme Steel Ltd."`` -> ``ACME-STEEL-LTD``."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _NOT_ALLOWED.sub("-", ascii_text.upper()).strip("-")
    if not slug:
        slug = fallback
    return slug[:MAX_ID_LENGTH].rstrip("-") or fallback


def unique_id(base: str, existing: Iterable[str]) -> str:
    """Return ``base``, or ``base-2``, ``base-3``… whichever is not taken (case-insensitive)."""
    taken = {value.casefold() for value in existing}
    if base.casefold() not in taken:
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: MAX_ID_LENGTH - len(suffix)]}{suffix}"
        if candidate.casefold() not in taken:
            return candidate
        counter += 1


def suggest_scenario_id(name: str) -> str:
    return slugify_id(name, fallback="SCENARIO")


def suggest_location_id(name: str, existing: Iterable[str]) -> str:
    return unique_id(slugify_id(name, fallback="LOCATION"), existing)


def suggest_vehicle_id(name: str, existing: Iterable[str]) -> str:
    return unique_id(slugify_id(name, fallback="TRUCK"), existing)


def suggest_shift_id(vehicle_id: str, shift_date: date, existing: Iterable[str]) -> str:
    """Vehicle ID plus date, the fixture convention: ``TRUCK-1-20260622``."""
    return unique_id(f"{vehicle_id}-{shift_date:%Y%m%d}", existing)


def suggest_task_id(existing: Iterable[str]) -> str:
    """Next running number after the highest ``TASK-NNNN``: ``TASK-0007``."""
    existing_ids = list(existing)
    highest = 0
    for value in existing_ids:
        match = _TASK_NUMBER.fullmatch(value)
        if match:
            highest = max(highest, int(match.group(1)))
    return unique_id(f"TASK-{highest + 1:04d}", existing_ids)
