"""Frontend export shaping for route plans.

Exports are generated from the backend plan JSON contract without importing
backend implementation models. Spreadsheet cells are escaped defensively so
planner-entered values cannot be interpreted as formulas.

Version 1.0's CSV columns and workbook sheets keep their names and order. V1.1-M6
adds, after them: ``priority`` and ``suggested_action`` on diagnostics, a "Plan
Settings" sheet (objective, effort, buffer, travel-time source), and a separate
run-sheet workbook with one printable sheet per truck-shift (plan §11.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from frontend.state.optimization import options_summary
from frontend.state.results import (
    GOOGLE_ATTRIBUTION,
    duration_text,
    km_text,
    location_address,
    plan_context,
    plan_settings,
    plan_uses_google_travel_times,
    reason_for,
    route_title,
    stop_rows,
    truck_name,
)

JsonPayload = dict[str, Any]

SUMMARY_COLUMNS = (
    "plan_id",
    "status",
    "scheduled_task_count",
    "unscheduled_task_count",
    "route_count",
    "total_distance_meters",
    "total_driving_seconds",
    "total_service_seconds",
    "total_waiting_seconds",
    "solver_elapsed_seconds",
)
ROUTE_SUMMARY_COLUMNS = (
    "plan_id",
    "vehicle_id",
    "shift_id",
    "stop_count",
    "total_distance_meters",
    "driving_seconds",
    "service_seconds",
    "waiting_seconds",
    "peak_load",
)
ROUTE_STOP_COLUMNS = (
    "plan_id",
    "vehicle_id",
    "shift_id",
    "sequence",
    "node_id",
    "kind",
    "location_id",
    "task_id",
    "arrival_at",
    "service_start_at",
    "departure_at",
    "load_after",
    "distance_from_previous_meters",
    "duration_from_previous_seconds",
    "due_at",
    "slack_seconds",
)
DIAGNOSTIC_COLUMNS = (
    "plan_id",
    "task_id",
    "po_number",
    "code",
    "message",
    "due_at",
    "estimated_completion_at",
    "late_by_seconds",
    "priority",
    "suggested_action",
)
SETTINGS_COLUMNS = ("Setting", "Value")
RUN_SHEET_COLUMNS = (
    "#",
    "Arrive",
    "Start",
    "Depart",
    "Action",
    "Location",
    "Address",
    "PO",
    "Quantity",
    "Load after",
    "Due by",
    "Slack",
    "Leg distance",
    "Leg time",
    "Notes",
)
FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass(frozen=True, slots=True)
class ExportTables:
    """All tabular export views for one plan."""

    summary_rows: tuple[JsonPayload, ...]
    route_summary_rows: tuple[JsonPayload, ...]
    route_stop_rows: tuple[JsonPayload, ...]
    diagnostic_rows: tuple[JsonPayload, ...]


def escape_spreadsheet_value(value: Any) -> Any:
    """Escape formula-like strings while preserving human-readable values."""
    if not isinstance(value, str):
        return value
    if value.startswith("'"):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def _safe_row(row: JsonPayload, columns: tuple[str, ...]) -> JsonPayload:
    return {column: escape_spreadsheet_value(row.get(column, "")) for column in columns}


def _as_dicts(value: Any) -> list[JsonPayload]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _plan_id(plan_payload: JsonPayload) -> str:
    return str(plan_payload.get("plan_id", "unsaved-plan"))


def build_export_tables(
    plan_payload: JsonPayload, scenario: Mapping[str, Any] | None = None
) -> ExportTables:
    """Build summary, route, stop, and diagnostic rows from plan JSON.

    With the scenario, diagnostics also carry each PO's priority when the plan did not
    record it, and every suggested action reads in the scenario's terms.
    """
    context = plan_context(scenario or {})
    plan_id = _plan_id(plan_payload)
    routes = _as_dicts(plan_payload.get("routes"))
    scheduled_task_ids = _as_strings(plan_payload.get("scheduled_task_ids"))
    unscheduled_task_ids = _as_strings(plan_payload.get("unscheduled_task_ids"))

    summary_rows = (
        {
            "plan_id": plan_id,
            "status": plan_payload.get("status"),
            "scheduled_task_count": len(scheduled_task_ids),
            "unscheduled_task_count": len(unscheduled_task_ids),
            "route_count": len(routes),
            "total_distance_meters": plan_payload.get("total_distance_meters", 0),
            "total_driving_seconds": plan_payload.get("total_driving_seconds", 0),
            "total_service_seconds": plan_payload.get("total_service_seconds", 0),
            "total_waiting_seconds": plan_payload.get("total_waiting_seconds", 0),
            "solver_elapsed_seconds": plan_payload.get("solver_elapsed_seconds", 0),
        },
    )

    route_summary_rows: list[JsonPayload] = []
    route_stop_rows: list[JsonPayload] = []
    for route in routes:
        stops = _as_dicts(route.get("stops"))
        route_summary_rows.append(
            {
                "plan_id": plan_id,
                "vehicle_id": route.get("vehicle_id"),
                "shift_id": route.get("shift_id"),
                "stop_count": len(stops),
                "total_distance_meters": route.get("total_distance_meters", 0),
                "driving_seconds": route.get("driving_seconds", 0),
                "service_seconds": route.get("service_seconds", 0),
                "waiting_seconds": route.get("waiting_seconds", 0),
                "peak_load": route.get("peak_load", 0),
            }
        )
        for stop in stops:
            route_stop_rows.append(
                {
                    "plan_id": plan_id,
                    "vehicle_id": route.get("vehicle_id"),
                    "shift_id": route.get("shift_id"),
                    "sequence": stop.get("sequence"),
                    "node_id": stop.get("node_id"),
                    "kind": stop.get("kind"),
                    "location_id": stop.get("location_id"),
                    "task_id": stop.get("task_id"),
                    "arrival_at": stop.get("arrival_at"),
                    "service_start_at": stop.get("service_start_at"),
                    "departure_at": stop.get("departure_at"),
                    "load_after": stop.get("load_after"),
                    "distance_from_previous_meters": stop.get("distance_from_previous_meters"),
                    "duration_from_previous_seconds": stop.get("duration_from_previous_seconds"),
                    "due_at": stop.get("due_at"),
                    "slack_seconds": stop.get("slack_seconds"),
                }
            )

    def priority_of(task_id: Any, recorded: Any) -> Any:
        if recorded is not None:
            return recorded
        task = context.tasks.get(str(task_id))
        return task.get("priority", 1) if task else ""

    diagnostic_rows = [
        {
            "plan_id": plan_id,
            "task_id": diagnostic.get("task_id"),
            "po_number": diagnostic.get("po_number"),
            "code": diagnostic.get("code"),
            "message": diagnostic.get("message"),
            "due_at": diagnostic.get("due_at"),
            "estimated_completion_at": diagnostic.get("estimated_completion_at"),
            "late_by_seconds": diagnostic.get("late_by_seconds"),
            "priority": priority_of(diagnostic.get("task_id"), diagnostic.get("priority"))
            if diagnostic.get("task_id") != "REQUEST"
            else "",
            "suggested_action": reason_for(diagnostic, context)[1],
        }
        for diagnostic in _as_dicts(plan_payload.get("diagnostics"))
    ]
    diagnostic_task_ids = {str(row.get("task_id")) for row in diagnostic_rows}
    for task_id in unscheduled_task_ids:
        if task_id not in diagnostic_task_ids:
            task = context.tasks.get(task_id, {})
            diagnostic_rows.append(
                {
                    "plan_id": plan_id,
                    "task_id": task_id,
                    "po_number": task.get("po_number", ""),
                    "code": "UNSCHEDULED",
                    "message": "Task was not scheduled by the returned plan.",
                    "due_at": "",
                    "estimated_completion_at": "",
                    "late_by_seconds": "",
                    "priority": priority_of(task_id, None),
                    "suggested_action": reason_for({"code": "UNSCHEDULED"}, context)[1],
                }
            )

    return ExportTables(
        summary_rows=tuple(summary_rows),
        route_summary_rows=tuple(route_summary_rows),
        route_stop_rows=tuple(route_stop_rows),
        diagnostic_rows=tuple(diagnostic_rows),
    )


def dataframe_for_rows(rows: tuple[JsonPayload, ...], columns: tuple[str, ...]) -> pd.DataFrame:
    """Return a safe dataframe with stable columns, even when rows are empty."""
    safe_rows = [_safe_row(row, columns) for row in rows]
    return pd.DataFrame(safe_rows, columns=list(columns))


def route_stops_csv_bytes(
    plan_payload: JsonPayload, scenario: Mapping[str, Any] | None = None
) -> bytes:
    """Return UTF-8 CSV bytes for detailed route stops."""
    tables = build_export_tables(plan_payload, scenario)
    csv_text = dataframe_for_rows(tables.route_stop_rows, ROUTE_STOP_COLUMNS).to_csv(index=False)
    if not isinstance(csv_text, str):
        raise RuntimeError("Expected pandas to return CSV text.")
    return csv_text.encode("utf-8-sig")


def diagnostics_csv_bytes(
    plan_payload: JsonPayload, scenario: Mapping[str, Any] | None = None
) -> bytes:
    """Return UTF-8 CSV bytes for unscheduled/diagnostic tasks."""
    tables = build_export_tables(plan_payload, scenario)
    csv_text = dataframe_for_rows(tables.diagnostic_rows, DIAGNOSTIC_COLUMNS).to_csv(index=False)
    if not isinstance(csv_text, str):
        raise RuntimeError("Expected pandas to return CSV text.")
    return csv_text.encode("utf-8-sig")


def settings_rows(
    plan_payload: JsonPayload, scenario: Mapping[str, Any] | None = None
) -> tuple[JsonPayload, ...]:
    """The "Plan Settings" sheet: how the plan was made, including the buffer."""
    return tuple(plan_settings(plan_payload, scenario or {}))


def workbook_bytes(plan_payload: JsonPayload, scenario: Mapping[str, Any] | None = None) -> bytes:
    """Return an XLSX workbook with summary, route, diagnostic, stop, and settings sheets."""
    tables = build_export_tables(plan_payload, scenario)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe_for_rows(tables.summary_rows, SUMMARY_COLUMNS).to_excel(
            writer,
            sheet_name="Plan Summary",
            index=False,
        )
        dataframe_for_rows(tables.route_summary_rows, ROUTE_SUMMARY_COLUMNS).to_excel(
            writer,
            sheet_name="Route Summary",
            index=False,
        )
        dataframe_for_rows(tables.route_stop_rows, ROUTE_STOP_COLUMNS).to_excel(
            writer,
            sheet_name="Route Stops",
            index=False,
        )
        dataframe_for_rows(tables.diagnostic_rows, DIAGNOSTIC_COLUMNS).to_excel(
            writer,
            sheet_name="Diagnostics",
            index=False,
        )
        for route in _as_dicts(plan_payload.get("routes")):
            vehicle_id = str(route.get("vehicle_id", "vehicle"))
            shift_id = str(route.get("shift_id", "shift"))
            sheet_name = _safe_sheet_name(f"{vehicle_id}-{shift_id}")
            rows = tuple(
                row
                for row in tables.route_stop_rows
                if row.get("vehicle_id") == route.get("vehicle_id")
                and row.get("shift_id") == route.get("shift_id")
            )
            dataframe_for_rows(rows, ROUTE_STOP_COLUMNS).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )
        dataframe_for_rows(settings_rows(plan_payload, scenario), SETTINGS_COLUMNS).to_excel(
            writer,
            sheet_name="Plan Settings",
            index=False,
        )
    return output.getvalue()


def run_sheet_rows(route: Mapping[str, Any], scenario: Mapping[str, Any]) -> list[JsonPayload]:
    """One truck-shift's stops for the driver: local times, names, addresses, POs."""
    context = plan_context(scenario)
    stops = _as_dicts(route.get("stops"))
    result: list[JsonPayload] = []
    for stop, shown in zip(stops, stop_rows(route, context), strict=True):
        task = context.tasks.get(str(stop.get("task_id")), {}) if stop.get("task_id") else {}
        result.append(
            {
                **shown,
                "Address": location_address(context, stop.get("location_id")),
                "Notes": str(task.get("notes") or ""),
            }
        )
    return result


def run_sheet_header(
    route: Mapping[str, Any], plan_payload: Mapping[str, Any], scenario: Mapping[str, Any]
) -> list[tuple[str, str]]:
    """The lines above a run sheet's table."""
    context = plan_context(scenario)
    options = plan_payload.get("optimization_options")
    lines = [
        ("Run sheet", route_title(route, context)),
        ("Truck", f"{truck_name(context, route.get('vehicle_id'))} ({route.get('vehicle_id')})"),
        ("Shift", str(route.get("shift_id", ""))),
        (
            "Totals",
            f"{km_text(route.get('total_distance_meters'))}, "
            f"driving {duration_text(route.get('driving_seconds'))}, "
            f"service {duration_text(route.get('service_seconds'))}, "
            f"waiting {duration_text(route.get('waiting_seconds'))}",
        ),
        ("Plan", str(plan_payload.get("plan_id", ""))),
        ("Made with", options_summary(options if isinstance(options, dict) else None)),
        ("Times are in", context.timezone),
    ]
    if plan_uses_google_travel_times(plan_payload):
        lines.append(("Travel times source", GOOGLE_ATTRIBUTION))
    return lines


def run_sheets_workbook_bytes(plan_payload: JsonPayload, scenario: Mapping[str, Any]) -> bytes:
    """One printable sheet per truck-shift, after a "Plan Settings" sheet.

    An empty or failed plan still exports: the settings sheet says how it was made.
    """
    workbook = Workbook()
    settings_sheet = workbook.active
    if settings_sheet is None:
        raise RuntimeError("openpyxl did not create a first sheet.")
    settings_sheet.title = "Plan Settings"
    _write_table(settings_sheet, 1, SETTINGS_COLUMNS, settings_rows(plan_payload, scenario))
    used_names = {"Plan Settings"}
    context = plan_context(scenario)
    for index, route in enumerate(_as_dicts(plan_payload.get("routes")), start=1):
        name = _unique_sheet_name(
            f"{index} {truck_name(context, route.get('vehicle_id'))}", used_names
        )
        sheet = workbook.create_sheet(name)
        header = run_sheet_header(route, plan_payload, scenario)
        for row_number, (label, value) in enumerate(header, start=1):
            sheet.cell(row=row_number, column=1, value=escape_spreadsheet_value(label)).font = Font(
                bold=True
            )
            sheet.cell(row=row_number, column=2, value=escape_spreadsheet_value(value))
        _write_table(sheet, len(header) + 2, RUN_SHEET_COLUMNS, run_sheet_rows(route, scenario))
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _write_table(
    sheet: Worksheet,
    first_row: int,
    columns: tuple[str, ...],
    rows: tuple[JsonPayload, ...] | list[JsonPayload],
) -> None:
    for column_number, column in enumerate(columns, start=1):
        cell = sheet.cell(row=first_row, column=column_number, value=column)
        cell.font = Font(bold=True)
    for row_offset, row in enumerate(rows, start=1):
        safe = _safe_row(row, columns)
        for column_number, column in enumerate(columns, start=1):
            sheet.cell(row=first_row + row_offset, column=column_number, value=safe[column])
    for column_number, column in enumerate(columns, start=1):
        width = max([len(str(column))] + [len(str(row.get(column, ""))) for row in rows], default=8)
        letter = sheet.cell(row=first_row, column=column_number).column_letter
        sheet.column_dimensions[letter].width = min(max(width + 2, 8), 60)


def _unique_sheet_name(value: str, used: set[str]) -> str:
    base = _safe_sheet_name(value)
    name, counter = base, 2
    while name in used:
        suffix = f" ({counter})"
        name = f"{base[: 31 - len(suffix)]}{suffix}"
        counter += 1
    used.add(name)
    return name


def _safe_sheet_name(value: str) -> str:
    cleaned = "".join(character if character not in "[]:*?/\\'" else "-" for character in value)
    cleaned = cleaned.strip() or "Route"
    return cleaned[:31]
