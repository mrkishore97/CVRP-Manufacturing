"""What the backend may keep, under the Google terms decisions (plan §4, D2 and D6).

Decision D6: Google Routes distances and durations are not stored outside the request
that produced them. The matrix cache does not keep them (``RoutingService``), saved
scenarios and drafts drop them, and anything Version 1.0 stored is removed at start-up.
Matrices from JSON fixtures or the offline fake provider carry no such terms.

Decision D2 (plan §8.6): coordinates found by address resolution may be kept for 30
days. Older ones are stripped from saved scenarios and drafts when they are loaded and
by a sweep at start-up. The address, place ID, and confirmation stay, so resolving
again is one click.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.enums import GeocodeStatus
from backend.app.domain.geocoding import geocode_is_expired
from backend.app.persistence.database import SQLiteDatabase
from backend.app.persistence.matrix_cache import SQLiteMatrixCache
from backend.app.persistence.scenario_repository import (
    SQLiteDraftRepository,
    SQLiteScenarioRepository,
)

LOGGER = logging.getLogger(__name__)

EXPIRING_LOCATION_FIELDS = (
    "latitude",
    "longitude",
    "formatted_address",
    "geocoded_at",
    "geocode_source_fingerprint",
    "geocode_location_type",
    "geocode_partial_match",
    "geocode_warning",
)
"""Fields that came with the coordinates and go with them; ``place_id`` may be kept."""

GOOGLE_MATRIX_SOURCE = "google_routes"
"""``GoogleRoutingProvider.provider_name``, stamped on every matrix it returns."""

UNSTORABLE_MATRIX_SOURCES = frozenset({GOOGLE_MATRIX_SOURCE})

JsonObject = dict[str, Any]


def matrix_is_storable(matrix: Any) -> bool:
    """Whether a matrix payload may be kept; Google matrices may not (D6)."""
    if not isinstance(matrix, Mapping):
        return True
    return str(matrix.get("source", "")) not in UNSTORABLE_MATRIX_SOURCES


def without_unstorable_matrix(payload: Mapping[str, Any]) -> tuple[JsonObject, bool]:
    """The payload without an embedded Google matrix, and whether one was removed."""
    copied = deepcopy(dict(payload))
    matrix = copied.get("routing_matrix")
    if matrix is not None and not matrix_is_storable(matrix):
        del copied["routing_matrix"]
        return copied, True
    return copied, False


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def location_coordinates_expired(
    location: Mapping[str, Any], *, now: datetime, max_age_seconds: int
) -> bool:
    """Whether a location holds resolved coordinates past the retention limit.

    Coordinates supplied in JSON (no ``geocoded_at`` and no provenance fingerprint) are
    the planner's own and never expire. Resolved coordinates whose age cannot be read
    are treated as expired, as validation and the app already do.
    """
    if location.get("latitude") is None and location.get("longitude") is None:
        return False
    raw = location.get("geocoded_at")
    if raw is None:
        return location.get("geocode_source_fingerprint") is not None
    geocoded_at = _parse_time(raw)
    if geocoded_at is None or geocoded_at.tzinfo is None:
        return True
    return geocode_is_expired(geocoded_at.astimezone(UTC), now, max_age_seconds)


def strip_expired_coordinates(
    payload: Mapping[str, Any], *, now: datetime, max_age_seconds: int
) -> tuple[JsonObject, int]:
    """The payload without coordinates older than the limit, and how many were removed.

    A stripped location keeps its address, place ID, and confirmation, and its status
    returns to ``PENDING``, so the app offers to resolve it again.
    """
    copied = deepcopy(dict(payload))
    locations = copied.get("locations")
    if not isinstance(locations, list):
        return copied, 0
    removed = 0
    for location in locations:
        if not isinstance(location, dict):
            continue
        if not location_coordinates_expired(location, now=now, max_age_seconds=max_age_seconds):
            continue
        for field in EXPIRING_LOCATION_FIELDS:
            location.pop(field, None)
        if location.get("geocode_status") in (
            GeocodeStatus.RESOLVED.value,
            GeocodeStatus.NEEDS_REVIEW.value,
        ):
            location["geocode_status"] = GeocodeStatus.PENDING.value
        removed += 1
    return copied, removed


@dataclass(frozen=True, slots=True)
class RetentionSweep:
    """What the start-up sweep removed."""

    cached_matrices_removed: int
    scenarios_cleaned: int
    drafts_cleaned: int = 0


def sweep_unstorable_matrices(database: SQLiteDatabase) -> RetentionSweep:
    """Remove Google matrices from the matrix cache, saved scenarios, and drafts."""
    cache = SQLiteMatrixCache(database)
    removed = sum(cache.purge_source(source) for source in sorted(UNSTORABLE_MATRIX_SOURCES))
    cleaned = SQLiteScenarioRepository(database).rewrite_payloads(_strip_for_sweep)
    drafts = SQLiteDraftRepository(database).rewrite_payloads(_strip_for_sweep)
    if removed or cleaned or drafts:
        LOGGER.info(
            "Removed %s cached Google matrices and Google matrices from %s saved scenarios "
            "and %s drafts",
            removed,
            cleaned,
            drafts,
        )
    return RetentionSweep(
        cached_matrices_removed=removed, scenarios_cleaned=cleaned, drafts_cleaned=drafts
    )


@dataclass(frozen=True, slots=True)
class CoordinateSweep:
    """How many saved scenarios and drafts had expired coordinates removed at start-up."""

    scenarios_cleaned: int
    drafts_cleaned: int


def sweep_expired_coordinates(
    database: SQLiteDatabase, *, max_age_seconds: int, now: datetime | None = None
) -> CoordinateSweep:
    """Strip coordinates past the retention limit from saved scenarios and drafts."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    def transform(payload: JsonObject) -> JsonObject | None:
        stripped, removed = strip_expired_coordinates(
            payload, now=moment, max_age_seconds=max_age_seconds
        )
        return stripped if removed else None

    scenarios = SQLiteScenarioRepository(database).rewrite_payloads(transform)
    drafts = SQLiteDraftRepository(database).rewrite_payloads(transform)
    if scenarios or drafts:
        LOGGER.info(
            "Removed expired coordinates from %s saved scenarios and %s drafts",
            scenarios,
            drafts,
        )
    return CoordinateSweep(scenarios_cleaned=scenarios, drafts_cleaned=drafts)


def _strip_for_sweep(payload: JsonObject) -> JsonObject | None:
    stripped, removed = without_unstorable_matrix(payload)
    return stripped if removed else None
