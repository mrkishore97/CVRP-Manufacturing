"""V1.1-M1 geocode cache: hits, expiry, the 30-day ceiling, and what is stored."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.domain import GeocodeLocationType
from backend.app.domain.geocoding import GEOCODE_MAX_AGE_SECONDS, normalize_address
from backend.app.persistence import (
    SQLiteDatabase,
    SQLiteGeocodeCache,
    build_geocode_cache_key,
)
from backend.app.routing import AddressResolution, GeocodeCandidate

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
ADDRESS = "200 Supplier Avenue, Vaughan, ON"
RESOLUTION = AddressResolution(
    candidates=(
        GeocodeCandidate(
            formatted_address="200 Supplier Ave, Vaughan, ON L4K 0A1, Canada",
            latitude=43.82,
            longitude=-79.5,
            place_id="place-supplier",
            location_type=GeocodeLocationType.ROOFTOP,
        ),
        GeocodeCandidate(
            formatted_address="200 Supplier Ave W, Vaughan, ON L4L 0B2, Canada",
            latitude=43.83,
            longitude=-79.51,
            place_id="place-supplier-west",
            location_type=GeocodeLocationType.RANGE_INTERPOLATED,
            partial_match=True,
        ),
    )
)


def _key(region: str | None = "ca", provider: str = "fake") -> str:
    return build_geocode_cache_key(
        provider_name=provider,
        region_code=region,
        normalized_address=normalize_address(ADDRESS),
    )


def _cache(tmp_path: Path, **kwargs: Any) -> SQLiteGeocodeCache:
    return SQLiteGeocodeCache(SQLiteDatabase(tmp_path / "cache.db"), now=lambda: NOW, **kwargs)


def _rows(tmp_path: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(tmp_path / "cache.db") as connection:
        return list(connection.execute("SELECT * FROM geocode_cache"))


def test_cache_key_varies_by_provider_region_and_address_but_hides_the_address() -> None:
    key = _key()

    assert key.startswith("geocode:1:")
    assert "supplier" not in key.lower()
    assert key != _key(region=None)
    assert key != _key(provider="google_routes")
    assert key != build_geocode_cache_key(
        provider_name="fake", region_code="ca", normalized_address="other address"
    )


def test_miss_then_hit_round_trips_every_candidate(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    assert cache.get(_key()) is None
    stored = cache.set(_key(), RESOLUTION, fetched_at=NOW - timedelta(hours=1))
    cached = cache.get(_key())

    assert cached is not None
    assert cached.resolution == RESOLUTION
    assert cached.fetched_at == NOW - timedelta(hours=1)
    assert cached.expires_at == stored.expires_at == NOW - timedelta(hours=1) + timedelta(days=30)


def test_entry_expires_at_the_ttl(tmp_path: Path) -> None:
    cache = _cache(tmp_path, ttl_seconds=86_400)
    cache.set(_key(), RESOLUTION, fetched_at=NOW)

    assert cache.get(_key(), now=NOW + timedelta(hours=23)) is not None
    assert cache.get(_key(), now=NOW + timedelta(days=1)) is None
    assert _rows(tmp_path) == []


def test_lowered_ttl_applies_to_rows_written_under_a_longer_one(tmp_path: Path) -> None:
    _cache(tmp_path).set(_key(), RESOLUTION, fetched_at=NOW - timedelta(days=5))

    assert _cache(tmp_path).get(_key()) is not None
    assert _cache(tmp_path, ttl_seconds=2 * 86_400).get(_key()) is None


@pytest.mark.parametrize("ttl_seconds", [GEOCODE_MAX_AGE_SECONDS + 1, 0, -1])
def test_cache_refuses_a_ttl_outside_one_second_to_thirty_days(
    tmp_path: Path, ttl_seconds: int
) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        _cache(tmp_path, ttl_seconds=ttl_seconds)


def test_settings_refuse_a_ttl_above_thirty_days() -> None:
    too_long: dict[str, Any] = {
        "_env_file": None,
        "GEOCODE_CACHE_TTL_SECONDS": GEOCODE_MAX_AGE_SECONDS + 1,
    }
    defaults: dict[str, Any] = {"_env_file": None}

    with pytest.raises(ValidationError, match="less than or equal to 2592000"):
        Settings(**too_long)

    assert Settings(**defaults).geocode_cache_ttl_seconds == GEOCODE_MAX_AGE_SECONDS


def test_not_found_results_are_not_cached(tmp_path: Path) -> None:
    cache = _cache(tmp_path)

    with pytest.raises(ValueError, match="not cached"):
        cache.set(_key(), AddressResolution(), fetched_at=NOW)
    assert _rows(tmp_path) == []


def test_purge_removes_only_expired_rows(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.set(_key(), RESOLUTION, fetched_at=NOW - timedelta(days=31))
    cache.set(_key(region=None), RESOLUTION, fetched_at=NOW - timedelta(days=1))

    assert cache.purge_expired() == 1
    assert cache.get(_key(region=None)) is not None
    assert len(_rows(tmp_path)) == 1


def test_rows_from_another_schema_version_are_dropped(tmp_path: Path) -> None:
    _cache(tmp_path, schema_version="0").set(_key(), RESOLUTION, fetched_at=NOW)

    assert _cache(tmp_path).get(_key()) is None
    assert _rows(tmp_path) == []


def test_unreadable_rows_are_discarded(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.set(_key(), RESOLUTION, fetched_at=NOW)
    with sqlite3.connect(tmp_path / "cache.db") as connection:
        connection.execute("UPDATE geocode_cache SET payload_json = '[{\"latitude\": 1}]'")

    assert cache.get(_key()) is None
    assert _rows(tmp_path) == []


def test_rows_hold_no_address_text(tmp_path: Path) -> None:
    _cache(tmp_path).set(_key(), RESOLUTION, fetched_at=NOW)

    stored = repr(_rows(tmp_path)).lower()
    assert normalize_address(ADDRESS) not in stored
    assert "200 supplier avenue" not in stored
