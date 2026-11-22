"""V1.1-M2 Streamlit shell tests through ``AppTest`` with a fake backend client.

Migrated from ``test_streamlit_smoke.py``: the unavailable-backend, startup, workflow,
and sample-loader tests each keep an equivalent here. These tests work in the Advanced
JSON page, which was the first page until M3; ``_start`` opens it through the URL.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend.samples import load_sample_payload
from frontend.state.json_io import ExportMode, scenario_to_json
from frontend.state.workspace import Workspace
from frontend.tests.fake_backend import FakeBackend, install

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
PAGE_HEADERS = {
    "scenario": "Scenario",
    "locations": "Locations",
    "json": "Advanced JSON",
    "fleet": "Fleet",
    "tasks": "Tasks",
    "review": "Review",
    "travel_times": "Travel times",
    "optimize": "Optimize",
    "results": "Results",
}


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


def _start() -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.query_params["page"] = "json"
    app.run()
    assert not app.exception, app.exception
    return app


def _click(app: AppTest, label: str) -> None:
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception, app.exception


def _go(app: AppTest, page: str) -> None:
    app.button(key=f"nav-{page}").click().run()
    assert not app.exception, app.exception
    assert [header.value for header in app.header] == [PAGE_HEADERS[page]]


def _button(app: AppTest, label: str) -> Any:
    return next(button for button in app.button if button.label == label)


def _workspace(app: AppTest) -> Workspace:
    workspace = app.session_state["workspace"]
    assert isinstance(workspace, Workspace)
    return workspace


def _sidebar_text(app: AppTest) -> str:
    return " | ".join(
        [element.value for element in app.sidebar.markdown]
        + [element.value for element in app.sidebar.caption]
    )


def _editor_text(app: AppTest) -> str:
    value = app.text_area(key="json_editor_text").value
    assert isinstance(value, str)
    return value


def _apply_editor_text(app: AppTest, text: str) -> None:
    app.text_area(key="json_editor_text").input(text).run()
    _click(app, "Apply JSON")


def test_unavailable_backend_is_reported_and_editing_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migrated: test_streamlit_app_handles_unavailable_backend."""
    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:9")
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.query_params["page"] = "json"
    app.run()

    assert not app.exception
    assert any("backend is unavailable" in warning.value.casefold() for warning in app.warning)
    assert "Backend unavailable" in _sidebar_text(app)
    assert "⏳ Not checked" in _sidebar_text(app)
    assert _editor_text(app)


def test_shell_starts_on_the_scenario_page_with_every_page_in_the_sidebar(
    backend: FakeBackend,
) -> None:
    """Migrated: test_streamlit_app_starts_with_m8_workflow (first page is Scenario since M3)."""
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.run()
    assert not app.exception, app.exception

    assert any("Manufacturing PO Route Optimizer" in title.value for title in app.title)
    assert [header.value for header in app.header] == ["Scenario"]
    for page in PAGE_HEADERS:
        assert app.button(key=f"nav-{page}") is not None
    assert [caption.value for caption in app.sidebar.caption][:3] == ["Build", "Plan", "Advanced"]
    for label in ("Save scenario", "Open sample", "Start a new empty scenario"):
        assert _button(app, label) is not None
    _go(app, "json")
    for label in ("Apply JSON", "Save scenario", "Load saved scenario", "Load feasible sample"):
        assert _button(app, label) is not None
    assert "Google Maps not configured" in _sidebar_text(app)


@pytest.mark.parametrize("page", list(PAGE_HEADERS))
def test_every_page_renders_and_is_kept_in_the_url(backend: FakeBackend, page: str) -> None:
    app = _start()

    _go(app, page)

    assert app.query_params["page"] == [page]


def test_page_comes_from_the_url_on_a_fresh_session(backend: FakeBackend) -> None:
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.query_params["page"] = "review"
    app.run()

    assert [header.value for header in app.header] == ["Review"]


def test_validation_runs_automatically_once_per_change(backend: FakeBackend) -> None:
    app = _start()
    assert len(backend.validate_calls) == 1
    assert "✅ Valid" in _sidebar_text(app)

    app.run()
    _go(app, "fleet")
    _go(app, "review")
    assert len(backend.validate_calls) == 1

    _go(app, "json")
    edited = json.loads(_editor_text(app))
    edited["name"] = "Renamed"
    _apply_editor_text(app, json.dumps(edited))
    app.run()
    assert len(backend.validate_calls) == 2
    assert _workspace(app).scenario["name"] == "Renamed"


def test_sample_uses_its_travel_times_and_solves(backend: FakeBackend) -> None:
    """Migrated: test_streamlit_workflow_unlocks_validate_matrix_and_solve."""
    app = _start()
    assert "✅ Travel times current" in _sidebar_text(app)

    _go(app, "optimize")
    assert not _button(app, "Solve route plan").disabled
    _click(app, "Solve route plan")

    assert [header.value for header in app.header] == ["Results"]
    # V1.1-M6: the status is said in plain words instead of the backend's code.
    assert any("Every PO is planned" in success.value for success in app.success)
    assert "routing_matrix" in backend.solve_calls[0]
    assert backend.matrix_calls == []
    # Coordinates supplied in JSON keep the OpenStreetMap preview (decision D1).
    assert not any("not drawn on the OpenStreetMap" in info.value for info in app.info)


def test_invalid_scenario_blocks_travel_times_and_solving(backend: FakeBackend) -> None:
    backend.valid = False
    app = _start()
    assert "❌ 1 error(s)" in _sidebar_text(app)

    _go(app, "travel_times")
    assert not any(
        button.label in ("Calculate travel times", "Recalculate travel times")
        and not button.disabled
        for button in app.button
    )
    _go(app, "optimize")
    assert _button(app, "Solve route plan").disabled
    _click(app, "Solve route plan")  # AppTest can click disabled buttons; nothing may happen
    assert backend.solve_calls == []

    backend.valid = True
    _go(app, "review")
    _click(app, "Revalidate")
    _go(app, "optimize")
    assert not _button(app, "Solve route plan").disabled


def test_unapplied_editor_text_and_view_survive_visiting_other_pages(
    backend: FakeBackend,
) -> None:
    app = _start()
    app.radio(key="json_view_mode").set_value(ExportMode.COMPLETE.value).run()
    draft = _editor_text(app).replace('"A"', '"DRAFT"', 1)
    app.text_area(key="json_editor_text").input(draft)

    _go(app, "review")
    _go(app, "json")

    assert _editor_text(app) == draft
    assert app.radio(key="json_view_mode").value == ExportMode.COMPLETE.value
    assert _workspace(app).scenario["scenario_id"] == "A"


def test_a_syntax_error_never_replaces_the_scenario(backend: FakeBackend) -> None:
    app = _start()
    before = _workspace(app).scenario

    _apply_editor_text(app, '{"scenario_id": "B",\n  "tasks": [')

    assert any("JSON line 2" in error.value for error in app.error)
    assert _workspace(app).scenario == before


def test_json_with_errors_never_replaces_a_valid_scenario(backend: FakeBackend) -> None:
    app = _start()
    before = _workspace(app).scenario
    invalid = {**load_sample_payload("A"), "scenario_id": "INVALID-SCENARIO"}

    _apply_editor_text(app, json.dumps(invalid))

    assert any("Nothing was applied" in error.value for error in app.error)
    assert _workspace(app).scenario == before
    assert _editor_text(app) == json.dumps(invalid)


def test_json_with_errors_may_replace_an_invalid_scenario(backend: FakeBackend) -> None:
    app = _start()
    _click(app, "Start empty scenario")
    assert "❌" in _sidebar_text(app)
    invalid = {**load_sample_payload("A"), "scenario_id": "INVALID-SCENARIO"}

    _apply_editor_text(app, json.dumps(invalid))

    assert _workspace(app).scenario["scenario_id"] == "INVALID-SCENARIO"
    _go(app, "review")
    # Since V1.1-M4 the Review page lists each issue with a "Go to" button.
    assert any("CAPACITY_EXCEEDED" in str(element.value) for element in app.markdown)


def test_clean_view_hides_and_complete_view_shows_derived_data(backend: FakeBackend) -> None:
    app = _start()
    clean = _editor_text(app)

    app.radio(key="json_view_mode").set_value(ExportMode.COMPLETE.value).run()
    complete = _editor_text(app)

    assert '"latitude"' not in clean
    assert '"routing_matrix"' not in clean
    assert '"latitude"' in complete
    assert '"routing_matrix"' in complete


def test_applying_clean_json_keeps_coordinates_and_travel_times(backend: FakeBackend) -> None:
    app = _start()
    edited = json.loads(_editor_text(app))
    edited["name"] = "Edited without coordinates"

    _apply_editor_text(app, json.dumps(edited))

    workspace = _workspace(app)
    assert workspace.scenario["name"] == "Edited without coordinates"
    assert all("latitude" in location for location in workspace.scenario["locations"])
    assert "✅ Travel times current" in _sidebar_text(app)
    assert "✏️ Unsaved edits" in _sidebar_text(app)


def test_replacing_an_edited_scenario_asks_first(backend: FakeBackend) -> None:
    app = _start()
    assert not _button(app, "Load fleet shortage sample").disabled
    edited = json.loads(_editor_text(app))
    edited["name"] = "Unsaved work"
    _apply_editor_text(app, json.dumps(edited))

    assert _button(app, "Load fleet shortage sample").disabled
    app.checkbox(key="confirm_discard_edits").check().run()
    _click(app, "Load fleet shortage sample")

    assert _workspace(app).scenario["scenario_id"] == "D"
    assert "No unsaved edits" in _sidebar_text(app)


def test_save_stores_the_complete_scenario_and_load_restores_it(backend: FakeBackend) -> None:
    app = _start()
    edited = json.loads(_editor_text(app))
    edited["name"] = "Saved name"
    _apply_editor_text(app, json.dumps(edited))

    _click(app, "Save scenario")
    assert "No unsaved edits" in _sidebar_text(app)
    saved = backend.saved["A"]
    assert saved["name"] == "Saved name"
    assert "routing_matrix" in saved
    assert "latitude" in saved["locations"][0]

    _click(app, "Load deadline issue sample")
    app.text_input(key="load_scenario_id").input("A").run()
    _click(app, "Load saved scenario")
    assert _workspace(app).scenario["name"] == "Saved name"
    assert "✅ Travel times current" in _sidebar_text(app)


def test_address_only_json_cannot_calculate_travel_times(backend: FakeBackend) -> None:
    app = _start()
    address_only = json.loads(
        scenario_to_json(load_sample_payload("A", include_matrix=False), mode=ExportMode.CLEAN)
    )

    app.radio(key="json_view_mode").set_value(ExportMode.COMPLETE.value).run()
    _apply_editor_text(app, json.dumps(address_only))
    _go(app, "travel_times")

    assert "📍 0 of 7 locations ready · 7 need attention" in _sidebar_text(app)
    assert _button(app, "Calculate travel times").disabled
    _go(app, "locations")
    statuses = app.dataframe[0].value["Status"].tolist()
    assert statuses == ["Not resolved yet"] * 7
    assert backend.matrix_calls == []


def test_no_page_has_a_latitude_or_longitude_input(backend: FakeBackend) -> None:
    app = _start()
    for page in PAGE_HEADERS:
        _go(app, page)
        labels = [widget.label.casefold() for widget in (*app.text_input, *app.number_input)]
        assert not any("latitude" in label or "longitude" in label for label in labels)


def test_sample_loader_returns_a_clean_planning_document() -> None:
    """Migrated: test_sample_loader_returns_clean_planning_payload."""
    payload = load_sample_payload("A")

    assert payload["scenario_id"] == "A"
    assert payload["name"]
    assert "locations_ref" not in payload
    assert "matrix_ref" not in payload
    assert "expected" not in payload
    assert payload["locations"]
    assert payload["routing_matrix"]
