"""M9 release-hardening regression tests."""

from __future__ import annotations

import json
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.application import RoutingService
from backend.app.config import Settings
from backend.app.domain import validate_planning_payload
from backend.app.domain.models import RoutingMatrix
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig
from backend.app.persistence import SQLiteDatabase, SQLiteMatrixCache
from backend.app.routing import FakeRoutingProvider, RoutingLocation, RoutingOptions
from backend.tests.fixtures.canonical import planning_payload


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(awaitable)


def _settings(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "m9.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    values.update(updates)
    return Settings(**values)


def _large_locations(count: int) -> tuple[RoutingLocation, ...]:
    return tuple(
        RoutingLocation(
            location_id=f"LOC-{index:02d}",
            formatted_address=f"{index} Fixture Road",
            latitude=43.0 + (index * 0.01),
            longitude=-79.0 - (index * 0.01),
            place_id=f"place-{index:02d}",
        )
        for index in range(count)
    )


def _large_matrix(count: int) -> RoutingMatrix:
    distances = tuple(
        tuple(
            0 if origin == destination else 1_000 + abs(origin - destination)
            for destination in range(count)
        )
        for origin in range(count)
    )
    durations = tuple(
        tuple(
            0 if origin == destination else 60 + abs(origin - destination)
            for destination in range(count)
        )
        for origin in range(count)
    )
    return RoutingMatrix(
        location_ids=tuple(f"LOC-{index:02d}" for index in range(count)),
        distance_meters=distances,
        duration_seconds=durations,
        source="fake_large_m9",
    )


def test_representative_larger_fake_matrix_is_cached_without_second_provider_call(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 22, 12, tzinfo=UTC)
    locations = _large_locations(25)
    provider = FakeRoutingProvider(matrix=_large_matrix(len(locations)))
    service = RoutingService(
        provider,
        SQLiteMatrixCache(SQLiteDatabase(tmp_path / "matrix.db"), now=lambda: now),
        now=lambda: now,
    )

    first = run(service.compute_matrix(locations, RoutingOptions()))
    second = run(service.compute_matrix(locations, RoutingOptions()))

    assert len(first.matrix.location_ids) == 25
    assert len(first.matrix.distance_meters) == 25
    assert not first.cache_hit
    assert second.cache_hit
    assert provider.matrix_call_count == 1


def test_solver_respects_configured_time_bound_on_canonical_workload() -> None:
    validation = validate_planning_payload(planning_payload("D"))
    assert validation.valid
    assert validation.normalized_request is not None
    solver = OrToolsCapacitySolver(SolverConfig(time_limit_seconds=1))

    started = perf_counter()
    result = solver.solve(validation.normalized_request)
    elapsed = perf_counter() - started

    assert elapsed < 3
    assert result.solver_elapsed_seconds < 3


def test_corrupt_persisted_plan_payload_returns_controlled_api_error(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    database = SQLiteDatabase(tmp_path / "m9.db")
    created_at = datetime(2026, 6, 22, 12, tzinfo=UTC).isoformat()
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO plans (plan_id, scenario_id, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("CORRUPT-PLAN", "A", "{not valid json", created_at),
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/v1/plans/CORRUPT-PLAN",
            headers={"X-Request-ID": "corrupt-plan"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "corrupt-plan"
    assert response.json()["code"] == "INTERNAL_SERVER_ERROR"
    assert response.json()["request_id"] == "corrupt-plan"
    assert "not valid json" not in response.text
    assert "Traceback" not in response.text


def test_missing_database_file_is_created_for_scenario_persistence(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "route_optimizer.db"
    app = create_app(_settings(tmp_path, database_path=database_path))

    with TestClient(app) as client:
        response = client.post("/api/v1/scenarios", json=planning_payload("A"))

    assert response.status_code == 201
    assert database_path.exists()


@pytest.mark.parametrize("payload_size_limit", [1_024, 2_048])
def test_size_limits_fail_before_domain_processing(
    tmp_path: Path,
    payload_size_limit: int,
) -> None:
    app = create_app(_settings(tmp_path, api_max_request_bytes=payload_size_limit))
    oversized = json.dumps(
        {
            "scenario_id": "OVERSIZED",
            "notes": "x" * (payload_size_limit + 100),
        }
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/plans/validate",
            content=oversized,
            headers={
                "Content-Type": "application/json",
                "X-Request-ID": "oversized-m9",
            },
        )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
