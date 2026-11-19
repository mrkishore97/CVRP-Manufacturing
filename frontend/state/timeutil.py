"""Local wall-clock text for forms and plant-local display of backend UTC times.

Forms store local wall-clock text without an offset (``2026-06-22T07:00:00``); the
backend applies the plant timezone and rejects ambiguous or non-existent
daylight-saving times. The frontend only converts backend UTC results to plant-local
time for display, so time-zone rules live in one place. The helpers that go the other
way exist for display, round-trip checks, and warning the planner early.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo


class WallClockStatus(StrEnum):
    OK = "OK"
    AMBIGUOUS = "AMBIGUOUS"  # happens twice when clocks go back
    NONEXISTENT = "NONEXISTENT"  # skipped when clocks go forward


def wall_clock_text(day: date, clock: time) -> str:
    """Offset-free local text as stored by forms: ``2026-06-22T07:00:00``."""
    return datetime.combine(day, clock.replace(tzinfo=None, microsecond=0)).isoformat()


def parse_datetime_text(text: str) -> datetime:
    """Parse ISO text; ``Z`` is accepted. The result may be naive or aware."""
    value = text.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def to_local(value: str | datetime, timezone: str) -> datetime:
    """Plant-local aware time; naive input is taken to be plant-local already."""
    parsed = parse_datetime_text(value) if isinstance(value, str) else value
    zone = ZoneInfo(timezone)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def format_local(value: str | datetime | None, timezone: str) -> str:
    """Planner display: ``2026-06-22 07:00 EDT``."""
    if value is None or value == "":
        return "—"
    return to_local(value, timezone).strftime("%Y-%m-%d %H:%M %Z")


def local_iso(value: str | datetime, timezone: str) -> str:
    """Plant-local ISO text with its offset, which identifies the instant exactly."""
    return to_local(value, timezone).isoformat()


def wall_clock_status(text: str, timezone: str) -> WallClockStatus:
    """Whether an offset-free local time is valid, ambiguous, or skipped by DST."""
    naive = parse_datetime_text(text)
    if naive.tzinfo is not None:
        return WallClockStatus.OK
    zone = ZoneInfo(timezone)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return WallClockStatus.OK
    round_trip = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        return WallClockStatus.NONEXISTENT
    return WallClockStatus.AMBIGUOUS


def local_to_utc(text: str, timezone: str) -> datetime:
    """UTC instant for local text; offset-free ambiguous or skipped times are refused."""
    parsed = parse_datetime_text(text)
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed.astimezone(UTC)
    status = wall_clock_status(text, timezone)
    if status is not WallClockStatus.OK:
        raise ValueError(
            f"{text} is {status.value.lower()} in {timezone} because of a daylight-saving "
            "change; add an explicit UTC offset."
        )
    return parsed.replace(tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def split_for_form(value: str, timezone: str) -> tuple[date, time]:
    """Date and time pickers' values for stored text, shown in plant-local time."""
    local = to_local(value, timezone)
    return local.date(), local.time().replace(tzinfo=None, microsecond=0)
