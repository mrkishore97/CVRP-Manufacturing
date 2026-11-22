"""V1.1-M6 through the real app and backend.

- Results show a location name for every stop, and the run sheets reconcile with the
  stop tables on the page.
- A scenario saved by Version 1.0 opens in the forms with the defaults filled in.
- After a simulated browser refresh, unsaved edits are restored from the backend draft.
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
from backend.app.persistence import SQLiteDatabase, SQLiteScenarioRepository
from frontend import api_client
from frontend.export_utils import RUN_SHEET_COLUMNS, run_sheets_workbook_bytes
from frontend.state.results import STATUS_TEXT
from frontend.tests.form_driver import click, go, ok, scenario, workspace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
VERSION_1_0_A = PROJECT_ROOT / "sample_data" / "v1_0_compat" / "scenario_a.json"


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "m6_pages.db"


@pytest.fixture
def backend(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": database_path,
        "google_maps_api_key": None,
        "solver_in_subprocess": False,
        "_env_file": None,
    }
    with TestClient(create_app(Settings(**values))) as test_client:
        client = api_client.BackendClient("http://testserver", transport=test_client._transport)
        monkeypatch.setattr(
            api_client.BackendClient, "from_environment", classmethod(lambda cls: client)
        )
        yield test_client


def _start(page: str = "scenario", **params: str) -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=60)
    app.query_params["page"] = page
    for key, value in params.items():
        app.query_params[key] = value
    app.run()
    ok(app)
    return app


def test_every_stop_has_a_name_and_the_run_sheets_match_the_stop_tables(
    backend: TestClient,
) -> None:
    app = _start("optimize")
    click(app, "Solve route plan")
    assert STATUS_TEXT["FEASIBLE"][1] in [success.value for success in app.success]
    plan = workspace(app).derived.plan
    assert isinstance(plan, dict)
    current = scenario(app)
    names = {location["name"] for location in current["locations"]}
    ids = {location["location_id"] for location in current["locations"]}

    stop_tables = [frame.value for frame in app.dataframe if "Action" in frame.value.columns]
    assert len(stop_tables) == len(plan["routes"]) >= 1
    for table in stop_tables:
        assert set(table["Location"]) <= names
        assert not set(table["Location"]) & ids

    workbook = load_workbook(BytesIO(run_sheets_workbook_bytes(plan, current)))
    assert len(workbook.sheetnames) == len(plan["routes"]) + 1
    for sheet_name, table in zip(workbook.sheetnames[1:], stop_tables, strict=True):
        rows = list(workbook[sheet_name].iter_rows(values_only=True))
        start = next(index for index, row in enumerate(rows) if row[0] == "#")
        body = [dict(zip(RUN_SHEET_COLUMNS, row, strict=False)) for row in rows[start + 1 :]]
        assert len(body) == len(table)
        for sheet_row, (_, screen_row) in zip(body, table.iterrows(), strict=True):
            for column in ("Action", "Location", "PO", "Arrive", "Depart"):
                assert (sheet_row[column] or "") == (screen_row[column] or "")

    compare = [frame.value for frame in app.dataframe if "Plan ID" in frame.value.columns]
    assert list(compare[0]["Plan ID"]) == [plan["plan_id"]]
    assert list(compare[0]["Inputs"]) == ["This plan"]


def test_a_version_1_0_saved_scenario_opens_with_defaults(
    backend: TestClient, database_path: Path
) -> None:
    with VERSION_1_0_A.open(encoding="utf-8") as handle:
        version_1_0 = json.load(handle)
    # Stored the way Version 1.0 saved it: no name, defaults, or options.
    SQLiteScenarioRepository(SQLiteDatabase(database_path)).save("A", version_1_0)

    app = _start("scenario", scenario="A")
    assert workspace(app).derived.saved_scenario_id == "A"
    assert "No unsaved edits" in [str(caption.value) for caption in app.sidebar.caption]
    fields = {box.label: box.value for box in app.text_input}
    assert fields["Scenario name"] == ""
    assert fields["Capacity unit label"] == "units"
    minutes = {box.label: box.value for box in app.number_input}
    assert minutes["Pickup service minutes"] == 15
    assert minutes["Delivery service minutes"] == 15

    go(app, "optimize")
    assert any(
        str(caption.value).startswith("Fewest trucks, standard search, time limit 10 s")
        for caption in app.caption
    )
    click(app, "Solve route plan")
    assert app.session_state["current_page"] == "results"
    assert "optimization_options" not in scenario(app)  # still the Version 1.0 shape


def test_unsaved_edits_are_restored_after_a_refresh(backend: TestClient) -> None:
    first = _start()
    next(box for box in first.text_input if box.label == "Scenario name").input("Before refresh")
    click(first, "Save details")
    assert backend.get("/api/v1/scenarios/A/draft").json()["payload"]["name"] == "Before refresh"

    second = _start("scenario", scenario="A")
    assert scenario(second)["name"] == "Three-truck feasible mixed plan"
    second.button(key="draft-restore").click().run()
    ok(second)
    assert scenario(second)["name"] == "Before refresh"
    assert "Restored the unsaved changes." in " ".join(s.value for s in second.success)

    click(second, "Save scenario")
    assert backend.get("/api/v1/scenarios/A").json()["payload"]["name"] == "Before refresh"
    assert backend.get("/api/v1/scenarios/A/draft").status_code == 404
