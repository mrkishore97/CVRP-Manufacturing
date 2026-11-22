"""V1.1-M7 representative size test: a form-built scenario at the documented limits.

The documented planning size (``docs/troubleshooting.md`` → "Scenario size") is one week
for 20 trucks on weekday shifts (100 truck-shifts), 100 locations (the most one
travel-time calculation takes), and 300 POs, which plan completely at the default 10 s
time limit. Every row is entered through the forms' own state functions.

- Through the real backend: 100 addresses resolve in one request with one lookup each,
  the 100 x 100 travel times are estimated and calculated, and the scenario validates.
- Through the real app: the saved scenario opens with its travel times, solves on the
  Optimize page with every PO planned, and Results, Tasks, and Review render it. The run
  sheets have one sheet per truck-shift, and every request stays well within the limits.
- At the request limits (200 locations, 1,000 tasks) a request is accepted, and one more
  location or task, or a 101-location travel-time request, is refused with a clear message.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.routing import FakeRoutingProvider
from backend.tests.fixtures.size_scenario import (
    DOCUMENTED_POS,
    DOCUMENTED_TRUCKS,
    MAX_MATRIX_LOCATIONS,
    MAX_REQUEST_TASKS,
    WEEKDAYS,
    fake_provider,
    form_built_scenario,
    task_rows,
)
from frontend import api_client
from frontend.export_utils import run_sheets_workbook_bytes, workbook_bytes
from frontend.state.locations import apply_resolutions, resolve_batches, resolve_rows
from frontend.state.results import STATUS_TEXT
from frontend.state.workspace import routing_locations, save_document, solve_payload
from frontend.tests.form_driver import click, go, ok, scenario, workspace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
MAX_REQUEST_BYTES = 2_000_000


@pytest.fixture(scope="module")
def built() -> tuple[dict[str, Any], FakeRoutingProvider]:
    scenario_payload, coordinates = form_built_scenario()
    return scenario_payload, fake_provider(scenario_payload, coordinates)


@pytest.fixture
def client(
    built: tuple[dict[str, Any], FakeRoutingProvider],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[api_client.BackendClient]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "size.db",
        "google_maps_api_key": None,
        "solver_in_subprocess": False,
        "_env_file": None,
    }
    backend = create_app(Settings(**values))
    backend.state.routing_provider = built[1]
    with TestClient(backend) as test_client:
        frontend_client = api_client.BackendClient(
            "http://testserver", transport=test_client._transport
        )
        monkeypatch.setattr(
            api_client.BackendClient, "from_environment", classmethod(lambda cls: frontend_client)
        )
        yield frontend_client


def _bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload).encode("utf-8"))


def test_a_form_built_week_at_the_documented_size_plans_completely(
    built: tuple[dict[str, Any], FakeRoutingProvider], client: api_client.BackendClient
) -> None:
    form_built, provider = built
    assert len(form_built["locations"]) == MAX_MATRIX_LOCATIONS
    assert len(form_built["vehicles"]) == DOCUMENTED_TRUCKS
    assert len(form_built["vehicle_shifts"]) == DOCUMENTED_TRUCKS * WEEKDAYS
    assert len(form_built["tasks"]) == DOCUMENTED_POS

    # Locations: 100 addresses, one request at the default limit, one lookup each.
    ids = [str(row["location_id"]) for row in form_built["locations"]]
    (batch,) = resolve_batches(ids, plant=str(form_built["plant_location_id"]), size=100)
    rows = resolve_rows(form_built, batch)
    resolved = client.resolve_locations(rows, plant_location_id=form_built["plant_location_id"])
    results = resolved.payload["results"]
    assert {result["status"] for result in results} == {"RESOLVED"}
    assert provider.resolve_call_count == MAX_MATRIX_LOCATIONS
    sent = {row["location_id"]: row["address"] for row in rows}
    located = apply_resolutions(form_built, results, sent_addresses=sent).scenario

    # Travel times: estimated first (10,000 elements in 16 requests), then calculated.
    locations = routing_locations(located)
    estimate = client.estimate_matrix(locations).payload
    assert estimate["element_count"] == MAX_MATRIX_LOCATIONS**2
    assert estimate["request_count"] == 16
    assert estimate["confirmation_required"] is True
    matrix = client.compute_matrix(locations).payload["matrix"]
    assert len(matrix["location_ids"]) == MAX_MATRIX_LOCATIONS

    validation = client.validate_plan(located).validation
    assert validation is not None and validation.valid, validation
    saved = {**located, "routing_matrix": matrix}
    assert _bytes(saved) < MAX_REQUEST_BYTES // 4
    client.save_scenario(saved)

    # The real app: open the saved scenario with its travel times, solve, read Results.
    app = AppTest.from_file(APP_PATH, default_timeout=120)
    app.query_params["page"] = "optimize"
    app.query_params["scenario"] = str(located["scenario_id"])
    app.run()
    ok(app)
    assert workspace(app).derived.matrix is not None
    click(app, "Solve route plan")
    assert app.session_state["current_page"] == "results"
    assert STATUS_TEXT["FEASIBLE"][1] in [success.value for success in app.success]
    plan = workspace(app).derived.plan
    assert isinstance(plan, dict)
    assert len(plan["scheduled_task_ids"]) == DOCUMENTED_POS
    assert plan["unscheduled_task_ids"] == []
    figures = {metric.label: metric.value for metric in app.metric}
    assert figures["POs planned"] == f"{DOCUMENTED_POS} of {DOCUMENTED_POS}"
    stop_tables = [frame.value for frame in app.dataframe if "Action" in frame.value.columns]
    assert len(stop_tables) == len(plan["routes"])
    names = {location["name"] for location in located["locations"]}
    assert all(set(table["Location"]) <= names for table in stop_tables)

    # Requests stay well within the limits; exports cover every truck-shift.
    assert _bytes(solve_payload(workspace(app))) < MAX_REQUEST_BYTES // 3
    assert _bytes(save_document(workspace(app))) < MAX_REQUEST_BYTES // 3
    current = scenario(app)
    run_sheets = load_workbook(BytesIO(run_sheets_workbook_bytes(plan, current)))
    assert len(run_sheets.sheetnames) == len(plan["routes"]) + 1
    assert "Plan Settings" in load_workbook(BytesIO(workbook_bytes(plan, current))).sheetnames

    # The input pages render at this size too.
    for page in ("tasks", "review", "locations", "fleet"):
        go(app, page)


def test_requests_at_the_limits_are_accepted_and_one_more_is_refused(
    client: api_client.BackendClient,
) -> None:
    wide, _ = form_built_scenario(locations=200, tasks=0)
    tasks = task_rows(wide, MAX_REQUEST_TASKS + 1)
    at_limit = {**wide, "tasks": tasks[:MAX_REQUEST_TASKS]}
    assert _bytes(at_limit) < MAX_REQUEST_BYTES // 2
    at_limit_validation = client.validate_plan(at_limit).validation
    assert at_limit_validation is not None and at_limit_validation.valid

    over: dict[str, dict[str, Any]] = {
        "tasks": {**wide, "tasks": tasks},
        "locations": {
            **at_limit,
            "locations": [
                *wide["locations"],
                {"location_id": "ONE-MORE", "name": "One more", "address": "1 More St"},
            ],
        },
    }
    for label, payload in over.items():
        with pytest.raises(api_client.BackendApiError) as error:
            client.solve_plan(payload)
        assert error.value.status_code == 413
        assert f"more than {200 if label == 'locations' else MAX_REQUEST_TASKS} {label}" in str(
            error.value
        )

    too_many = [
        {"location_id": f"L{index}", "address": f"{index} Size Test St, Ontario"}
        for index in range(101)
    ]
    with pytest.raises(api_client.BackendApiError) as resolve_error:
        client.resolve_locations(too_many)
    assert "more than 100" in str(resolve_error.value)

    one_too_many = [
        {"location_id": f"L{index}", "latitude": 43.5 + index / 1_000, "longitude": -79.6}
        for index in range(MAX_MATRIX_LOCATIONS + 1)
    ]
    with pytest.raises(api_client.BackendApiError) as matrix_error:
        client.estimate_matrix(one_too_many)
    assert matrix_error.value.status_code == 422
