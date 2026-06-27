"""SQLite matrix cache and routing service tests."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.application import RoutingService
from backend.app.domain.enums import RoutingPreference
from backend.app.domain.models import RoutingMatrix
from backend.app.persistence import (
    SQLiteDatabase,
    SQLiteMatrixCache,
    build_matrix_cache_key,
)
from backend.app.routing import FakeRoutingProvider, RoutingLocation, RoutingOptions


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def sample_locations() -> tuple[RoutingLocation, RoutingLocation]:
    return (
        RoutingLocation("PLANT", "Plant", 43.700001, -79.400001, "plant-place"),
        RoutingLocation("SUPPLIER", "Supplier", 43.800001, -79.500001, "supplier-place"),
    )


def sample_matrix() -> RoutingMatrix:
    return RoutingMatrix(
        location_ids=("PLANT", "SUPPLIER"),
        distance_meters=((0, 28_000), (27_000, 0)),
        duration_seconds=((0, 1_800), (1_700, 0)),
        source="fake",
    )


def cache_at(path: Path, now: datetime, *, version: str = "1") -> SQLiteMatrixCache:
    return SQLiteMatrixCache(
        SQLiteDatabase(path),
        schema_version=version,
        now=lambda: now,
    )


def test_cache_miss_then_hit_avoids_second_provider_call(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    provider = FakeRoutingProvider(matrix=sample_matrix())
    cache = cache_at(tmp_path / "matrix.db", now)
    service = RoutingService(provider, cache, now=lambda: now)

    first = run(service.compute_matrix(sample_locations(), RoutingOptions()))
    second = run(service.compute_matrix(sample_locations(), RoutingOptions()))

    assert not first.cache_hit
    assert second.cache_hit
    assert first.cache_key == second.cache_key
    assert provider.matrix_call_count == 1
    assert second.matrix == first.matrix


def test_routing_option_change_uses_new_cache_key(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    provider = FakeRoutingProvider(matrix=sample_matrix())
    service = RoutingService(provider, cache_at(tmp_path / "matrix.db", now), now=lambda: now)

    unaware = run(service.compute_matrix(sample_locations(), RoutingOptions()))
    aware = run(
        service.compute_matrix(
            sample_locations(),
            RoutingOptions(routing_preference=RoutingPreference.TRAFFIC_AWARE),
        )
    )

    assert unaware.cache_key != aware.cache_key
    assert provider.matrix_call_count == 2


def test_expired_entry_is_removed_and_recomputed(tmp_path: Path) -> None:
    clock = [datetime(2026, 6, 22, 12, tzinfo=UTC)]
    provider = FakeRoutingProvider(matrix=sample_matrix())
    cache = SQLiteMatrixCache(SQLiteDatabase(tmp_path / "matrix.db"), now=lambda: clock[0])
    service = RoutingService(
        provider,
        cache,
        cache_ttl_seconds=60,
        now=lambda: clock[0],
    )

    first = run(service.compute_matrix(sample_locations(), RoutingOptions()))
    clock[0] += timedelta(seconds=61)
    second = run(service.compute_matrix(sample_locations(), RoutingOptions()))

    assert not first.cache_hit
    assert not second.cache_hit
    assert provider.matrix_call_count == 2


def test_schema_version_change_invalidates_entry(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    path = tmp_path / "matrix.db"
    key = build_matrix_cache_key(
        provider_name="fake",
        locations=sample_locations(),
        options=RoutingOptions(),
    )
    matrix = sample_matrix().model_copy(
        update={"created_at": now, "expires_at": now + timedelta(hours=1)}
    )
    cache_at(path, now, version="1").set(key, matrix)

    assert cache_at(path, now, version="2").get(key) is None


def test_corrupt_cache_payload_is_discarded(tmp_path: Path) -> None:
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    database = SQLiteDatabase(tmp_path / "matrix.db")
    cache = SQLiteMatrixCache(database, now=lambda: now)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO route_matrix_cache (
                cache_key, schema_version, created_at, expires_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "matrix:1:corrupt",
                "1",
                now.isoformat(),
                (now + timedelta(hours=1)).isoformat(),
                "not-json",
            ),
        )

    assert cache.get("matrix:1:corrupt") is None
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM route_matrix_cache WHERE cache_key = ?",
            ("matrix:1:corrupt",),
        ).fetchone()[0]
    assert count == 0


def test_cache_key_is_order_and_departure_option_sensitive() -> None:
    first, second = sample_locations()
    base = build_matrix_cache_key(
        provider_name="google_routes",
        locations=(first, second),
        options=RoutingOptions(),
    )
    reversed_key = build_matrix_cache_key(
        provider_name="google_routes",
        locations=(second, first),
        options=RoutingOptions(),
    )
    departure_key = build_matrix_cache_key(
        provider_name="google_routes",
        locations=(first, second),
        options=RoutingOptions(departure_time=datetime(2026, 6, 22, 13, 30, tzinfo=UTC)),
    )

    assert base != reversed_key
    assert base != departure_key
    assert "google" not in base
    assert "plant-place" not in base
