"""Google adapter plus SQLite cache integration tests with mocked HTTP."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from backend.app.application import RoutingService
from backend.app.persistence import SQLiteDatabase, SQLiteMatrixCache
from backend.app.routing import GoogleRoutingProvider, RoutingLocation, RoutingOptions


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_google_matrices_are_never_cached_decision_d6(tmp_path: Path) -> None:
    """Changed in V1.1-M3 by decision D6 (plan §4).

    Version 1.0 asserted that the second identical request was a cache hit with one
    HTTP call. Google matrices are no longer stored, so both requests call Google and
    the cache table stays empty.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload: dict[str, Any] = json.loads(request.content)
        elements = []
        for origin_index, _origin in enumerate(payload["origins"]):
            for destination_index, _destination in enumerate(payload["destinations"]):
                diagonal = origin_index == destination_index
                elements.append(
                    {
                        "originIndex": origin_index,
                        "destinationIndex": destination_index,
                        "status": {},
                        "condition": "ROUTE_EXISTS",
                        "distanceMeters": 0 if diagonal else 1_000,
                        "duration": "0s" if diagonal else "100s",
                    }
                )
        return httpx.Response(200, json=elements)

    provider = GoogleRoutingProvider(
        api_key="mock-secret",
        routes_matrix_url="https://google.test/matrix",
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    cache = SQLiteMatrixCache(SQLiteDatabase(tmp_path / "matrix.db"), now=lambda: now)
    service = RoutingService(provider, cache, now=lambda: now)
    locations = (
        RoutingLocation("A", "A", 43.0, -79.0),
        RoutingLocation("B", "B", 44.0, -80.0),
    )

    estimate = service.estimate_matrix(locations, RoutingOptions())
    first = run(service.compute_matrix(locations, RoutingOptions()))
    second = run(service.compute_matrix(locations, RoutingOptions()))

    assert not estimate.cache_enabled
    assert not estimate.cache_hit
    assert not first.cache_hit
    assert not second.cache_hit
    assert not first.cache_enabled
    assert calls == 2
    assert first.matrix.source == "google_routes"
    assert first.matrix.expires_at is None
    assert second.matrix.distance_meters == first.matrix.distance_meters
    assert cache.get(first.cache_key, now=now) is None
    with SQLiteDatabase(tmp_path / "matrix.db").connect() as connection:
        rows = connection.execute("SELECT COUNT(*) FROM route_matrix_cache").fetchone()
    assert rows[0] == 0
