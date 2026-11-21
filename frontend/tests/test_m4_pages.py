"""V1.1-M4 pages through ``AppTest`` with a fake backend client.

Plan §14, V1.1-M4 checks covered here: trucks, shifts, and all three task movements
are created through forms; the shift generator flags existing and overlapping shifts;
choosing a movement fills and locks the plant end; an import is applied in the chosen
mode, all or nothing; Review groups issues and links to the row.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend.state.scenario_state import find_row, rows
from frontend.tests.fake_backend import FakeBackend, install
from frontend.tests.form_driver import (
    add_task,
    add_truck,
    choose_movement,
    click,
    generate_shifts,
    go,
    ok,
    scenario,
    workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
DAY = date(2026, 12, 7)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


@pytest.fixture
def app(backend: FakeBackend) -> AppTest:
    """The address-only sample (V11-A) open on the Fleet page."""
    test_app = AppTest.from_file(APP_PATH, default_timeout=30)
    test_app.query_params["page"] = "scenario"
    test_app.run()
    ok(test_app)
    next(box for box in test_app.selectbox if box.label == "Sample").set_value("V11A").run()
    click(test_app, "Open sample")
    go(test_app, "fleet")
    return test_app


def _messages(app: AppTest) -> str:
    return " | ".join(
        str(element.value) for group in (app.success, app.warning, app.error) for element in group
    )


# --- fleet --------------------------------------------------------------------------


def test_trucks_are_added_edited_duplicated_and_deleted_through_forms(app: AppTest) -> None:
    add_truck(app, name="Reefer 9", capacity=8.5, tags="refrigerated", max_time="9:30", max_km=250)

    assert find_row(scenario(app), "vehicles", "REEFER-9") == {
        "vehicle_id": "REEFER-9",
        "name": "Reefer 9",
        "capacity": 8.5,
        "enabled": True,
        "tags": ["REFRIGERATED"],
        "maximum_route_duration_seconds": 34_200,
        "maximum_route_distance_meters": 250_000,
    }
    assert app.selectbox(key="fleet_truck_edit_id").value == "REEFER-9"

    prefix = next(
        str(widget.key)[: -len("-name")]
        for widget in app.text_input
        if str(widget.key).startswith("truck-edit-") and str(widget.key).endswith("-name")
    )
    app.text_input(key=f"{prefix}-max-time").input("")
    app.number_input(key=f"{prefix}-capacity").set_value(9.0)
    click(app, "Save truck")
    edited = find_row(scenario(app), "vehicles", "REEFER-9")
    assert edited is not None
    assert edited["capacity"] == 9
    assert "maximum_route_duration_seconds" not in edited

    click(app, "Duplicate truck")
    assert find_row(scenario(app), "vehicles", "REEFER-9-2") is not None

    app.selectbox(key="fleet_truck_edit_id").set_value("TRUCK-1").run()
    click(app, "Delete truck")
    assert find_row(scenario(app), "vehicles", "TRUCK-1") is not None  # it has a shift
    assert "Tick the box" in _messages(app)
    app.checkbox(key="delete-truck-shifts-TRUCK-1").check().run()
    click(app, "Delete truck")
    assert find_row(scenario(app), "vehicles", "TRUCK-1") is None
    assert all(shift["vehicle_id"] != "TRUCK-1" for shift in rows(scenario(app), "vehicle_shifts"))


def test_the_generator_adds_only_new_shifts_and_extends_the_period(app: AppTest) -> None:
    generate_shifts(
        app,
        trucks=["TRUCK-1", "TRUCK-2"],
        first=DAY,
        last=date(2026, 12, 13),
        weekdays=(0, 1, 2),
        end_location="VAUGHAN-SUPPLIER",
        apply=False,
    )
    statuses = [str(value) for value in app.dataframe[-1].value["Status"]]
    assert statuses.count("New") == 4
    assert sum(status.startswith("Already exists") for status in statuses) == 2

    app.button(key="generator-apply").click().run()
    ok(app)

    shifts = {shift["shift_id"]: shift for shift in rows(scenario(app), "vehicle_shifts")}
    assert {"TRUCK-1-20261208", "TRUCK-2-20261209"} <= set(shifts)
    assert shifts["TRUCK-1-20261208"]["end_location_id"] == "VAUGHAN-SUPPLIER"
    assert "TRUCK-1-20261207" in shifts and "end_location_id" not in shifts["TRUCK-1-20261207"]
    assert scenario(app)["planning_horizon"]["end"] == "2026-12-10T00:00:00"
    assert "4 shift(s); 2 skipped" in _messages(app)
    assert "extended" in _messages(app)


def test_a_single_shift_and_copy_to_the_next_day(app: AppTest) -> None:
    prefix = "shift-add-0"
    app.selectbox(key=f"{prefix}-truck").set_value("TRUCK-3")
    app.date_input(key=f"{prefix}-date").set_value(DAY)
    app.time_input(key=f"{prefix}-start").set_value(time(16, 0))
    app.time_input(key=f"{prefix}-end").set_value(time(2, 0))
    app.text_input(key=f"{prefix}-id").input("TRUCK-3-NIGHT")
    click(app, "Add shift")

    night = find_row(scenario(app), "vehicle_shifts", "TRUCK-3-NIGHT")
    assert night is not None
    assert (night["start"], night["end"]) == ("2026-12-07T16:00:00", "2026-12-08T02:00:00")
    assert app.selectbox(key="fleet_shift_edit_id").value == "TRUCK-3-NIGHT"
    overlaps = [str(value) for value in app.dataframe[1].value["Check"]]
    assert "Overlaps TRUCK-3-20261207" in overlaps

    click(app, "Copy to the next day")
    assert find_row(scenario(app), "vehicle_shifts", "TRUCK-3-20261208") is not None


# --- tasks --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("movement", "locked", "free"),
    [("PICKUP", "to", ["from"]), ("DROP", "from", ["to"]), ("PICKUP_DROP", None, ["from", "to"])],
)
def test_choosing_a_movement_fills_and_locks_the_plant_end(
    app: AppTest, movement: str, locked: str | None, free: list[str]
) -> None:
    go(app, "tasks")
    prefix = choose_movement(app, movement)

    keys = {str(box.key): box for box in app.selectbox}
    if locked:
        box = keys[f"{prefix}-{locked}-plant"]
        assert box.disabled
        assert box.value == "PLANT"
        assert box.options == ["Main plant (stand-in: Mississauga Civic Centre) (PLANT)"]
    else:
        assert not any(key.endswith("-plant") and key.startswith(prefix) for key in keys)
    for side in free:
        picker = keys[f"{prefix}-{side}"]
        assert not picker.disabled
        assert all("(PLANT)" not in option for option in picker.options)


def test_all_three_movements_are_added_through_the_form(app: AppTest) -> None:
    go(app, "tasks")
    before = len(rows(scenario(app), "tasks"))
    add_task(
        app,
        movement="PICKUP",
        po="PO-F1",
        origin="BRAMPTON-SUPPLIER",
        quantity=2.5,
        day=DAY,
        priority=5,
    )
    add_task(app, movement="DROP", po="PO-F2", destination="TORONTO-CUSTOMER", quantity=3, day=DAY)
    add_task(
        app,
        movement="PICKUP_DROP",
        po="PO-F3",
        origin="VAUGHAN-SUPPLIER",
        destination="MARKHAM-CUSTOMER",
        quantity=4,
        day=DAY,
        ready=time(9, 0),
        due=time(15, 30),
    )

    tasks = {task["po_number"]: task for task in rows(scenario(app), "tasks")}
    assert len(tasks) == before + 3
    assert (tasks["PO-F1"]["origin_location_id"], tasks["PO-F1"]["destination_location_id"]) == (
        "BRAMPTON-SUPPLIER",
        "PLANT",
    )
    assert tasks["PO-F1"]["quantity"] == 2.5
    assert tasks["PO-F1"]["priority"] == 5
    assert tasks["PO-F1"]["pickup_service_minutes"] == 15  # the sample's planner default
    assert tasks["PO-F2"]["origin_location_id"] == "PLANT"
    assert tasks["PO-F3"]["task_type"] == "PICKUP_DROP"
    assert tasks["PO-F3"]["due_at"] == "2026-12-07T15:30:00"
    assert tasks["PO-F3"]["task_id"] == "TASK-0009"
    assert app.selectbox(key="tasks_edit_id").value == "TASK-0009"


def test_a_task_needing_tags_no_truck_has_is_warned_at_once(app: AppTest) -> None:
    go(app, "fleet")
    add_truck(app, name="Reefer", capacity=6, tags="REFRIGERATED")
    go(app, "tasks")
    add_task(
        app,
        movement="DROP",
        po="PO-COLD",
        destination="OAKVILLE-CUSTOMER",
        quantity=7,
        day=DAY,
        tags=["REFRIGERATED"],
    )

    assert "No enabled truck with these tags can carry 7" in _messages(app)


def test_editing_and_duplicating_a_task(app: AppTest) -> None:
    go(app, "tasks")
    app.selectbox(key="tasks_edit_id").set_value("TASK-0002").run()
    ok(app)
    prefix = next(
        str(widget.key)[: -len("-po")]
        for widget in app.text_input
        if str(widget.key).startswith("task-edit-") and str(widget.key).endswith("-po")
    )
    app.text_input(key=f"{prefix}-po").input("PO-EDITED")
    app.selectbox(key=f"{prefix}-priority").set_value(4)
    click(app, "Save task")
    task = find_row(scenario(app), "tasks", "TASK-0002")
    assert task is not None
    assert (task["po_number"], task["priority"]) == ("PO-EDITED", 4)

    click(app, "Duplicate task")
    copy_id = app.selectbox(key="tasks_edit_id").value
    copy = find_row(scenario(app), "tasks", str(copy_id))
    assert copy is not None
    assert copy["po_number"] == "PO-EDITED (copy)"
    assert copy["origin_location_id"] == task["origin_location_id"]

    click(app, "Delete task")
    assert find_row(scenario(app), "tasks", str(copy_id)) is None


def _preview_row(row_number: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_number": row_number,
        "task_id": None,
        "po_number": f"PO-IMP-{row_number}",
        "task_type": "DROP",
        "origin_location_id": "PLANT",
        "destination_location_id": "MARKHAM-CUSTOMER",
        "quantity": 2,
        "ready_at": "2026-12-07T08:00:00",
        "due_at": "2026-12-07T15:00:00",
        "due_event": "DELIVERY_COMPLETE",
        "pickup_service_minutes": 15,
        "delivery_service_minutes": 15,
        "priority": 1,
        "required_vehicle_tags": [],
        "notes": None,
    }
    row.update(overrides)
    return row


def _checked_file(app: AppTest, *preview_rows: dict[str, Any]) -> None:
    """The state after "Check file" (``AppTest`` cannot upload files)."""
    app.session_state["tasks_import_preview"] = {
        "file": "tasks.xlsx",
        "valid": True,
        "rows": list(preview_rows),
        "issues": [],
    }
    app.run()
    ok(app)


def test_a_checked_import_is_applied_in_the_chosen_mode(app: AppTest) -> None:
    go(app, "tasks")
    _checked_file(
        app, _preview_row(2, task_id="TASK-0001", quantity=9), _preview_row(3, priority=3)
    )
    app.radio(key="tasks_import_mode").set_value("update").run()
    click(app, "Import 2 task(s)")

    tasks = {task["task_id"]: task for task in rows(scenario(app), "tasks")}
    assert tasks["TASK-0001"]["quantity"] == 9
    assert tasks["TASK-0001"]["task_type"] == "DROP"
    assert "TASK-0007" in tasks and tasks["TASK-0007"]["priority"] == 3
    assert "1 added, 1 updated" in _messages(app)

    # The imported row can then be edited like any other.
    app.selectbox(key="tasks_edit_id").set_value("TASK-0007").run()
    prefix = next(
        str(widget.key)[: -len("-po")]
        for widget in app.text_input
        if str(widget.key).startswith("task-edit-") and str(widget.key).endswith("-po")
    )
    app.number_input(key=f"{prefix}-quantity").set_value(5.0)
    click(app, "Save task")
    assert find_row(scenario(app), "tasks", "TASK-0007")["quantity"] == 5  # type: ignore[index]


def test_a_failing_import_changes_nothing(app: AppTest) -> None:
    go(app, "tasks")
    before = scenario(app)
    _checked_file(app, _preview_row(2), _preview_row(3, task_id="TASK-0002"))
    click(app, "Import 2 task(s)")  # append refuses an existing ID

    assert scenario(app) == before
    assert "Nothing was imported" in _messages(app)


def test_replace_import_keeps_only_the_file_rows(app: AppTest) -> None:
    go(app, "tasks")
    _checked_file(app, _preview_row(2, task_id="ONLY-1"))
    app.radio(key="tasks_import_mode").set_value("replace").run()
    click(app, "Import 1 task(s)")

    assert [task["task_id"] for task in rows(scenario(app), "tasks")] == ["ONLY-1"]


# --- review -------------------------------------------------------------------------


def test_review_groups_issues_and_go_to_opens_the_row(app: AppTest, backend: FakeBackend) -> None:
    backend.extra_issues = [
        {
            "severity": "WARNING",
            "code": "VEHICLE_WITHOUT_SHIFT",
            "message": "Truck TRUCK-2 has no shift.",
            "section": "vehicles",
            "item_id": "TRUCK-2",
        },
        {
            "severity": "WARNING",
            "code": "TASK_WINDOW_OUTSIDE_SHIFTS",
            "message": "PO cannot be planned.",
            "section": "tasks",
            "item_id": "TASK-0004",
            "task_id": "TASK-0004",
        },
    ]
    go(app, "tasks")  # an edit there is not needed; revalidate on Review
    go(app, "review")
    click(app, "Revalidate")

    headings = [str(expander.label) for expander in app.expander]
    assert "Trucks: 0 error(s), 1 warning(s)" in headings
    assert "Tasks: 0 error(s), 1 warning(s)" in headings

    app.button(key="review-go-tasks-0").click().run()
    ok(app)
    assert app.session_state["current_page"] == "tasks"
    assert app.selectbox(key="tasks_edit_id").value == "TASK-0004"

    go(app, "review")
    app.button(key="review-go-vehicles-0").click().run()
    ok(app)
    assert app.session_state["current_page"] == "fleet"
    assert app.selectbox(key="fleet_truck_edit_id").value == "TRUCK-2"


def test_review_fits_the_period_to_shifts_and_tasks(app: AppTest, backend: FakeBackend) -> None:
    backend.extra_issues = [
        {
            "severity": "ERROR",
            "code": "OUTSIDE_PLANNING_HORIZON",
            "message": "Outside.",
            "section": "tasks",
            "item_id": "TASK-0001",
        }
    ]
    go(app, "review")
    click(app, "Revalidate")
    click(app, "Fit the planning period to shifts and tasks")

    assert scenario(app)["planning_horizon"] == {
        "start": "2026-12-07T00:00:00",
        "end": "2026-12-08T00:00:00",
    }


def test_fleet_and_task_edits_keep_travel_times_and_call_no_provider(
    app: AppTest, backend: FakeBackend
) -> None:
    go(app, "locations")
    next(b for b in app.button if str(b.label).startswith("Resolve addresses (")).click().run()
    go(app, "travel_times")
    click(app, "Calculate travel times")
    calls = backend.provider_calls
    matrix = workspace(app).derived.matrix

    go(app, "fleet")
    add_truck(app, name="Spare", capacity=4)
    generate_shifts(app, trucks=["SPARE"], first=DAY, last=DAY, weekdays=(0,))
    go(app, "tasks")
    add_task(app, movement="DROP", po="PO-X", destination="OAKVILLE-CUSTOMER", day=DAY)
    for page in ("scenario", "locations", "fleet", "tasks", "review", "travel_times"):
        go(app, page)

    assert backend.provider_calls == calls
    assert workspace(app).derived.matrix == matrix
    sidebar = " | ".join(str(element.value) for element in app.sidebar.markdown)
    assert "✅ Travel times current" in sidebar


def test_renaming_keeps_the_row_selected_in_the_edit_picker(app: AppTest) -> None:
    """The picker labels include names; saving must not jump to the first row."""
    go(app, "locations")
    app.selectbox(key="locations_edit_id").set_value("VAUGHAN-SUPPLIER").run()
    app.text_input(key="edit-VAUGHAN-SUPPLIER-name").input("Vaughan steel yard")
    click(app, "Save location")

    assert app.selectbox(key="locations_edit_id").value == "VAUGHAN-SUPPLIER"


def test_a_one_off_message_does_not_move_the_page_below_it(app: AppTest) -> None:
    """Found in the browser: when a one-off message disappeared, everything below it
    moved up one place, and Streamlit then reopened the first tab of the page's tabs
    (the planner was sent from "Edit" back to "Add" while picking a task). Notices
    now live in one container that is always there."""
    go(app, "tasks")
    app.session_state["flash_message"] = {"level": "success", "message": "Imported tasks."}
    app.run()
    ok(app)
    with_message = [type(child).__name__ for child in app.main.children.values()]
    assert any("Imported tasks." in str(element.value) for element in app.success)

    app.run()
    ok(app)
    without_message = [type(child).__name__ for child in app.main.children.values()]

    assert with_message == without_message
