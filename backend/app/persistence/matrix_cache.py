"""Versioned SQLite route-matrix cache and deterministic cache keys."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import ValidationError

from backend.app.domain.models import RoutingMatrix
from backend.app.persistence.database import SQLiteDatabase
from backend.app.routing.base import RoutingLocation, RoutingOptions

LOGGER = logging.getLogger(__name__)
MATRIX_CACHE_SCHEMA_VERSION = "1"
NowFunction = Callable[[], datetime]


def _departure_bucket(
    value: datetime | None,
    bucket_minutes: int,
) -> str | None:
    if value is None:
        return None
    if bucket_minutes <= 0:
        raise ValueError("bucket_minutes must be positive")
    utc_value = value.astimezone(UTC)
    bucket_seconds = bucket_minutes * 60
    epoch_seconds = int(utc_value.timestamp())
    bucket_start = epoch_seconds - (epoch_seconds % bucket_seconds)
    return datetime.fromtimestamp(bucket_start, tz=UTC).isoformat()


def build_matrix_cache_key(
    *,
    provider_name: str,
    locations: Sequence[RoutingLocation],
    options: RoutingOptions,
    departure_bucket_minutes: int = 60,
    schema_version: str = MATRIX_CACHE_SCHEMA_VERSION,
) -> str:
    """Hash ordered coordinates and routing options without including secrets."""
    if not provider_name.strip():
        raise ValueError("provider_name is required")
    if not locations:
        raise ValueError("locations are required")
    payload = {
        "schema_version": schema_version,
        "provider": provider_name,
        "locations": [
            {
                "location_id": location.location_id,
                "place_id": location.place_id,
                "latitude": round(location.latitude, 6),
                "longitude": round(location.longitude, 6),
            }
            for location in locations
        ],
        "travel_mode": options.travel_mode.value,
        "routing_preference": options.routing_preference.value,
        "departure_bucket": _departure_bucket(
            options.departure_time,
            departure_bucket_minutes,
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"matrix:{schema_version}:{digest}"


class SQLiteMatrixCache:
    """Persist complete validated matrices with schema and expiry checks."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        schema_version: str = MATRIX_CACHE_SCHEMA_VERSION,
        now: NowFunction | None = None,
    ) -> None:
        self._database = database
        self._schema_version = schema_version
        self._now = now or (lambda: datetime.now(UTC))
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS route_matrix_cache (
                    cache_key TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def get(self, cache_key: str, *, now: datetime | None = None) -> RoutingMatrix | None:
        """Return an unexpired compatible matrix or treat the entry as a miss."""
        current_time = (now or self._now()).astimezone(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT schema_version, expires_at, payload_json
                FROM route_matrix_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            schema_version, expires_at_text, payload_json = row
            try:
                expires_at = datetime.fromisoformat(expires_at_text).astimezone(UTC)
            except (TypeError, ValueError):
                LOGGER.warning("Discarding matrix cache entry with invalid expiry")
                connection.execute(
                    "DELETE FROM route_matrix_cache WHERE cache_key = ?", (cache_key,)
                )
                return None
            if schema_version != self._schema_version or expires_at <= current_time:
                connection.execute(
                    "DELETE FROM route_matrix_cache WHERE cache_key = ?", (cache_key,)
                )
                return None
            try:
                matrix = RoutingMatrix.model_validate_json(payload_json)
            except (ValidationError, ValueError):
                LOGGER.warning("Discarding invalid matrix cache payload")
                connection.execute(
                    "DELETE FROM route_matrix_cache WHERE cache_key = ?", (cache_key,)
                )
                return None
            if matrix.expires_at is None or matrix.expires_at <= current_time:
                connection.execute(
                    "DELETE FROM route_matrix_cache WHERE cache_key = ?", (cache_key,)
                )
                return None
            return matrix

    def set(self, cache_key: str, matrix: RoutingMatrix) -> None:
        """Atomically insert or replace one complete matrix."""
        if matrix.created_at is None or matrix.expires_at is None:
            raise ValueError("cached matrix requires created_at and expires_at")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO route_matrix_cache (
                    cache_key, schema_version, created_at, expires_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    payload_json = excluded.payload_json
                """,
                (
                    cache_key,
                    self._schema_version,
                    matrix.created_at.astimezone(UTC).isoformat(),
                    matrix.expires_at.astimezone(UTC).isoformat(),
                    matrix.model_dump_json(),
                ),
            )

    def purge_source(self, source: str) -> int:
        """Delete every row whose matrix came from ``source``; returns the count.

        Used at start-up to remove Google matrices cached by Version 1.0 (decision D6).
        """
        removed = 0
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT cache_key, payload_json FROM route_matrix_cache"
            ).fetchall()
            for cache_key, payload_json in rows:
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    payload = None
                if not isinstance(payload, dict) or payload.get("source") == source:
                    connection.execute(
                        "DELETE FROM route_matrix_cache WHERE cache_key = ?", (cache_key,)
                    )
                    removed += 1
        return removed

    def clear_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired rows and return the number removed."""
        current_time = (now or self._now()).astimezone(UTC).isoformat()
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM route_matrix_cache WHERE expires_at <= ?", (current_time,)
            )
            return max(0, cursor.rowcount)
