"""Strict timezone and date-only normalization utilities."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.domain.enums import ValidationCode

DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DateTimeInput = datetime | date | str


class DateTimeNormalizationError(ValueError):
    """A datetime could not be normalized without guessing."""

    def __init__(self, code: ValidationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def get_timezone(timezone_name: str) -> ZoneInfo:
    """Return an IANA timezone or a stable validation error."""
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DateTimeNormalizationError(
            ValidationCode.INVALID_TIMEZONE,
            f"Unknown IANA timezone: {timezone_name}",
        ) from exc


def localize_strict(value: datetime, timezone: ZoneInfo) -> datetime:
    """Attach a timezone while rejecting ambiguous/nonexistent local wall times."""
    if value.tzinfo is not None:
        return value.astimezone(timezone)

    candidates: dict[object, datetime] = {}
    for fold in (0, 1):
        candidate = value.replace(tzinfo=timezone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
        if round_trip == value:
            candidates[candidate.utcoffset()] = candidate

    if not candidates:
        raise DateTimeNormalizationError(
            ValidationCode.NONEXISTENT_LOCAL_TIME,
            f"Local time does not exist in {timezone.key}: {value.isoformat()}",
        )
    if len(candidates) > 1:
        raise DateTimeNormalizationError(
            ValidationCode.AMBIGUOUS_LOCAL_TIME,
            f"Local time is ambiguous in {timezone.key}: {value.isoformat()}",
        )
    return next(iter(candidates.values()))


def parse_datetime_input(value: DateTimeInput) -> datetime | date:
    """Parse accepted input types without applying timezone assumptions."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise DateTimeNormalizationError(
            ValidationCode.INVALID_DATETIME,
            "Datetime value must be a non-empty ISO string, date, or datetime.",
        )

    normalized = value.strip()
    if DATE_ONLY_PATTERN.fullmatch(normalized):
        try:
            return date.fromisoformat(normalized)
        except ValueError as exc:
            raise DateTimeNormalizationError(
                ValidationCode.INVALID_DATETIME,
                f"Invalid calendar date: {normalized}",
            ) from exc

    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DateTimeNormalizationError(
            ValidationCode.INVALID_DATETIME,
            f"Invalid ISO datetime: {value}",
        ) from exc


def normalize_datetime(
    value: DateTimeInput,
    timezone_name: str,
    *,
    date_boundary: datetime | None = None,
) -> datetime:
    """Normalize a datetime to UTC, using an explicit shift boundary for a date."""
    timezone = get_timezone(timezone_name)
    parsed = parse_datetime_input(value)

    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        if date_boundary is None:
            raise DateTimeNormalizationError(
                ValidationCode.DATE_ONLY_REQUIRES_SHIFT,
                f"Date-only value {parsed.isoformat()} requires an applicable truck shift.",
            )
        boundary_local = date_boundary.astimezone(timezone)
        if boundary_local.date() != parsed:
            raise DateTimeNormalizationError(
                ValidationCode.DATE_ONLY_REQUIRES_SHIFT,
                f"No applicable shift boundary exists on {parsed.isoformat()}.",
            )
        return boundary_local.astimezone(UTC)

    assert isinstance(parsed, datetime)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = localize_strict(parsed, timezone)
    return parsed.astimezone(UTC)


def display_in_timezone(value: datetime, timezone_name: str) -> datetime:
    """Convert an aware internal datetime to the plant timezone for display."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Internal datetime must be timezone-aware")
    return value.astimezone(get_timezone(timezone_name))
