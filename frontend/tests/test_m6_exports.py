"""V1.1-M6 exports: settings, priority, run sheets; formula-safe; empty plans export."""

from __future__ import annotations

from io import BytesIO, StringIO
from typing import Any

import pandas as pd
from openpyxl import load_workbook

from frontend.export_utils import (
    DIAGNOSTIC_COLUMNS,
    ROUTE_STOP_COLUMNS,
    RUN_SHEET_COLUMNS,
    diagnostics_csv_bytes,
    route_stops_csv_bytes,
    run_sheet_rows,
    run_sheets_workbook_bytes,
    workbook_bytes,
)
from frontend.state.results import plan_context, stop_rows
from frontend.tests.plan_fixtures import ROUTE_1, partial_plan, sample_scenario

VERSION_1_0_DIAGNOSTIC_COLUMNS = (
    "plan_id",
    "task_id",
    "po_number",
    "code",
    "message",
    "due_at",
    "estimated_completion_at",
    "late_by_seconds",
)


def _sheet_rows(data: bytes, sheet: str) -> list[tuple[Any, ...]]:
    workbook = load_workbook(BytesIO(data))
    return [tuple(row) for row in workbook[sheet].iter_rows(values_only=True)]


def test_version_1_0_columns_keep_their_order_and_new_ones_follow() -> None:
    assert DIAGNOSTIC_COLUMNS[: len(VERSION_1_0_DIAGNOSTIC_COLUMNS)] == (
        VERSION_1_0_DIAGNOSTIC_COLUMNS
    )
    assert DIAGNOSTIC_COLUMNS[len(VERSION_1_0_DIAGNOSTIC_COLUMNS) :] == (
        "priority",
        "suggested_action",
    )
    stops = pd.read_csv(
        StringIO(route_stops_csv_bytes(partial_plan(), sample_scenario()).decode("utf-8-sig"))
    )
    assert tuple(stops.columns) == ROUTE_STOP_COLUMNS


def test_diagnostics_carry_priority_and_a_suggested_action() -> None:
    text = diagnostics_csv_bytes(partial_plan(), sample_scenario()).decode("utf-8-sig")
    frame = pd.read_csv(StringIO(text)).set_index("task_id")
    assert frame.loc["TASK-PAIR-002", "priority"] == 3
    assert frame.loc["TASK-DROP-002", "priority"] == 2
    # No diagnostic for it: the PO number and priority come from the scenario.
    assert frame.loc["TASK-PICK-002", "po_number"] == "PO-PICK-002"
    assert frame.loc["TASK-PICK-002", "priority"] == 2
    assert "due time later" in frame.loc["TASK-PAIR-002", "suggested_action"]


def test_plan_workbook_adds_a_settings_sheet_with_the_buffer() -> None:
    data = workbook_bytes(partial_plan(), sample_scenario())
    workbook = load_workbook(BytesIO(data))
    assert workbook.sheetnames[:4] == [
        "Plan Summary",
        "Route Summary",
        "Route Stops",
        "Diagnostics",
    ]
    assert workbook.sheetnames[-1] == "Plan Settings"
    settings = {row[0]: row[1] for row in _sheet_rows(data, "Plan Settings")[1:]}
    assert settings["Travel-time buffer"] == "20 %"
    assert settings["Objective"] == "Balanced workload"
    assert settings["Travel times from"] == "Google Maps"


def test_run_sheets_have_one_sheet_per_truck_shift_matching_the_stop_table() -> None:
    scenario = sample_scenario()
    plan = partial_plan()
    data = run_sheets_workbook_bytes(plan, scenario)
    workbook = load_workbook(BytesIO(data))
    assert workbook.sheetnames == ["Plan Settings", "1 Truck 1", "2 Truck 2"]

    rows = _sheet_rows(data, "1 Truck 1")
    header = {row[0]: row[1] for row in rows[:9] if row[0]}
    assert header["Run sheet"] == "Truck 1 · Mon 22 Jun · 07:00-09:40"
    assert header["Truck"] == "Truck 1 (TRUCK-1)"
    assert header["Totals"] == "64.5 km, driving 1:30, service 1:00, waiting 0:10"
    assert header["Made with"].startswith("Balanced workload, thorough search")
    assert "travel-time buffer 20 %" in header["Made with"]
    assert header["Times are in"] == "America/Toronto"
    assert header["Travel times source"] == "Google Maps"

    table_start = next(index for index, row in enumerate(rows) if row[0] == "#")
    assert rows[table_start][: len(RUN_SHEET_COLUMNS)] == RUN_SHEET_COLUMNS
    body = [dict(zip(RUN_SHEET_COLUMNS, row, strict=False)) for row in rows[table_start + 1 :]]
    # Reconcile with the stop table on the Results page: same stops, same times.
    on_screen = stop_rows(ROUTE_1, plan_context(scenario))
    assert len(body) == len(on_screen)
    for sheet_row, screen_row in zip(body, on_screen, strict=True):
        for column in ("Action", "Location", "PO", "Quantity", "Arrive", "Depart", "Slack"):
            assert (sheet_row[column] or "") == screen_row[column]
    supplier = body[1]
    assert supplier["Location"] == "Fixture Supplier A"
    assert supplier["Address"]  # the address as the planner typed it
    assert supplier["PO"] == "PO-PICK-001"


def test_planner_text_in_exports_cannot_become_a_formula() -> None:
    scenario = sample_scenario()
    for location in scenario["locations"]:
        if location["location_id"] == "SUPPLIER_A":
            location["name"] = '=HYPERLINK("http://example.test","click")'
            location["address"] = "+1 Evil Road"
    for task in scenario["tasks"]:
        if task["task_id"] == "TASK-PICK-001":
            task["notes"] = "@SUM(A1:A2)"
    scenario["name"] = "-cmd"
    data = run_sheets_workbook_bytes(partial_plan(), scenario)
    rows = _sheet_rows(data, "1 Truck 1")
    cells = [str(cell) for row in rows for cell in row if cell is not None]
    assert '\'=HYPERLINK("http://example.test","click")' in cells
    assert "'+1 Evil Road" in cells
    assert "'@SUM(A1:A2)" in cells
    assert not any(cell.startswith(("=", "+", "@")) for cell in cells)
    settings = [str(cell) for row in _sheet_rows(data, "Plan Settings") for cell in row if cell]
    assert not any(cell.startswith(("=", "+", "@")) for cell in settings)
    rows_for_route = run_sheet_rows(ROUTE_1, scenario)
    assert rows_for_route[1]["Notes"] == "@SUM(A1:A2)"  # escaped only when written


def test_empty_and_failed_plans_still_export() -> None:
    scenario = sample_scenario()
    empty = partial_plan(
        status="INFEASIBLE",
        routes=[],
        scheduled_task_ids=[],
        metrics=None,
        matrix=None,
        optimization_options=None,
    )
    runs = load_workbook(BytesIO(run_sheets_workbook_bytes(empty, scenario)))
    assert runs.sheetnames == ["Plan Settings"]
    book = load_workbook(BytesIO(workbook_bytes(empty, scenario)))
    assert "Plan Settings" in book.sheetnames
    assert diagnostics_csv_bytes(empty, scenario)
    assert route_stops_csv_bytes(empty, scenario)
    # Without a scenario (Version 1.0 callers), exports still work.
    assert workbook_bytes(partial_plan())
    assert run_sheets_workbook_bytes(partial_plan(), {})


def test_sheet_names_stay_unique_and_within_excel_limits() -> None:
    scenario = sample_scenario()
    for vehicle in scenario["vehicles"]:
        vehicle["name"] = "A very long truck name that Excel would refuse: [x]"
    data = run_sheets_workbook_bytes(partial_plan(), scenario)
    names = load_workbook(BytesIO(data)).sheetnames
    assert len(names) == len(set(names)) == 3
    assert all(len(name) <= 31 and not set(name) & set("[]:*?/\\") for name in names)
