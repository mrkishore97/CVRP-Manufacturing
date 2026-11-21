"""V1.1-M5 API: option bounds, plan history, and responsiveness during a solve.

- Out-of-range options are rejected with field-level errors, and JSON cannot exceed the
  server's time-limit ceiling.
- Two solves produce two retrievable plans; history keeps the newest per scenario.
- Health answers while a solve is running (finding F17).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.main import create_app
from backend.app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
V11_E = PROJECT_ROOT / "sample_data" / "v1_1" / "v11_e_objective_modes.json"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
        **overrides,
    }
    return Settings(**values)


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    return TestClient(create_app(_settings(tmp_path, **overrides)))


def _payload(**options: Any) -> dict[str, Any]:
    with V11_E.open(encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    if options:
        payload["optimization_options"] = options
    return payload


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"objective_mode": "CHEAPEST"}, "optimization_options.objective_mode"),
        ({"search_effort": "MAXIMUM"}, "optimization_options.search_effort"),
        ({"time_limit_seconds": 0}, "optimization_options.time_limit_seconds"),
        ({"travel_time_factor": 2.5}, "optimization_options.travel_time_factor"),
        ({"travel_time_factor": 1.234}, "optimization_options.travel_time_factor"),
        ({"extra_truck_cost_km": -1}, "optimization_options.extra_truck_cost_km"),
        ({"balance_strength": "EXTREME"}, "optimization_options.balance_strength"),
        ({"objectve_mode": "MINIMIZE_TRAVEL"}, "optimization_options.objectve_mode"),
    ],
)
def test_out_of_range_options_are_field_level_errors(
    tmp_path: Path, options: dict[str, Any], field: str
) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/v1/plans/validate", json=_payload(**options))

    validation = response.json()["validation"]
    assert validation["valid"] is False
    issue = next(issue for issue in validation["issues"] if issue["field"] == field)
    assert issue["severity"] == "ERROR"
    assert issue["section"] == "optimization_options"


def test_json_cannot_exceed_the_server_time_limit_ceiling(tmp_path: Path) -> None:
    with _client(tmp_path, solver_max_time_limit_seconds=30) as client:
        validate = client.post("/api/v1/plans/validate", json=_payload(time_limit_seconds=31))
        solve = client.post("/api/v1/plans/solve", json=_payload(time_limit_seconds=31))
        allowed = client.post("/api/v1/plans/validate", json=_payload(time_limit_seconds=30))

    [issue] = validate.json()["validation"]["issues"]
    assert issue["field"] == "optimization_options.time_limit_seconds"
    assert "maximum of 30 seconds" in issue["message"]
    assert solve.status_code == 422
    assert solve.json()["details"][0]["field"] == "optimization_options.time_limit_seconds"
    assert allowed.json()["validation"]["valid"] is True


def test_the_server_default_must_not_exceed_its_maximum(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _settings(tmp_path, solver_time_limit_seconds=60, solver_max_time_limit_seconds=30)


def test_config_reports_the_time_limit_ceiling_and_history_limit(tmp_path: Path) -> None:
    with _client(tmp_path, solver_max_time_limit_seconds=45, plan_history_limit=7) as client:
        config = client.get("/api/v1/config").json()

    assert config["solver_time_limit_seconds"] == 10
    assert config["solver_max_time_limit_seconds"] == 45
    assert config["plan_history_limit"] == 7


def test_two_solves_give_two_retrievable_plans_and_history(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.post("/api/v1/plans/solve", json=_payload()).json()["plan"]
        second = client.post(
            "/api/v1/plans/solve", json=_payload(objective_mode="BALANCE_WORKLOAD")
        ).json()["plan"]
        fetched = [client.get(f"/api/v1/plans/{plan['plan_id']}") for plan in (first, second)]
        history = client.get("/api/v1/scenarios/V11-E/plans").json()
        unknown = client.get("/api/v1/scenarios/NEVER-SOLVED/plans").json()

    assert first["plan_id"] != second["plan_id"]
    assert all(response.status_code == 200 for response in fetched)
    assert fetched[1].json()["plan"]["optimization_options"]["objective_mode"] == (
        "BALANCE_WORKLOAD"
    )
    summaries = history["plans"]
    assert [summary["plan_id"] for summary in summaries] == [
        second["plan_id"],
        first["plan_id"],
    ]
    assert summaries[0]["objective_mode"] == "BALANCE_WORKLOAD"
    assert summaries[0]["truck_shifts_used"] > summaries[1]["truck_shifts_used"]
    assert summaries[1]["total_distance_meters"] == 216_000
    assert unknown["plans"] == []


def test_history_keeps_only_the_newest_plans_per_scenario(tmp_path: Path) -> None:
    with _client(tmp_path, plan_history_limit=2) as client:
        plan_ids = [
            client.post("/api/v1/plans/solve", json=_payload()).json()["plan"]["plan_id"]
            for _ in range(3)
        ]
        history = client.get("/api/v1/scenarios/V11-E/plans").json()["plans"]
        oldest = client.get(f"/api/v1/plans/{plan_ids[0]}")

    assert [summary["plan_id"] for summary in history] == [plan_ids[2], plan_ids[1]]
    assert oldest.status_code == 404


def test_health_responds_while_a_solve_is_running(tmp_path: Path) -> None:
    application = create_app(_settings(tmp_path))
    payload = _payload(search_effort="THOROUGH", time_limit_seconds=3)

    async def scenario() -> tuple[float, float, int]:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = perf_counter()
            solve = asyncio.create_task(client.post("/api/v1/plans/solve", json=payload))
            await asyncio.sleep(0.5)
            health = await client.get("/api/v1/health")
            health_done = perf_counter() - started
            solved = await solve
            return health_done, perf_counter() - started, health.status_code + solved.status_code

    health_done, solve_done, codes = asyncio.run(scenario())

    assert codes == 400  # 200 + 200
    assert health_done < 1.5
    assert solve_done >= 3
    assert health_done < solve_done
