"""Planner-friendly units: kilometres for distances and h:mm for durations.

The backend works in metres and seconds; forms and results show kilometres and hours.
"""

from __future__ import annotations

import re

_HMM = re.compile(r"^\s*(?P<hours>\d+):(?P<minutes>[0-5]\d)\s*$")


def meters_to_km(meters: int | float) -> float:
    return float(meters) / 1_000


def km_to_meters(kilometres: int | float) -> int:
    if kilometres < 0:
        raise ValueError("distance cannot be negative")
    return round(float(kilometres) * 1_000)


def format_km(meters: int | float | None, *, decimals: int = 1) -> str:
    if meters is None:
        return "—"
    return f"{meters_to_km(meters):,.{decimals}f} km"


def seconds_to_hmm(seconds: int | float) -> str:
    """Whole minutes as ``h:mm``, rounding to the nearest minute: 7500 -> ``2:05``."""
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    total_minutes = round(float(seconds) / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


def hmm_to_seconds(text: str) -> int:
    """Parse ``h:mm`` (minutes 00-59) into seconds: ``2:05`` -> 7500."""
    match = _HMM.fullmatch(text)
    if match is None:
        raise ValueError(f"Enter a duration as h:mm, such as 2:30 (got {text!r}).")
    return (int(match.group("hours")) * 60 + int(match.group("minutes"))) * 60
