"""V1.1-M5 through the real app and backend: settings on the Optimize page change plans.

Sample A ("feasible sample", Scenario A's shape) opens with its travel times. Fewest
trucks puts all six POs on one truck; Balanced workload spreads them. Both plans are
stored, with their settings, and listed newest first.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.api.main import create_app
from backend.app.config import Settings
from frontend import api_client
from frontend.tests.form_driver import click, go, ok, workspace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")


@pytest.fixture
def backend(tmp_path: Path) -> Iterator[TestClient]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "m5.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    with TestClient(create_app(Settings(**values))) as test_client:
        yield test_client


@pytest.fixture
def app(backend: TestClient, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    client = api_client.BackendClient("http://testserver", transport=backend._transport)
    monkeypatch.setattr(
        api_client.BackendClient, "from_environment", classmethod(lambda cls: client)
    )
    test_app = AppTest.from_file(APP_PATH, default_timeout=60)
    test_app.query_params["page"] = "optimize"
    test_app.run()
    ok(test_app)
    return test_app


def _widget(group: Any, suffix: str) -> Any:
    return next(widget for widget in group if str(widget.key).endswith(suffix))


def _plan(app: AppTest) -> dict[str, Any]:
    plan = workspace(app).derived.plan
    assert isinstance(plan, dict)
    return plan


def test_objective_chosen_on_the_page_changes_the_plan(app: AppTest, backend: TestClient) -> None:
    click(app, "Solve route plan")
    fewest = _plan(app)
    assert fewest["status"] == "FEASIBLE"
    assert len(fewest["routes"]) == 1
    assert fewest["plan_id"].startswith("PLAN-")
    assert fewest["optimization_options"]["objective_mode"] == "MINIMIZE_TRUCKS"
    assert fewest["optimization_options"]["time_limit_seconds"] == 10

    go(app, "optimize")
    _widget(app.radio, "-objective").set_value("BALANCE_WORKLOAD")
    _widget(app.slider, "-buffer").set_value(10)
    click(app, "Save settings")
    click(app, "Solve route plan")
    balanced = _plan(app)

    assert balanced["status"] == "FEASIBLE"
    assert len(balanced["routes"]) > 1
    assert (
        balanced["metrics"]["longest_working_seconds"]
        < (fewest["metrics"]["longest_working_seconds"])
    )
    assert balanced["matrix"]["travel_time_factor"] == 1.1
    captions = " | ".join(str(caption.value) for caption in app.caption)
    assert "Made with: Balanced workload, standard search" in captions
    assert "travel-time buffer 10 %" in captions

    scenario_id = workspace(app).scenario["scenario_id"]
    history = backend.get(f"/api/v1/scenarios/{scenario_id}/plans").json()["plans"]
    assert [summary["plan_id"] for summary in history] == [
        balanced["plan_id"],
        fewest["plan_id"],
    ]
