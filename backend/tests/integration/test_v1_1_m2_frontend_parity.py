"""V1.1-M2 parity: the new Streamlit shell, driving the real backend, reproduces v1.0.

Each frozen Version 1.0 payload (``sample_data/v1_0_compat``) is pasted into the
Advanced JSON editor of the real ``frontend/streamlit_app.py`` and applied; the app
validates it automatically, uses its embedded matrix, and solves. The plan must match
the results recorded from Version 1.0. The backend runs in-process; the frontend still
reaches it only over HTTP through ``BackendClient``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain.geocoding import address_fingerprint
from frontend import api_client
from frontend.state.readiness import geocode_fingerprint
from frontend.state.workspace import Workspace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
COMPAT_DIR = PROJECT_ROOT / "sample_data" / "v1_0_compat"
EXPECTED = json.loads((COMPAT_DIR / "expected_default_results.json").read_text("utf-8"))[
    "scenarios"
]


@pytest.fixture(scope="module")
def http_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[api_client.BackendClient]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path_factory.mktemp("m2_parity") / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    with TestClient(create_app(Settings(**values))) as test_client:
        yield api_client.BackendClient("http://testserver", transport=test_client._transport)


@pytest.fixture
def app(http_client: api_client.BackendClient, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setattr(
        api_client.BackendClient, "from_environment", classmethod(lambda cls: http_client)
    )
    test_app = AppTest.from_file(APP_PATH, default_timeout=60)
    test_app.query_params["page"] = "json"  # the first page until M3; Scenario since
    test_app.run()
    assert not test_app.exception, test_app.exception
    return test_app


def _click(app: AppTest, label: str) -> None:
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception, app.exception


def _go(app: AppTest, page: str) -> None:
    app.button(key=f"nav-{page}").click().run()
    assert not app.exception, app.exception


def _workspace(app: AppTest) -> Workspace:
    workspace = app.session_state["workspace"]
    assert isinstance(workspace, Workspace)
    return workspace


def _apply_payload(app: AppTest, letter: str) -> None:
    text = (COMPAT_DIR / f"scenario_{letter.lower()}.json").read_text(encoding="utf-8")
    app.text_area(key="json_editor_text").input(text).run()
    _click(app, "Apply JSON")


def _sidebar(app: AppTest) -> str:
    return " | ".join(element.value for element in app.sidebar.markdown)


@pytest.mark.parametrize("letter", [letter for letter in "ACDEF"])
def test_version_1_0_payload_loads_validates_uses_its_matrix_and_solves_identically(
    app: AppTest, letter: str
) -> None:
    _apply_payload(app, letter)
    workspace = _workspace(app)
    assert workspace.scenario["scenario_id"] == letter
    assert "✅ Valid" in _sidebar(app)
    assert "✅ Travel times current" in _sidebar(app)

    _go(app, "optimize")
    _click(app, "Solve route plan")

    plan = _workspace(app).derived.plan
    assert plan is not None
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
    expected = {key: value for key, value in EXPECTED[letter].items() if key != "http_status"}
    assert observed == expected
    assert any(m.label == "Plan status" and m.value == expected["status"] for m in app.metric)


def test_version_1_0_payload_b_is_refused_over_a_valid_scenario(app: AppTest) -> None:
    _apply_payload(app, "B")

    assert any("Nothing was applied" in error.value for error in app.error)
    assert any("CAPACITY_EXCEEDED" in frame.value["code"].tolist() for frame in app.dataframe)
    assert _workspace(app).scenario["scenario_id"] == "A"


def test_version_1_0_payload_b_loads_over_an_invalid_scenario_and_cannot_solve(
    app: AppTest,
) -> None:
    _click(app, "Start empty scenario")
    _apply_payload(app, "B")
    assert _workspace(app).scenario["scenario_id"] == "B"

    _go(app, "review")
    assert any("CAPACITY_EXCEEDED" in frame.value["code"].tolist() for frame in app.dataframe)
    _go(app, "optimize")
    assert next(b for b in app.button if b.label == "Solve route plan").disabled


@pytest.mark.parametrize(
    ("address", "region"),
    [
        ("200 Supplier Avenue, Vaughan, ON", "ca"),
        ("  200   SUPPLIER avenue,\tVaughan , ON ", "CA"),
        ("100 Fixture Plant Road, Toronto, ON", None),
        ("Café Économie, 1 Rue Principale, Montréal", "ca"),
        ("1600 Amphitheatre Pkwy", ""),
    ],
)
def test_frontend_fingerprint_mirrors_the_backend(address: str, region: str | None) -> None:
    assert geocode_fingerprint(address, region) == address_fingerprint(address, region)
