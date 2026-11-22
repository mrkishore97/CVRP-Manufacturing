"""V1.1-M6 API: scenario management, drafts, retention on load, and plan comparison.

- Save as and Duplicate never overwrite (``if_exists=error``); the default still replaces.
- Delete removes a scenario with its plans and draft.
- Drafts keep the working copy, never a Google matrix.
- Coordinates older than 30 days are stripped when a scenario or draft is loaded and at
  start-up; supplied coordinates, place IDs, and confirmations are kept.
- A saved scenario round-trips losslessly.
- Plans carry an input fingerprint: the same inputs with other settings share it.
"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain.geocoding import address_fingerprint
from backend.app.persistence import SCHEMA_VERSION, SQLiteDatabase, SQLiteScenarioRepository

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V11_E = PROJECT_ROOT / "sample_data" / "v1_1" / "v11_e_objective_modes.json"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "m6.db",
        "google_maps_api_key": None,
        "solver_in_subprocess": False,
        "_env_file": None,
        **overrides,
    }
    return Settings(**values)


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **overrides)))


def _payload(**changes: Any) -> dict[str, Any]:
    with V11_E.open(encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    payload.update(changes)
    return payload


def _resolved(payload: dict[str, Any], *, age_days: float) -> dict[str, Any]:
    """Mark the first non-plant location as resolved ``age_days`` ago (Google-derived)."""
    updated = deepcopy(payload)
    location = updated["locations"][1]
    geocoded_at = datetime.now(UTC) - timedelta(days=age_days)
    location.update(
        {
            "formatted_address": "Matched by Google",
            "place_id": "place-123",
            "geocode_status": "RESOLVED",
            "geocode_source_fingerprint": address_fingerprint(location["address"], "ca"),
            "geocoded_at": geocoded_at.isoformat().replace("+00:00", "Z"),
            "geocode_location_type": "ROOFTOP",
            "geocode_partial_match": False,
            "geocode_confirmed": True,
        }
    )
    return updated


# --- save, save as, delete -----------------------------------------------------------


def test_if_exists_error_never_overwrites_and_the_default_still_replaces(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.post("/api/v1/scenarios?if_exists=error", json=_payload(name="First"))
        assert first.status_code == 201
        refused = client.post("/api/v1/scenarios?if_exists=error", json=_payload(name="Second"))
        assert refused.status_code == 409
        assert refused.json()["code"] == "SCENARIO_EXISTS"
        assert client.get("/api/v1/scenarios/V11-E").json()["payload"]["name"] == "First"

        replaced = client.post("/api/v1/scenarios", json=_payload(name="Replaced"))
        assert replaced.status_code == 201
        assert client.get("/api/v1/scenarios/V11-E").json()["payload"]["name"] == "Replaced"
        assert client.post("/api/v1/scenarios?if_exists=maybe", json=_payload()).status_code == 422


def test_delete_removes_the_scenario_its_plans_and_its_draft(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/scenarios", json=_payload())
        client.post("/api/v1/scenarios", json=_payload(scenario_id="OTHER"))
        assert client.post("/api/v1/plans/solve", json=_payload()).status_code == 200
        assert client.post("/api/v1/plans/solve", json=_payload()).status_code == 200
        client.post("/api/v1/plans/solve", json=_payload(scenario_id="OTHER"))
        client.put("/api/v1/scenarios/V11-E/draft", json={"payload": _payload(name="Draft")})
        listed = {
            row["scenario_id"]: row for row in client.get("/api/v1/scenarios").json()["scenarios"]
        }
        assert listed["V11-E"]["plan_count"] == 2

        deleted = client.delete("/api/v1/scenarios/V11-E")
        assert deleted.status_code == 200
        assert deleted.json() | {"request_id": None} == {
            "request_id": None,
            "scenario_id": "V11-E",
            "plans_removed": 2,
            "draft_removed": True,
        }
        assert client.get("/api/v1/scenarios/V11-E").status_code == 404
        assert client.get("/api/v1/scenarios/V11-E/plans").json()["plans"] == []
        assert client.get("/api/v1/scenarios/V11-E/draft").status_code == 404
        assert client.delete("/api/v1/scenarios/V11-E").status_code == 404
        # Another scenario keeps its plan.
        assert len(client.get("/api/v1/scenarios/OTHER/plans").json()["plans"]) == 1


# --- drafts ---------------------------------------------------------------------------


def test_a_draft_is_kept_returned_and_discarded_without_touching_the_save(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/scenarios", json=_payload(name="Saved"))
        assert client.get("/api/v1/scenarios/V11-E/draft").status_code == 404
        meta = {"version": 1, "plan_id": "PLAN-1", "baseline_fingerprint": "abc"}
        put = client.put(
            "/api/v1/scenarios/V11-E/draft", json={"payload": _payload(name="Draft"), "meta": meta}
        )
        assert put.status_code == 200

        draft = client.get("/api/v1/scenarios/V11-E/draft").json()
        assert draft["payload"]["name"] == "Draft"
        assert draft["meta"] == meta
        assert draft["updated_at"]
        assert client.get("/api/v1/scenarios/V11-E").json()["payload"]["name"] == "Saved"

        assert client.delete("/api/v1/scenarios/V11-E/draft").json()["deleted"] is True
        assert client.delete("/api/v1/scenarios/V11-E/draft").json()["deleted"] is False
        assert client.get("/api/v1/scenarios/V11-E/draft").status_code == 404


def test_a_draft_never_keeps_google_travel_times(tmp_path: Path) -> None:
    payload = _payload()
    payload["routing_matrix"]["source"] = "google_routes"
    with _client(tmp_path) as client:
        put = client.put("/api/v1/scenarios/V11-E/draft", json={"payload": payload})
        assert put.json()["routing_matrix_dropped"] is True
        stored = client.get("/api/v1/scenarios/V11-E/draft").json()["payload"]
        assert "routing_matrix" not in stored
    with sqlite3.connect(tmp_path / "m6.db") as connection:
        raw = connection.execute("SELECT payload_json FROM scenario_drafts").fetchone()[0]
    assert "google_routes" not in raw


def test_draft_requests_are_checked(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        mismatch = client.put("/api/v1/scenarios/OTHER/draft", json={"payload": _payload()})
        assert mismatch.status_code == 409
        assert mismatch.json()["code"] == "SCENARIO_ID_MISMATCH"
        large = client.put(
            "/api/v1/scenarios/V11-E/draft",
            json={"payload": _payload(), "meta": {"padding": "x" * 20_000}},
        )
        assert large.status_code == 413
        assert large.json()["code"] == "DRAFT_META_TOO_LARGE"
        too_many = _payload(tasks=[_payload()["tasks"][0]] * 2_001)
        assert (
            client.put("/api/v1/scenarios/V11-E/draft", json={"payload": too_many}).status_code
            == 413
        )


# --- retention on load ----------------------------------------------------------------


def test_expired_coordinates_are_stripped_when_a_saved_scenario_is_loaded(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "m6.db")
    expired = _resolved(_payload(), age_days=31)
    with _client(tmp_path) as client:
        # Stored directly, as a scenario saved 31 days ago would be.
        SQLiteScenarioRepository(database).save("V11-E", expired)
        loaded = client.get("/api/v1/scenarios/V11-E").json()

    assert loaded["expired_coordinates_removed"] == 1
    location = loaded["payload"]["locations"][1]
    for field in ("latitude", "longitude", "formatted_address", "geocoded_at"):
        assert field not in location
    assert location["place_id"] == "place-123"
    assert location["geocode_confirmed"] is True
    assert location["geocode_status"] == "PENDING"
    assert location["address"] == expired["locations"][1]["address"]
    # Coordinates supplied in JSON (no provenance) are the planner's and stay.
    assert loaded["payload"]["locations"][0]["latitude"] == expired["locations"][0]["latitude"]
    # The stored copy was cleaned too.
    stored = SQLiteScenarioRepository(database).get("V11-E")
    assert stored is not None and "latitude" not in stored.payload["locations"][1]


def test_fresh_coordinates_are_kept_and_drafts_are_cleaned_too(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/v1/scenarios", json=_resolved(_payload(), age_days=29))
        fresh = client.get("/api/v1/scenarios/V11-E").json()
        assert fresh["expired_coordinates_removed"] == 0
        assert "latitude" in fresh["payload"]["locations"][1]

        client.put(
            "/api/v1/scenarios/V11-E/draft", json={"payload": _resolved(_payload(), age_days=40)}
        )
        draft = client.get("/api/v1/scenarios/V11-E/draft").json()
        assert draft["expired_coordinates_removed"] == 1
        assert "latitude" not in draft["payload"]["locations"][1]


def test_start_up_strips_expired_coordinates_and_records_the_schema(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "m6.db")
    SQLiteScenarioRepository(database).save(
        "OLD", _resolved(_payload(scenario_id="OLD"), age_days=45)
    )
    with _client(tmp_path):
        pass  # start-up and shut-down
    stored = SQLiteScenarioRepository(database).get("OLD")
    assert stored is not None
    assert "latitude" not in stored.payload["locations"][1]
    with sqlite3.connect(tmp_path / "m6.db") as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('plans')")}
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert int(version) == SCHEMA_VERSION == 2
    assert "plans_by_scenario" in indexes
    assert {"scenarios", "plans", "scenario_drafts", "schema_meta"} <= tables


def test_a_saved_scenario_round_trips_losslessly(tmp_path: Path) -> None:
    payload = _resolved(_payload(name="Round trip"), age_days=1)
    payload["planner_defaults"] = {
        "pickup_service_minutes": 20,
        "delivery_service_minutes": 10,
        "capacity_unit": "pallets",
    }
    payload["optimization_options"] = {"objective_mode": "BALANCE_WORKLOAD"}
    payload["routing_options"] = {"routing_preference": "TRAFFIC_AWARE"}
    payload["tasks"][0]["notes"] = "Dock 4 — call ahead"
    with _client(tmp_path) as client:
        client.post("/api/v1/scenarios", json=payload)
        loaded = client.get("/api/v1/scenarios/V11-E").json()["payload"]
    assert loaded == payload


# --- plan comparison ------------------------------------------------------------------


def test_plans_of_the_same_inputs_share_a_fingerprint_whatever_the_settings(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        fewest = client.post("/api/v1/plans/solve", json=_payload()).json()["plan"]
        balanced_payload = _payload(
            optimization_options={"objective_mode": "BALANCE_WORKLOAD", "travel_time_factor": 1.2}
        )
        balanced = client.post("/api/v1/plans/solve", json=balanced_payload).json()["plan"]
        renamed = _payload(name="Renamed")
        renamed["locations"][1]["name"] = "Another name"
        renamed["vehicles"][0]["name"] = "Big truck"
        renamed["tasks"][0]["notes"] = "Only a note"
        same = client.post("/api/v1/plans/solve", json=renamed).json()["plan"]
        changed_payload = _payload()
        changed_payload["tasks"] = changed_payload["tasks"][:-1]
        changed = client.post("/api/v1/plans/solve", json=changed_payload).json()["plan"]
        history = client.get("/api/v1/scenarios/V11-E/plans").json()["plans"]

    assert fewest["input_fingerprint"].startswith("v1:")
    assert balanced["input_fingerprint"] == fewest["input_fingerprint"]
    assert same["input_fingerprint"] == fewest["input_fingerprint"]
    assert changed["input_fingerprint"] != fewest["input_fingerprint"]
    newest = history[0]
    assert newest["plan_id"] == changed["plan_id"]
    assert newest["input_fingerprint"] == changed["input_fingerprint"]
    balanced_summary = next(row for row in history if row["plan_id"] == balanced["plan_id"])
    assert balanced_summary["balance_strength"] == "MEDIUM"
    assert balanced_summary["time_limit_seconds"] == 10
    assert balanced_summary["truck_shifts_available"] == 3
    assert balanced_summary["longest_working_seconds"] > 0
    assert balanced_summary["total_driving_seconds"] == balanced["total_driving_seconds"]
