"""V1.1-M3 API tests: scenario list, location import preview, and decision D6.

Decision D6 (plan §4): Google travel-time matrices are not stored. The matrix cache does
not keep them, saved scenarios drop them, and what Version 1.0 stored is removed at
start-up. Matrices from fixtures or the fake provider are unaffected. No key or network
is needed: Google is reached only through a mocked HTTP transport.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.application.retention import (
    GOOGLE_MATRIX_SOURCE,
    matrix_is_storable,
    without_unstorable_matrix,
)
from backend.app.config import Settings
from backend.app.domain.models import RoutingMatrix
from backend.app.persistence import (
    SQLiteDatabase,
    SQLiteMatrixCache,
    SQLiteScenarioRepository,
)
from backend.app.routing import FakeRoutingProvider, GoogleRoutingProvider

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPAT_A = PROJECT_ROOT / "sample_data" / "v1_0_compat" / "scenario_a.json"
LOCATIONS = [
    {"location_id": "A", "formatted_address": "A", "latitude": 43.0, "longitude": -79.0},
    {"location_id": "B", "formatted_address": "B", "latitude": 44.0, "longitude": -80.0},
]


def _settings(tmp_path: Path) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    return Settings(**values)


def _google_provider(calls: list[int]) -> GoogleRoutingProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        payload: dict[str, Any] = json.loads(request.content)
        elements = [
            {
                "originIndex": origin,
                "destinationIndex": destination,
                "status": {},
                "condition": "ROUTE_EXISTS",
                "distanceMeters": 0 if origin == destination else 1_000,
                "duration": "0s" if origin == destination else "100s",
            }
            for origin in range(len(payload["origins"]))
            for destination in range(len(payload["destinations"]))
        ]
        return httpx.Response(200, json=elements)

    return GoogleRoutingProvider(
        api_key="m3-sentinel-key-do-not-log",
        routes_matrix_url="https://google.test/matrix",
        retry_base_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )


def _google_matrix_payload() -> dict[str, Any]:
    return {
        "location_ids": ["PLANT", "SUPPLIER_A"],
        "distance_meters": [[0, 1_000], [1_000, 0]],
        "duration_seconds": [[0, 100], [100, 0]],
        "source": GOOGLE_MATRIX_SOURCE,
    }


# --- decision D6: the matrix cache ---------------------------------------------------


def test_google_matrices_are_never_cached_and_the_estimate_says_so(tmp_path: Path) -> None:
    calls: list[int] = []
    app = create_app(_settings(tmp_path))
    app.state.routing_provider = _google_provider(calls)
    with TestClient(app) as client:
        estimate = client.post("/api/v1/matrices/estimate", json={"locations": LOCATIONS}).json()
        first = client.post("/api/v1/matrices/compute", json={"locations": LOCATIONS}).json()
        again = client.post("/api/v1/matrices/estimate", json={"locations": LOCATIONS}).json()
        second = client.post("/api/v1/matrices/compute", json={"locations": LOCATIONS}).json()

    assert estimate["cache_enabled"] is False
    assert again["cache_hit"] is False
    assert again["billable_element_count"] == 4
    assert (first["cache_hit"], second["cache_hit"]) == (False, False)
    assert first["cache_enabled"] is False
    assert first["matrix"]["source"] == GOOGLE_MATRIX_SOURCE
    assert first["matrix"]["expires_at"] is None
    assert len(calls) == 2
    with SQLiteDatabase(tmp_path / "api.db").connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM route_matrix_cache").fetchone()[0] == 0
    assert "m3-sentinel-key-do-not-log" not in json.dumps([estimate, first, again, second])


def test_fake_provider_matrices_are_still_cached(tmp_path: Path) -> None:
    matrix = RoutingMatrix(
        location_ids=("A", "B"),
        distance_meters=((0, 5), (5, 0)),
        duration_seconds=((0, 9), (9, 0)),
        source="fake",
    )
    provider = FakeRoutingProvider(matrix=matrix)
    app = create_app(_settings(tmp_path))
    app.state.routing_provider = provider
    with TestClient(app) as client:
        client.post("/api/v1/matrices/compute", json={"locations": LOCATIONS})
        estimate = client.post("/api/v1/matrices/estimate", json={"locations": LOCATIONS}).json()
        second = client.post("/api/v1/matrices/compute", json={"locations": LOCATIONS}).json()

    assert estimate["cache_enabled"] is True
    assert estimate["cache_hit"] is True
    assert estimate["billable_element_count"] == 0
    assert second["cache_hit"] is True
    assert provider.matrix_call_count == 1


def test_the_google_provider_name_is_the_source_retention_looks_for() -> None:
    provider = _google_provider([])

    assert provider.provider_name == GOOGLE_MATRIX_SOURCE
    assert provider.matrix_storage_allowed is False
    assert FakeRoutingProvider().matrix_storage_allowed is True
    assert not matrix_is_storable({"source": GOOGLE_MATRIX_SOURCE})
    assert matrix_is_storable({"source": "deterministic_offline_fixture"})
    assert matrix_is_storable(None)


# --- decision D6: saved scenarios --------------------------------------------------------


def test_saving_drops_a_google_matrix_and_keeps_a_fixture_matrix(tmp_path: Path) -> None:
    fixture_payload = json.loads(COMPAT_A.read_text(encoding="utf-8"))
    google_payload = {
        **fixture_payload,
        "scenario_id": "G",
        "routing_matrix": _google_matrix_payload(),
    }
    with TestClient(create_app(_settings(tmp_path))) as client:
        kept = client.post("/api/v1/scenarios", json=fixture_payload)
        dropped = client.post("/api/v1/scenarios", json=google_payload)
        replaced = client.put("/api/v1/scenarios/G", json=google_payload)
        loaded = client.get("/api/v1/scenarios/G").json()

    assert kept.status_code == 201
    assert kept.json()["routing_matrix_dropped"] is False
    assert kept.json()["payload"]["routing_matrix"]["source"] == "deterministic_offline_fixture"
    assert dropped.json()["routing_matrix_dropped"] is True
    assert "routing_matrix" not in dropped.json()["payload"]
    assert replaced.json()["routing_matrix_dropped"] is True
    assert "routing_matrix" not in loaded["payload"]
    assert loaded["payload"]["locations"] == fixture_payload["locations"]


def test_start_up_removes_google_matrices_stored_by_version_1_0(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "api.db")
    now = datetime.now(UTC)
    cache = SQLiteMatrixCache(database)
    for key, source in (("matrix:1:google", GOOGLE_MATRIX_SOURCE), ("matrix:1:fake", "fake")):
        cache.set(
            key,
            RoutingMatrix(
                location_ids=("A", "B"),
                distance_meters=((0, 5), (5, 0)),
                duration_seconds=((0, 9), (9, 0)),
                source=source,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            ),
        )
    repository = SQLiteScenarioRepository(database)
    fixture_payload = json.loads(COMPAT_A.read_text(encoding="utf-8"))
    repository.save("KEEP", fixture_payload)
    repository.save("CLEAN", {**fixture_payload, "routing_matrix": _google_matrix_payload()})
    before = {summary.scenario_id: summary.updated_at for summary in repository.list_summaries()}

    with TestClient(create_app(_settings(tmp_path))):
        pass

    assert cache.get("matrix:1:google") is None
    assert cache.get("matrix:1:fake") is not None
    clean = repository.get("CLEAN")
    keep = repository.get("KEEP")
    assert clean is not None and keep is not None
    assert "routing_matrix" not in clean.payload
    assert clean.payload["locations"] == fixture_payload["locations"]
    assert keep.payload["routing_matrix"]["source"] == "deterministic_offline_fixture"
    after = {summary.scenario_id: summary.updated_at for summary in repository.list_summaries()}
    assert after == before  # a retention sweep is not a planner's save


def test_without_unstorable_matrix_never_changes_its_input() -> None:
    payload = {"scenario_id": "X", "routing_matrix": _google_matrix_payload()}

    stripped, removed = without_unstorable_matrix(payload)

    assert removed
    assert "routing_matrix" not in stripped
    assert "routing_matrix" in payload


# --- scenario list ------------------------------------------------------------------------


def test_saved_scenarios_are_listed_newest_first_with_counts(tmp_path: Path) -> None:
    payload = json.loads(COMPAT_A.read_text(encoding="utf-8"))
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.get("/api/v1/scenarios").json()["scenarios"] == []
        client.post("/api/v1/scenarios", json={**payload, "scenario_id": "OLD", "name": "Old"})
        client.post("/api/v1/scenarios", json={"scenario_id": "BARE"})
        response = client.get("/api/v1/scenarios")

    assert response.status_code == 200
    scenarios = response.json()["scenarios"]
    assert [scenario["scenario_id"] for scenario in scenarios] == ["BARE", "OLD"]
    old = scenarios[1]
    assert old["name"] == "Old"
    assert (old["location_count"], old["vehicle_count"]) == (
        len(payload["locations"]),
        len(payload["vehicles"]),
    )
    assert (old["shift_count"], old["task_count"]) == (
        len(payload["vehicle_shifts"]),
        len(payload["tasks"]),
    )
    assert scenarios[0]["name"] is None
    assert scenarios[0]["task_count"] == 0


# --- location import preview -----------------------------------------------------------------


def test_location_import_preview_maps_rows_and_reports_issues(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        good = client.post(
            "/api/v1/imports/locations/preview",
            json={"rows": [{"Company": "Acme", "Full address": "1 Acme St", "Notes": "x"}]},
        )
        bad = client.post(
            "/api/v1/imports/locations/preview",
            json={"rows": [{"Company": "Acme", "Full address": ""}]},
        )
        empty = client.post("/api/v1/imports/locations/preview", json={"rows": []})

    assert good.status_code == 200
    body = good.json()
    assert body["valid"] is True
    assert body["rows"] == [
        {"row_number": 2, "name": "Acme", "address": "1 Acme St", "location_id": None}
    ]
    assert body["unknown_columns"] == ["Notes"]
    assert [issue["code"] for issue in body["issues"]] == ["UNKNOWN_COLUMN"]
    assert bad.json()["valid"] is False
    assert bad.json()["issues"][0]["row_number"] == 2
    assert empty.status_code == 422


def test_location_import_preview_respects_the_location_limit(tmp_path: Path) -> None:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "api_max_locations": 2,
        "_env_file": None,
    }
    rows = [{"name": f"L{index}", "address": f"{index} Road"} for index in range(3)]
    with TestClient(create_app(Settings(**values))) as client:
        response = client.post("/api/v1/imports/locations/preview", json={"rows": rows})

    assert response.status_code == 413
    assert response.json()["code"] == "LOCATION_LIMIT_EXCEEDED"
