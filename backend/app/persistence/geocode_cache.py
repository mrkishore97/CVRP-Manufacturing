"""SQLite address-resolution cache bounded by Google's 30-day coordinate limit.

Rows are keyed by a hash of provider, region bias, normalised address, and schema
version. They hold the parsed candidates and timestamps only: no address text, no
API key, and no raw provider payload. Not-found answers are never stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.domain.enums import GeocodeLocationType
from backend.app.domain.geocoding import GEOCODE_MAX_AGE_SECONDS
from backend.app.persistence.database import SQLiteDatabase
from backend.app.routing.base import AddressResolution, GeocodeCandidate

LOGGER = logging.getLogger(__name__)
GEOCODE_CACHE_SCHEMA_VERSION = "1"
NowFunction = Callable[[], datetime]
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _timestamp(value: datetime) -> str:
    """Fixed-width UTC text, so SQL string comparison orders timestamps correctly."""
    return value.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def build_geocode_cache_key(
    *,
    provider_name: str,
    region_code: str | None,
    normalized_address: str,
    schema_version: str = GEOCODE_CACHE_SCHEMA_VERSION,
) -> str:
    """Hash the lookup inputs; the address itself never appears in the key."""
    if not provider_name.strip():
        raise ValueError("provider_name is required")
    if not normalized_address:
        raise ValueError("normalized_address is required")
    canonical = json.dumps(
        {
            "schema_version": schema_version,
            "provider": provider_name,
            "region": region_code or "",
            "address": normalized_address,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"geocode:{schema_version}:{digest}"


@dataclass(frozen=True, slots=True)
class CachedResolution:
    """A cached resolution and when the provider originally returned it."""

    resolution: AddressResolution
    fetched_at: datetime
    expires_at: datetime


def _candidate_to_json(candidate: GeocodeCandidate) -> dict[str, Any]:
    return {
        "formatted_address": candidate.formatted_address,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "place_id": candidate.place_id,
        "location_type": candidate.location_type.value if candidate.location_type else None,
        "partial_match": candidate.partial_match,
    }


def _candidate_from_json(value: Any) -> GeocodeCandidate:
    if not isinstance(value, dict):
        raise ValueError("cached candidate must be an object")
    formatted_address = value["formatted_address"]
    latitude = value["latitude"]
    longitude = value["longitude"]
    place_id = value.get("place_id")
    location_type = value.get("location_type")
    if not isinstance(formatted_address, str) or not formatted_address:
        raise ValueError("cached candidate needs a formatted address")
    if not isinstance(latitude, int | float) or not isinstance(longitude, int | float):
        raise ValueError("cached candidate needs numeric coordinates")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("cached candidate coordinates are out of range")
    return GeocodeCandidate(
        formatted_address=formatted_address,
        latitude=float(latitude),
        longitude=float(longitude),
        place_id=place_id if isinstance(place_id, str) else None,
        location_type=GeocodeLocationType(location_type) if location_type else None,
        partial_match=value.get("partial_match") is True,
    )


class SQLiteGeocodeCache:
    """Persist found address resolutions for at most 30 days."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        ttl_seconds: int = GEOCODE_MAX_AGE_SECONDS,
        schema_version: str = GEOCODE_CACHE_SCHEMA_VERSION,
        now: NowFunction | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if ttl_seconds > GEOCODE_MAX_AGE_SECONDS:
            raise ValueError(
                "ttl_seconds cannot exceed 30 days; Google limits how long "
                "geocoded coordinates may be cached"
            )
        self._database = database
        self._ttl = timedelta(seconds=ttl_seconds)
        self._schema_version = schema_version
        self._now = now or (lambda: datetime.now(UTC))
        self._initialize()

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    cache_key TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def get(self, cache_key: str, *, now: datetime | None = None) -> CachedResolution | None:
        """Return an unexpired, compatible entry; anything else is deleted and missed."""
        current_time = (now or self._now()).astimezone(UTC)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT schema_version, fetched_at, expires_at, payload_json
                FROM geocode_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            schema_version, fetched_text, expires_text, payload_json = row
            try:
                fetched_at = _parse_timestamp(fetched_text)
                stored_expiry = _parse_timestamp(expires_text)
                candidates = tuple(_candidate_from_json(item) for item in json.loads(payload_json))
            except (KeyError, TypeError, ValueError):
                LOGGER.warning("Discarding an unreadable geocode cache entry")
                connection.execute("DELETE FROM geocode_cache WHERE cache_key = ?", (cache_key,))
                return None
            # A lowered TTL applies to rows written under the old, longer one.
            expires_at = min(stored_expiry, fetched_at + self._ttl)
            if (
                schema_version != self._schema_version
                or not candidates
                or expires_at <= current_time
            ):
                connection.execute("DELETE FROM geocode_cache WHERE cache_key = ?", (cache_key,))
                return None
            return CachedResolution(
                resolution=AddressResolution(candidates=candidates),
                fetched_at=fetched_at,
                expires_at=expires_at,
            )

    def set(
        self,
        cache_key: str,
        resolution: AddressResolution,
        *,
        fetched_at: datetime,
    ) -> CachedResolution:
        """Store a found resolution; not-found answers are refused."""
        if not resolution.found:
            raise ValueError("not-found address resolutions are not cached")
        fetched_at = fetched_at.astimezone(UTC)
        expires_at = fetched_at + self._ttl
        payload_json = json.dumps(
            [_candidate_to_json(candidate) for candidate in resolution.candidates],
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO geocode_cache (
                    cache_key, schema_version, fetched_at, expires_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    payload_json = excluded.payload_json
                """,
                (
                    cache_key,
                    self._schema_version,
                    _timestamp(fetched_at),
                    _timestamp(expires_at),
                    payload_json,
                ),
            )
        return CachedResolution(
            resolution=resolution,
            fetched_at=fetched_at,
            expires_at=expires_at,
        )

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired or incompatible rows and return how many were removed."""
        current_time = (now or self._now()).astimezone(UTC)
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM geocode_cache
                WHERE expires_at <= ? OR fetched_at <= ? OR schema_version != ?
                """,
                (
                    _timestamp(current_time),
                    _timestamp(current_time - self._ttl),
                    self._schema_version,
                ),
            )
            return max(0, cursor.rowcount)
