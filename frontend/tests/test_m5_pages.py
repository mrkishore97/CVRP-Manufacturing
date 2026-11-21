"""V1.1-M5 Optimize page through ``AppTest`` with a fake backend client.

Settings are stored in the scenario (only what differs from the defaults), make the plan
stale but never the travel times, call no provider, and reach the solve with the time
limit the client waits for. Results say how the plan was made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend.tests.fake_backend import FakeBackend, install
from frontend.tests.form_driver import click, go, ok, scenario

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


@pytest.fixture
def app(backend: FakeBackend) -> AppTest:
    """Sample A (with its travel times) open on the Optimize page."""
    test_app = AppTest.from_file(APP_PATH, default_timeout=30)
    test_app.query_params["page"] = "optimize"
    test_app.run()
    ok(test_app)
    return test_app


def _widget(group: Any, suffix: str) -> Any:
    matches = [widget for widget in group if str(widget.key).endswith(suffix)]
    assert matches, f"no widget ending {suffix!r}"
    return matches[0]


def _sidebar(app: AppTest) -> str:
    return " | ".join(str(element.value) for element in app.sidebar.markdown)


def _texts(app: AppTest) -> str:
    groups = (app.caption, app.markdown, app.success, app.info, app.warning)
    return " | ".join(str(element.value) for group in groups for element in group)


def test_settings_are_stored_minimally_and_make_only_the_plan_stale(
    app: AppTest, backend: FakeBackend
) -> None:
    click(app, "Solve route plan")
    assert "✅ Plan FEASIBLE" in _sidebar(app)
    go(app, "optimize")

    _widget(app.radio, "-objective").set_value("BALANCE_WORKLOAD")
    _widget(app.slider, "-buffer").set_value(20)
    click(app, "Save settings")

    assert scenario(app)["optimization_options"] == {
        "objective_mode": "BALANCE_WORKLOAD",
        "travel_time_factor": 1.2,
    }
    sidebar = _sidebar(app)
    assert "✅ Travel times current" in sidebar
    assert "✅ Plan" not in sidebar
    assert backend.provider_calls == 0
    assert "Balanced workload, standard search" in _texts(app)


def test_saving_the_defaults_changes_nothing(app: AppTest) -> None:
    click(app, "Save settings")

    assert "optimization_options" not in scenario(app)
    assert any("Nothing changed" in str(element.value) for element in app.info)


def test_the_time_limit_is_bounded_by_the_server_and_sent_with_the_solve(
    app: AppTest, backend: FakeBackend
) -> None:
    slider = _widget(app.slider, "-time-limit")
    assert (slider.min, slider.max, slider.value) == (1, 120, 10)

    _widget(app.radio, "-effort").set_value("THOROUGH")
    _widget(app.slider, "-time-limit").set_value(30)
    click(app, "Save settings")
    assert "Thorough search takes about 30 s, and up to 60 s" in _texts(app)

    click(app, "Solve route plan")

    assert backend.solve_time_limits == [30]
    assert backend.solve_calls[-1]["optimization_options"] == {
        "search_effort": "THOROUGH",
        "time_limit_seconds": 30,
    }
    assert app.session_state["current_page"] == "results"
    assert "Made with: Fewest trucks, thorough search, time limit 30 s" in _texts(app)


def test_the_page_states_that_no_setting_relaxes_a_hard_rule(app: AppTest) -> None:
    assert "No setting here relaxes a hard rule" in _texts(app)
    labels = {str(radio.label) for radio in app.radio}
    assert {"Objective", "Search effort", "Balance strength"} <= labels
    assert any(str(box.label) == "Cost of an extra truck (km)" for box in app.number_input)


def test_an_optimization_issue_on_review_links_to_the_optimize_page(
    app: AppTest, backend: FakeBackend
) -> None:
    backend.extra_issues = [
        {
            "severity": "ERROR",
            "code": "INVALID_VALUE",
            "message": "Too long.",
            "field": "optimization_options.time_limit_seconds",
            "section": "optimization_options",
        }
    ]
    go(app, "review")
    click(app, "Revalidate")
    assert any(
        str(expander.label).startswith("Optimization settings: 1 error(s)")
        for expander in app.expander
    )

    app.button(key="review-go-optimization_options-0").click().run()
    ok(app)
    assert app.session_state["current_page"] == "optimize"
