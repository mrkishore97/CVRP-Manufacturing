"""V1.1-M3 pages through ``AppTest`` with a fake backend client.

Plan §14, V1.1-M3 automated checks:

- No form on any page exposes a latitude or longitude input (whole widget tree).
- Add → resolve → confirm → calculate succeeds with a fake client.
- Editing an address resets only that location and makes travel times stale;
  renaming a location changes nothing downstream.
- Rerunning or navigating pages makes zero provider calls.
- Travel times cannot be calculated while any location is unresolved, in review,
  or failed.
- Large-matrix confirmation is required above the threshold.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend.samples import load_sample_payload
from frontend.state.readiness import LocationReadiness, readiness_by_location
from frontend.state.workspace import Workspace
from frontend.tests.fake_backend import FakeBackend, install

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
SAMPLE = load_sample_payload("V11A")
ADDRESS = {location["location_id"]: location["address"] for location in SAMPLE["locations"]}
PAGES = (
    "scenario",
    "locations",
    "fleet",
    "tasks",
    "review",
    "travel_times",
    "optimize",
    "results",
    "json",
)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


@pytest.fixture
def app(backend: FakeBackend) -> AppTest:
    """The app with the address-only sample open on the Locations page."""
    test_app = AppTest.from_file(APP_PATH, default_timeout=30)
    test_app.query_params["page"] = "scenario"
    test_app.run()
    _ok(test_app)
    _select(test_app, "Sample", "V11A")
    _click(test_app, "Open sample")
    assert _workspace(test_app).scenario["scenario_id"] == "V11-A"
    _go(test_app, "locations")
    return test_app


# --- helpers ---------------------------------------------------------------------


def _ok(app: AppTest) -> None:
    assert not app.exception, app.exception


def _click(app: AppTest, label: str) -> None:
    _button(app, label).click().run()
    _ok(app)


def _button(app: AppTest, label: str) -> Any:
    matches = [button for button in app.button if button.label == label]
    assert matches, f"no button {label!r}: {[button.label for button in app.button]}"
    return matches[0]


def _buttons_starting(app: AppTest, prefix: str) -> list[Any]:
    return [button for button in app.button if str(button.label).startswith(prefix)]


def _go(app: AppTest, page: str) -> None:
    app.button(key=f"nav-{page}").click().run()
    _ok(app)


def _select(app: AppTest, label: str, value: Any) -> None:
    box = next(box for box in app.selectbox if box.label == label)
    box.set_value(value).run()
    _ok(app)


def _workspace(app: AppTest) -> Workspace:
    workspace = app.session_state["workspace"]
    assert isinstance(workspace, Workspace)
    return workspace


def _readiness(app: AppTest) -> dict[str, LocationReadiness]:
    return readiness_by_location(_workspace(app).scenario, now=datetime.now(UTC))


def _allow_discard(app: AppTest) -> None:
    """Tick "Discard unsaved edits" on the Scenario page when it is shown."""
    for box in app.checkbox:
        if box.key == "scenario_confirm_discard":
            box.check().run()
            _ok(app)


def _sidebar(app: AppTest) -> str:
    return " | ".join(
        [element.value for element in app.sidebar.markdown]
        + [element.value for element in app.sidebar.caption]
    )


def _texts(app: AppTest) -> str:
    return " | ".join(
        [str(element.value) for element in (*app.markdown, *app.caption, *app.success)]
        + [str(element.value) for element in (*app.info, *app.warning, *app.error)]
    )


def _resolve_all(app: AppTest) -> None:
    pending = _buttons_starting(app, "Resolve addresses (")
    assert pending and not pending[0].disabled
    pending[0].click().run()
    _ok(app)


def _form_input(app: AppTest, label: str, value: str, *, key_part: str | None = None) -> None:
    candidates = [
        widget
        for widget in app.text_input
        if widget.label == label and (key_part is None or key_part in str(widget.key))
    ]
    assert candidates, f"no text input {label!r}"
    candidates[0].input(value)


def _submit(app: AppTest, label: str) -> None:
    _click(app, label)


def _edit_location(app: AppTest, location_id: str, **values: str) -> None:
    app.selectbox(key="locations_edit_id").set_value(location_id).run()
    _ok(app)
    for field, value in values.items():
        app.text_input(key=f"edit-{location_id}-{field}").input(value)
    _submit(app, "Save location")


def _ready_and_calculated(app: AppTest, backend: FakeBackend) -> None:
    _resolve_all(app)
    _go(app, "travel_times")
    _click(app, "Calculate travel times")
    assert "✅ Travel times current" in _sidebar(app)


def _all_widgets(app: AppTest) -> Iterator[Any]:
    for group in (
        app.text_input,
        app.text_area,
        app.number_input,
        app.selectbox,
        app.multiselect,
        app.date_input,
        app.time_input,
        app.checkbox,
        app.radio,
        app.slider,
        app.toggle,
        app.select_slider,
        app.color_picker,
    ):
        yield from group


# --- address-only workflow ---------------------------------------------------------


def test_no_widget_on_any_page_asks_for_latitude_or_longitude(app: AppTest) -> None:
    """Acceptance criterion 6, over the whole widget tree of every page."""
    seen = 0
    for page in PAGES:
        _go(app, page)
        for widget in _all_widgets(app):
            seen += 1
            text = f"{widget.label} {getattr(widget, 'key', '')} {getattr(widget, 'help', '')}"
            assert "latitude" not in text.casefold(), (page, widget.label)
            assert "longitude" not in text.casefold(), (page, widget.label)
            assert "coordinate" not in str(widget.label).casefold(), (page, widget.label)
    assert seen > 20


def test_add_resolve_confirm_calculate_and_solve(app: AppTest, backend: FakeBackend) -> None:
    backend.answer(ADDRESS["HAMILTON-SUPPLIER"], "NEEDS_REVIEW", reasons=("PARTIAL_MATCH",))
    _form_input(app, "Name", "Etobicoke warehouse", key_part="add_location")
    _form_input(app, "Address", "4700 Keele St, Toronto, ON", key_part="add_location")
    _submit(app, "Add location")
    add_fields = [widget for widget in app.text_input if "add_location" in str(widget.key)]
    assert len(add_fields) == 3
    assert all(widget.value == "" for widget in add_fields)  # ready for the next location
    assert "ETOBICOKE-WAREHOUSE" in [
        location["location_id"] for location in _workspace(app).scenario["locations"]
    ]
    assert _buttons_starting(app, "Resolve addresses (8 pending)")

    _resolve_all(app)

    assert len(backend.resolve_calls) == 1
    sent = backend.resolve_calls[0]
    assert len(sent) == 8
    assert sent[0]["location_id"] == "PLANT"  # the plant first: the far-from-plant check
    readiness = _readiness(app)
    assert readiness["HAMILTON-SUPPLIER"] is LocationReadiness.NEEDS_REVIEW
    assert sum(value is LocationReadiness.READY for value in readiness.values()) == 7
    assert any("Needs review (1)" in heading.value for heading in app.subheader)

    _go(app, "travel_times")
    assert not any(
        button.label == "Calculate travel times" and not button.disabled for button in app.button
    )
    assert backend.estimate_calls == []

    _go(app, "locations")
    app.button(key="confirm-HAMILTON-SUPPLIER").click().run()
    _ok(app)
    assert _readiness(app)["HAMILTON-SUPPLIER"] is LocationReadiness.READY
    hamilton = next(
        row
        for row in _workspace(app).scenario["locations"]
        if row["location_id"] == "HAMILTON-SUPPLIER"
    )
    assert hamilton["geocode_confirmed"] is True
    assert hamilton["geocode_status"] == "RESOLVED"

    _go(app, "travel_times")
    assert len(backend.estimate_calls) == 1
    assert any(
        metric.label == "Billable elements" and metric.value == "64" for metric in app.metric
    )
    _click(app, "Calculate travel times")

    assert len(backend.matrix_calls) == 1
    assert len(backend.matrix_calls[0]) == 8
    assert "✅ Travel times current" in _sidebar(app)
    _go(app, "optimize")
    assert not _button(app, "Solve route plan").disabled
    _click(app, "Solve route plan")
    assert [header.value for header in app.header] == ["Results"]
    # Decision D1: address-resolved locations are not drawn on the OpenStreetMap preview.
    assert "not drawn on the OpenStreetMap preview" in _texts(app)


def test_a_new_scenario_is_built_from_the_scenario_and_locations_forms(
    app: AppTest, backend: FakeBackend
) -> None:
    _go(app, "scenario")
    _allow_discard(app)
    _click(app, "Start a new empty scenario")
    assert _workspace(app).scenario["locations"] == []

    _form_input(app, "Scenario name", "Week 50 inbound")
    _submit(app, "Save details")
    assert _workspace(app).scenario["name"] == "Week 50 inbound"
    assert _workspace(app).scenario["scenario_id"] == "WEEK-50-INBOUND"

    _form_input(app, "Plant name", "Main plant")
    _form_input(app, "Plant address", "300 City Centre Dr, Mississauga, ON")
    _submit(app, "Save plant")
    scenario = _workspace(app).scenario
    assert scenario["locations"] == [
        {
            "location_id": "PLANT",
            "name": "Main plant",
            "address": "300 City Centre Dr, Mississauga, ON",
        }
    ]

    _go(app, "locations")
    _form_input(app, "Name", "Acme Steel", key_part="add_location")
    _form_input(app, "Address", "2 Wellington St W, Brampton, ON", key_part="add_location")
    _submit(app, "Add location")
    _resolve_all(app)

    assert set(_readiness(app).values()) == {LocationReadiness.READY}
    assert [row["location_id"] for row in backend.resolve_calls[0]] == ["PLANT", "ACME-STEEL"]


def test_editing_one_address_resets_only_that_location_and_stales_travel_times(
    app: AppTest, backend: FakeBackend
) -> None:
    _ready_and_calculated(app, backend)
    _go(app, "locations")
    before = {row["location_id"]: row for row in _workspace(app).scenario["locations"]}

    _edit_location(app, "VAUGHAN-SUPPLIER", address="3201 Rutherford Rd, Vaughan, ON")

    after = {row["location_id"]: row for row in _workspace(app).scenario["locations"]}
    assert "latitude" not in after["VAUGHAN-SUPPLIER"]
    assert _readiness(app)["VAUGHAN-SUPPLIER"] is LocationReadiness.NOT_RESOLVED
    for location_id, row in before.items():
        if location_id != "VAUGHAN-SUPPLIER":
            assert after[location_id] == row
    assert "⚠️ Travel times stale" in _sidebar(app)

    _resolve_all(app)
    assert [row["location_id"] for row in backend.resolve_calls[-1]] == ["VAUGHAN-SUPPLIER"]


def test_renaming_a_location_changes_nothing_downstream(app: AppTest, backend: FakeBackend) -> None:
    _ready_and_calculated(app, backend)
    _go(app, "optimize")
    _click(app, "Solve route plan")
    _go(app, "locations")
    calls_before = backend.provider_calls

    _edit_location(app, "PLANT", name="Renamed plant")

    assert (
        next(row for row in _workspace(app).scenario["locations"] if row["location_id"] == "PLANT")[
            "name"
        ]
        == "Renamed plant"
    )
    assert "✅ Travel times current" in _sidebar(app)
    assert "✅ Plan FEASIBLE" in _sidebar(app)
    assert backend.provider_calls == calls_before


def test_renaming_a_location_id_keeps_travel_times_current(
    app: AppTest, backend: FakeBackend
) -> None:
    _ready_and_calculated(app, backend)
    _go(app, "locations")

    _edit_location(app, "TORONTO-CUSTOMER", id="TO-CUSTOMER")

    scenario = _workspace(app).scenario
    assert "TO-CUSTOMER" in [row["location_id"] for row in scenario["locations"]]
    assert any(task["destination_location_id"] == "TO-CUSTOMER" for task in scenario["tasks"])
    matrix = _workspace(app).derived.matrix
    assert matrix is not None
    assert "TO-CUSTOMER" in matrix["location_ids"]
    assert "✅ Travel times current" in _sidebar(app)
    assert len(backend.matrix_calls) == 1


def test_rerunning_and_visiting_pages_makes_no_provider_calls(
    app: AppTest, backend: FakeBackend
) -> None:
    _ready_and_calculated(app, backend)
    calls = backend.provider_calls
    estimates = len(backend.estimate_calls)
    resolves = len(backend.resolve_calls)

    for _ in range(3):
        app.run()
        _ok(app)
    for page in (*PAGES, *reversed(PAGES)):
        _go(app, page)

    assert backend.provider_calls == calls
    assert len(backend.resolve_calls) == resolves
    assert len(backend.matrix_calls) == 1
    assert len(backend.estimate_calls) == estimates


@pytest.mark.parametrize(
    ("status", "reasons"),
    [("NOT_RESOLVED", ()), ("NEEDS_REVIEW", ("LOW_PRECISION",)), ("FAILED", ())],
)
def test_travel_times_cannot_be_calculated_while_a_location_is_not_ready(
    app: AppTest, backend: FakeBackend, status: str, reasons: tuple[str, ...]
) -> None:
    if status != "NOT_RESOLVED":
        backend.answer(ADDRESS["MARKHAM-CUSTOMER"], status, reasons=reasons)
        _resolve_all(app)
    _go(app, "travel_times")

    enabled = [
        button
        for button in app.button
        if button.label in ("Calculate travel times", "Recalculate travel times")
        and not button.disabled
    ]
    assert enabled == []
    for label in ("Calculate travel times", "Recalculate travel times"):
        for button in app.button:
            if button.label == label:
                button.click().run()  # AppTest can click disabled buttons
                _ok(app)
    assert backend.matrix_calls == []
    assert "every location resolved" in _texts(app)


def test_a_large_matrix_needs_a_confirmation_tick(app: AppTest, backend: FakeBackend) -> None:
    backend.matrix_confirm_elements = 40  # seven locations: 49 elements
    _resolve_all(app)
    _go(app, "travel_times")

    assert _button(app, "Calculate travel times").disabled
    _click(app, "Calculate travel times")
    assert backend.matrix_calls == []

    tick = next(box for box in app.checkbox if "billable elements" in str(box.label))
    tick.check().run()
    _ok(app)
    assert not _button(app, "Calculate travel times").disabled
    _click(app, "Calculate travel times")
    assert len(backend.matrix_calls) == 1


def test_below_the_threshold_no_confirmation_is_asked(app: AppTest, backend: FakeBackend) -> None:
    _resolve_all(app)
    _go(app, "travel_times")

    assert not any("billable elements" in str(box.label) for box in app.checkbox)
    assert not _button(app, "Calculate travel times").disabled


def test_recalculating_current_travel_times_needs_its_own_confirmation(
    app: AppTest, backend: FakeBackend
) -> None:
    _ready_and_calculated(app, backend)

    assert _button(app, "Recalculate travel times").disabled
    _click(app, "Recalculate travel times")
    assert len(backend.matrix_calls) == 1
    next(box for box in app.checkbox if "accept the Google charge" in str(box.label)).check().run()
    _click(app, "Recalculate travel times")
    assert len(backend.matrix_calls) == 2
    box = next(box for box in app.checkbox if "accept the Google charge" in str(box.label))
    assert box.value is False


def test_a_not_found_address_is_corrected_and_resolved_again(
    app: AppTest, backend: FakeBackend
) -> None:
    backend.answer(ADDRESS["OAKVILLE-CUSTOMER"], "FAILED")
    _resolve_all(app)
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.FAILED
    assert any("Not found (1)" in heading.value for heading in app.subheader)
    assert _buttons_starting(app, "Retry not found (1)")

    app.button(key="correct-failed-OAKVILLE-CUSTOMER").click().run()
    _ok(app)
    assert app.selectbox(key="locations_edit_id").value == "OAKVILLE-CUSTOMER"
    _edit_location(app, "OAKVILLE-CUSTOMER", address="1225 Trafalgar Road, Oakville, Ontario")
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.NOT_RESOLVED

    _resolve_all(app)
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.READY
    assert [row["location_id"] for row in backend.resolve_calls[-1]] == ["OAKVILLE-CUSTOMER"]


def test_one_of_several_matches_can_be_picked(app: AppTest, backend: FakeBackend) -> None:
    backend.answer(
        ADDRESS["MARKHAM-CUSTOMER"],
        "NEEDS_REVIEW",
        reasons=("MULTIPLE_MATCHES",),
        alternatives=("101 Town Centre Blvd, Markham, ON L3R 9W3, Canada",),
    )
    _resolve_all(app)

    app.button(key="alt-MARKHAM-CUSTOMER-0").click().run()
    _ok(app)

    markham = next(
        row
        for row in _workspace(app).scenario["locations"]
        if row["location_id"] == "MARKHAM-CUSTOMER"
    )
    assert markham["address"] == "101 Town Centre Blvd, Markham, ON L3R 9W3, Canada"
    assert _readiness(app)["MARKHAM-CUSTOMER"] is LocationReadiness.NOT_RESOLVED
    assert len(backend.resolve_calls) == 1  # picking an address does not call Google


def test_far_from_plant_match_shows_the_distance(app: AppTest, backend: FakeBackend) -> None:
    backend.answer(ADDRESS["HAMILTON-SUPPLIER"], "NEEDS_REVIEW", reasons=("FAR_FROM_PLANT",))
    _resolve_all(app)

    assert "512 km from the plant" in _texts(app)
    assert "far from the plant" in _texts(app)


def test_a_used_location_is_deleted_only_with_its_dependants(
    app: AppTest, backend: FakeBackend
) -> None:
    app.selectbox(key="locations_edit_id").set_value("MARKHAM-CUSTOMER").run()
    _click(app, "Delete")
    assert any("used by 1 task" in error.value for error in app.error)
    assert "MARKHAM-CUSTOMER" in [
        row["location_id"] for row in _workspace(app).scenario["locations"]
    ]

    app.checkbox(key="delete-dependants-MARKHAM-CUSTOMER").check().run()
    _click(app, "Delete")
    scenario = _workspace(app).scenario
    assert "MARKHAM-CUSTOMER" not in [row["location_id"] for row in scenario["locations"]]
    assert "TASK-0005" not in [task["task_id"] for task in scenario["tasks"]]


def test_the_plant_cannot_be_deleted(app: AppTest) -> None:
    app.selectbox(key="locations_edit_id").set_value("PLANT").run()

    assert not [button for button in app.button if button.label == "Delete"]
    assert "The plant cannot be deleted" in _texts(app)


def test_duplicating_keeps_the_resolution(app: AppTest, backend: FakeBackend) -> None:
    _resolve_all(app)
    app.selectbox(key="locations_edit_id").set_value("TORONTO-CUSTOMER").run()
    _click(app, "Duplicate")

    readiness = _readiness(app)
    assert readiness["TORONTO-CUSTOMER-2"] is LocationReadiness.READY
    assert app.selectbox(key="locations_edit_id").value == "TORONTO-CUSTOMER-2"


def test_locations_are_copied_from_a_saved_scenario(app: AppTest, backend: FakeBackend) -> None:
    _resolve_all(app)
    _go(app, "scenario")
    _click(app, "Save scenario")
    assert "V11-A" in backend.saved
    _allow_discard(app)
    _click(app, "Start a new empty scenario")
    _form_input(app, "Plant name", "Main plant")
    _form_input(app, "Plant address", "300 City Centre Dr, Mississauga, ON L5B 3C1")
    _submit(app, "Save plant")
    _go(app, "locations")

    app.selectbox(key="locations_copy_scenario").set_value("V11-A").run()
    _click(app, "Show its locations")
    app.multiselect(key="locations_copy_pick").set_value(
        ["PLANT", "VAUGHAN-SUPPLIER", "HAMILTON-SUPPLIER"]
    ).run()
    _click(app, "Copy 3 location(s)")

    scenario = _workspace(app).scenario
    assert [row["location_id"] for row in scenario["locations"]] == [
        "PLANT",
        "VAUGHAN-SUPPLIER",
        "HAMILTON-SUPPLIER",
    ]
    readiness = _readiness(app)
    assert readiness["VAUGHAN-SUPPLIER"] is LocationReadiness.READY
    assert "1 skipped because the address is already here" in _texts(app)
    resolves = len(backend.resolve_calls)
    assert resolves == 1


def test_routing_options_make_travel_times_stale_and_are_sent(
    app: AppTest, backend: FakeBackend
) -> None:
    _ready_and_calculated(app, backend)

    _select(app, "Driving times", "TRAFFIC_AWARE")
    _submit(app, "Save routing options")

    assert _workspace(app).scenario["routing_options"] == {"routing_preference": "TRAFFIC_AWARE"}
    assert "⚠️ Travel times stale" in _sidebar(app)
    _click(app, "Calculate travel times")
    assert backend.matrix_options[-1] == {"routing_preference": "TRAFFIC_AWARE"}

    _select(app, "Driving times", "TRAFFIC_UNAWARE")
    _submit(app, "Save routing options")
    assert "routing_options" not in _workspace(app).scenario


def test_google_travel_times_are_not_saved_or_downloaded(
    app: AppTest, backend: FakeBackend
) -> None:
    """Decision D6: Google matrices stay in the session."""
    backend.matrix_source = "google_routes"
    backend.cache_enabled = False
    _resolve_all(app)
    _go(app, "travel_times")
    assert any(
        metric.label == "Backend cache" and metric.value == "Not stored" for metric in app.metric
    )
    _click(app, "Calculate travel times")
    assert "kept only for this session" in _texts(app)

    _go(app, "scenario")
    _click(app, "Save scenario")

    saved = backend.saved["V11-A"]
    assert "routing_matrix" not in saved
    assert all("latitude" in location for location in saved["locations"])
    assert "Travel times from Google are not saved" in _texts(app)
    _go(app, "json")
    app.radio(key="json_view_mode").set_value("complete").run()
    editor = app.text_area(key="json_editor_text").value
    assert '"routing_matrix"' not in str(editor)
    assert '"latitude"' in str(editor)


def test_scenario_details_period_fit_and_defaults(app: AppTest, backend: FakeBackend) -> None:
    _go(app, "scenario")
    scenario = _workspace(app).scenario
    assert scenario["planning_horizon"] == {
        "start": "2026-12-07T00:00:00",
        "end": "2026-12-08T00:00:00",
    }

    _select(app, "Plant timezone", "America/Vancouver")
    _form_input(app, "Scenario name", "Renamed sample")
    _submit(app, "Save details")
    scenario = _workspace(app).scenario
    assert scenario["timezone"] == "America/Vancouver"
    assert scenario["name"] == "Renamed sample"
    assert scenario["scenario_id"] == "V11-A"  # a chosen ID is not replaced

    caption = next(caption.value for caption in app.caption if "Fitting would set" in caption.value)
    assert "2026-12-07 00:00 to 2026-12-08 00:00" in caption

    number = next(widget for widget in app.number_input if widget.label == "Pickup service minutes")
    number.set_value(25)
    _form_input(app, "Capacity unit label", "skids")
    _submit(app, "Save defaults")
    defaults = _workspace(app).scenario["planner_defaults"]
    assert defaults["pickup_service_minutes"] == 25
    assert defaults["capacity_unit"] == "skids"
    assert "✅ Valid" in _sidebar(app)


def test_another_location_can_become_the_plant(app: AppTest) -> None:
    _go(app, "scenario")
    _select(app, "Location", "VAUGHAN-SUPPLIER")
    app.button(key="choose-plant").click().run()
    _ok(app)

    assert _workspace(app).scenario["plant_location_id"] == "VAUGHAN-SUPPLIER"


def test_the_address_only_sample_opens_without_coordinates_or_travel_times(
    app: AppTest,
) -> None:
    workspace = _workspace(app)
    assert workspace.derived.matrix is None
    assert all("latitude" not in row for row in workspace.scenario["locations"])
    assert "📍 0 of 7 locations ready · 7 need attention" in _sidebar(app)
    assert _buttons_starting(app, "Resolve addresses (7 pending)")
    assert json.loads(json.dumps(workspace.scenario)) == SAMPLE
