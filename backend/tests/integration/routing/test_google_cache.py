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


def test_cache_hit_prevents_second_google_http_call(tmp_path: Path) -> None:
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

    first = run(service.compute_matrix(locations, RoutingOptions()))
    second = run(service.compute_matrix(locations, RoutingOptions()))

    assert not first.cache_hit
    assert second.cache_hit
    assert calls == 1
    assert second.matrix == first.matrix
