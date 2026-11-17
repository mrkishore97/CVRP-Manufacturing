"""Version 1.0 default-option characterization tests (V1.1-M0).

Each frozen Version 1.0 payload in ``sample_data/v1_0_compat`` is posted to the solve endpoint
with no options. The result must match what ``v1.0.0`` returned: status, scheduled and
unscheduled tasks, truck-shifts used, total distance, and diagnostic codes. Any Version 1.1
change that alters these is a behaviour change and must be decided, not discovered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain import validate_planning_payload
from backend.app.domain.results import PlanResult
from backend.app.optimization import validate_plan_result

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPAT_DIR = PROJECT_ROOT / "sample_data" / "v1_0_compat"
SCENARIOS = ("A", "B", "C", "D", "E", "F")


def _load(name: str) -> Any:
    return json.loads((COMPAT_DIR / name).read_text(encoding="utf-8"))


def _content_sha256(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payload(letter: str) -> dict[str, Any]:
    payload: dict[str, Any] = _load(f"scenario_{letter.lower()}.json")
    return payload


def _expected(letter: str) -> dict[str, Any]:
    expected: dict[str, Any] = _load("expected_default_results.json")["scenarios"][letter]
    return expected


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    settings = Settings(  # type: ignore[call-arg]
        app_environment="test",
        database_path=tmp_path_factory.mktemp("characterization") / "api.db",
        google_maps_api_key=None,
        _env_file=None,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_frozen_files_are_unchanged() -> None:
    manifest = _load("manifest.json")

    assert manifest["frozen_from"] == "v1.0.0"
    assert set(manifest["files"]) == {
        *(f"scenario_{letter.lower()}.json" for letter in SCENARIOS),
        "expected_default_results.json",
    }
    for name, recorded_hash in manifest["files"].items():
        assert _content_sha256(_load(name)) == recorded_hash, f"{name} was modified"


def test_frozen_payloads_hold_only_version_1_0_keys() -> None:
    version_1_0_keys = {
        "scenario_id",
        "timezone",
        "planning_horizon",
        "plant_location_id",
        "locations",
        "vehicles",
        "vehicle_shifts",
        "tasks",
        "routing_matrix",
    }
    for letter in SCENARIOS:
        assert set(_payload(letter)) == version_1_0_keys


@pytest.mark.parametrize("letter", SCENARIOS)
def test_default_results_match_version_1_0(client: TestClient, letter: str) -> None:
    payload = _payload(letter)
    expected = _expected(letter)

    response = client.post("/api/v1/plans/solve", json=payload)

    assert response.status_code == expected["http_status"]
    body = response.json()
    if response.status_code != 200:
        assert body["code"] == expected["error_code"]
        assert sorted({detail["code"] for detail in body["details"]}) == expected["issue_codes"]
        return

    plan = body["plan"]
    observed = {
        "status": plan["status"],
        "scheduled_task_ids": sorted(plan["scheduled_task_ids"]),
        "unscheduled_task_ids": sorted(plan["unscheduled_task_ids"]),
        "truck_shifts_used": sorted(
            f"{route['vehicle_id']}/{route['shift_id']}"
            for route in plan["routes"]
            if route["stops"]
        ),
        "total_distance_meters": plan["total_distance_meters"],
        "diagnostic_codes": sorted({diagnostic["code"] for diagnostic in plan["diagnostics"]}),
    }
    assert observed == {key: value for key, value in expected.items() if key != "http_status"}


@pytest.mark.parametrize("letter", [letter for letter in SCENARIOS if letter != "B"])
def test_default_plans_pass_independent_validation(client: TestClient, letter: str) -> None:
    payload = _payload(letter)
    validation = validate_planning_payload(payload)
    assert validation.normalized_request is not None

    response = client.post("/api/v1/plans/solve", json=payload)
    plan = PlanResult.model_validate(response.json()["plan"])

    result = validate_plan_result(validation.normalized_request, plan)
    assert result.valid, result.issues
