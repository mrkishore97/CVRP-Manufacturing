"""V1.1-M6 pages through ``AppTest`` with a fake backend.

Results in planner language, plan comparison and earlier plans, drafts restored after
a simulated session loss, and scenario management: the overwrite guard, Save as,
Duplicate, and Delete.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend.state.results import STATUS_TEXT
from frontend.tests.fake_backend import FakeBackend, install
from frontend.tests.form_driver import click, go, ok, scenario, workspace
from frontend.tests.plan_fixtures import partial_plan

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


def _start(page: str = "scenario", *, scenario_param: str | None = None) -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.query_params["page"] = page
    if scenario_param is not None:
        app.query_params["scenario"] = scenario_param
    app.run()
    ok(app)
    return app


def _texts(app: AppTest) -> str:
    groups = (app.caption, app.markdown, app.success, app.info, app.warning, app.error)
    return " | ".join(str(element.value) for group in groups for element in group)


def _sidebar(app: AppTest) -> str:
    groups = (app.sidebar.markdown, app.sidebar.caption)
    return " | ".join(str(element.value) for group in groups for element in group)


def _frames(app: AppTest) -> list[Any]:
    return [frame.value for frame in app.dataframe]


def _cells(app: AppTest) -> set[str]:
    return {str(cell) for frame in _frames(app) for cell in frame.to_numpy().ravel()}


def _rename(app: AppTest, name: str) -> None:
    next(box for box in app.text_input if box.label == "Scenario name").input(name)
    click(app, "Save details")


# --- Results -------------------------------------------------------------------------


def test_results_speak_the_planners_language(backend: FakeBackend) -> None:
    backend.next_plan = partial_plan()
    app = _start("optimize")
    click(app, "Solve route plan")
    assert app.session_state["current_page"] == "results"

    assert STATUS_TEXT["PARTIALLY_FEASIBLE"][1] in [warning.value for warning in app.warning]
    assert {metric.label: metric.value for metric in app.metric}["POs planned"] == "3 of 6"
    assert "Not planned (3)" in [subheader.value for subheader in app.subheader]
    cells = _cells(app)
    assert {"Fixture Supplier A", "Fixture Hub A", "PO-PICK-001", "3 Important"} <= cells
    assert not {"SUPPLIER_A", "HUB_A", "TASK-PICK-001"} & cells  # no internal IDs
    texts = _texts(app)
    assert "Made with: Balanced workload, thorough search" in texts
    assert "times are plant-local (America/Toronto)" in texts
    assert "Travel times: Google Maps" in texts  # the plan's travel times came from Google
    links = app.get("link_button")
    assert len(links) == 2  # one per route; neither needs splitting
    downloads = [element.proto.label for element in app.get("download_button")]
    assert "Download run sheets (XLSX)" in downloads
    assert "Download plan workbook XLSX" in downloads


def test_plans_are_compared_and_an_earlier_plan_can_be_viewed(backend: FakeBackend) -> None:
    backend.next_plan = partial_plan()
    app = _start("optimize")
    click(app, "Solve route plan")
    backend.next_plan = partial_plan(
        status="FEASIBLE",
        unscheduled_task_ids=[],
        diagnostics=[],
        optimization_options={"objective_mode": "MINIMIZE_TRUCKS", "time_limit_seconds": 10},
    )
    go(app, "optimize")
    click(app, "Solve route plan")

    compare = _frames(app)[-1]
    assert list(compare["Plan ID"]) == ["PLAN-2", "PLAN-1"]
    assert list(compare["Inputs"]) == ["This plan", "Same"]
    assert list(compare["Objective"]) == ["Fewest trucks", "Balanced workload"]
    assert list(compare["Not planned"]) == [0, 3]

    app.selectbox(key="history-choice").set_value("PLAN-1").run()
    click(app, "View this plan")
    assert any("Earlier plan made" in warning.value for warning in app.warning)
    assert "Not planned (3)" in [subheader.value for subheader in app.subheader]
    click(app, "Back to the current plan")
    assert not any("Earlier plan made" in warning.value for warning in app.warning)
    assert STATUS_TEXT["FEASIBLE"][1] in [success.value for success in app.success]


def test_a_stale_plan_is_hidden_but_stays_in_the_comparison(backend: FakeBackend) -> None:
    app = _start("optimize")
    click(app, "Solve route plan")
    go(app, "scenario")
    next(box for box in app.date_input if box.label == "End date").set_value(date(2026, 6, 25))
    click(app, "Save details")
    go(app, "results")
    assert any("The last plan is hidden" in warning.value for warning in app.warning)
    compare = _frames(app)[-1]
    assert list(compare["Plan ID"]) == ["PLAN-1"]
    assert not app.get("download_button")  # nothing exports as current


# --- drafts ----------------------------------------------------------------------------


def test_unsaved_edits_survive_a_session_loss_and_can_be_restored(backend: FakeBackend) -> None:
    first = _start()
    _rename(first, "Edited before the refresh")
    assert first.query_params["scenario"] == ["A"]
    assert backend.drafts["A"]["payload"]["name"] == "Edited before the refresh"
    assert "kept if the page reloads" in _sidebar(first)

    # A browser refresh: a new session with the same URL and the same backend.
    second = _start(scenario_param="A")
    assert scenario(second)["name"] == "Three-truck feasible mixed plan"
    assert any(
        "Unsaved changes to A (Edited before the refresh)" in warning.value
        for warning in second.warning
    )
    puts_before = len(backend.draft_puts)
    second.run()
    assert len(backend.draft_puts) == puts_before  # nothing overwrites it while offered

    second.button(key="draft-restore").click().run()
    ok(second)
    assert scenario(second)["name"] == "Edited before the refresh"
    assert "✏️ Unsaved edits" in _sidebar(second)
    assert workspace(second).derived.matrix is not None  # sample travel times came back
    assert not any("Unsaved changes to A" in warning.value for warning in second.warning)


def test_a_kept_draft_can_be_discarded(backend: FakeBackend) -> None:
    first = _start()
    _rename(first, "Throw away")
    second = _start(scenario_param="A")
    second.button(key="draft-discard").click().run()
    ok(second)
    assert "A" not in backend.drafts
    assert scenario(second)["name"] == "Three-truck feasible mixed plan"
    assert "Discarded the kept changes." in [info.value for info in second.info]


def test_a_refresh_reopens_the_saved_scenario_named_in_the_url(backend: FakeBackend) -> None:
    saved = deepcopy(_start().session_state["workspace"].scenario)
    saved["scenario_id"] = "WEEK-26"
    saved["name"] = "Week 26"
    backend.saved["WEEK-26"] = saved
    backend.expired_on_load = 2
    app = _start(scenario_param="WEEK-26")
    assert scenario(app)["name"] == "Week 26"
    assert workspace(app).derived.saved_scenario_id == "WEEK-26"
    assert "2 location(s) had coordinates older than 30 days" in _texts(app)
    assert not backend.draft_puts  # opening is not an edit


def test_saving_deletes_the_draft(backend: FakeBackend) -> None:
    app = _start()
    _rename(app, "Edited")
    assert "A" in backend.drafts
    click(app, "Save scenario")
    assert "A" not in backend.drafts
    assert backend.saved["A"]["name"] == "Edited"


# --- scenario management -------------------------------------------------------------


def test_save_asks_before_replacing_a_different_saved_scenario(backend: FakeBackend) -> None:
    backend.saved["A"] = {"scenario_id": "A", "name": "Someone else's plan"}
    app = _start()
    click(app, "Save scenario")
    assert backend.save_calls == [("A", False)]
    assert backend.saved["A"]["name"] == "Someone else's plan"
    assert any("Another saved scenario already uses the ID A" in w.value for w in app.warning)

    click(app, "Keep the saved one")
    assert backend.saved["A"]["name"] == "Someone else's plan"
    assert not any("Another saved scenario" in w.value for w in app.warning)

    click(app, "Save scenario")
    click(app, "Replace saved A")
    assert backend.save_calls[-1] == ("A", True)
    assert backend.saved["A"]["name"] == "Three-truck feasible mixed plan"
    # From now on this session owns the saved copy: Save replaces it without asking.
    _rename(app, "Edited")
    click(app, "Save scenario")
    assert backend.save_calls[-1] == ("A", True)
    assert backend.saved["A"]["name"] == "Edited"


def test_save_as_never_overwrites_and_continues_in_the_copy(backend: FakeBackend) -> None:
    backend.saved["TAKEN"] = {"scenario_id": "TAKEN", "name": "Keep me"}
    app = _start()
    app.text_input(key="save-as-id").input("TAKEN")
    click(app, "Save as")
    assert any("TAKEN already exists" in error.value for error in app.error)
    assert backend.saved["TAKEN"] == {"scenario_id": "TAKEN", "name": "Keep me"}

    app.text_input(key="save-as-name").input("Week 26 inbound")
    app.text_input(key="save-as-id").input("WEEK-26")
    click(app, "Save as")
    assert backend.saved["WEEK-26"]["name"] == "Week 26 inbound"
    assert scenario(app)["scenario_id"] == "WEEK-26"
    assert workspace(app).derived.saved_scenario_id == "WEEK-26"
    assert app.query_params["scenario"] == ["WEEK-26"]
    assert "Saved as WEEK-26" in " | ".join(success.value for success in app.success)


def test_duplicate_copies_a_saved_scenario_without_opening_it(backend: FakeBackend) -> None:
    backend.saved["WEEK-26"] = {"scenario_id": "WEEK-26", "name": "Week 26", "tasks": []}
    app = _start()
    app.selectbox(key="saved-choice").set_value("WEEK-26").run()
    assert app.text_input(key="duplicate-id").value == "COPY-OF-WEEK-26"
    click(app, "Duplicate")
    assert backend.saved["COPY-OF-WEEK-26"]["name"] == "Copy of Week 26"
    assert backend.save_calls[-1] == ("COPY-OF-WEEK-26", False)
    assert scenario(app)["scenario_id"] == "A"  # still working on what was open


def test_delete_needs_a_confirmation_and_leaves_the_open_scenario_unsaved(
    backend: FakeBackend,
) -> None:
    app = _start()
    click(app, "Save scenario")
    app.selectbox(key="saved-choice").set_value("A").run()
    delete = app.button(key="delete-saved")
    assert delete.disabled
    app.checkbox(key="delete-confirm").check().run()
    app.button(key="delete-saved").click().run()
    ok(app)
    assert "A" not in backend.saved
    assert workspace(app).derived.saved_scenario_id is None
    assert "✏️ Unsaved edits" in _sidebar(app)
    assert "Deleted saved scenario A" in " | ".join(success.value for success in app.success)
