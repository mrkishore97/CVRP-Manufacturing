"""Frontend export shaping for route plans.

Exports are generated from the backend plan JSON contract without importing
backend implementation models. Spreadsheet cells are escaped defensively so
planner-entered values cannot be interpreted as formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pandas as pd

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


def build_export_tables(plan_payload: JsonPayload) -> ExportTables:
    """Build summary, route, stop, and diagnostic rows from plan JSON."""
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
        }
        for diagnostic in _as_dicts(plan_payload.get("diagnostics"))
    ]
    diagnostic_task_ids = {str(row.get("task_id")) for row in diagnostic_rows}
    for task_id in unscheduled_task_ids:
        if task_id not in diagnostic_task_ids:
            diagnostic_rows.append(
                {
                    "plan_id": plan_id,
                    "task_id": task_id,
                    "po_number": "",
                    "code": "UNSCHEDULED",
                    "message": "Task was not scheduled by the returned plan.",
                    "due_at": "",
                    "estimated_completion_at": "",
                    "late_by_seconds": "",
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


def route_stops_csv_bytes(plan_payload: JsonPayload) -> bytes:
    """Return UTF-8 CSV bytes for detailed route stops."""
    tables = build_export_tables(plan_payload)
    csv_text = dataframe_for_rows(tables.route_stop_rows, ROUTE_STOP_COLUMNS).to_csv(index=False)
    if not isinstance(csv_text, str):
        raise RuntimeError("Expected pandas to return CSV text.")
    return csv_text.encode("utf-8-sig")


def diagnostics_csv_bytes(plan_payload: JsonPayload) -> bytes:
    """Return UTF-8 CSV bytes for unscheduled/diagnostic tasks."""
    tables = build_export_tables(plan_payload)
    csv_text = dataframe_for_rows(tables.diagnostic_rows, DIAGNOSTIC_COLUMNS).to_csv(index=False)
    if not isinstance(csv_text, str):
        raise RuntimeError("Expected pandas to return CSV text.")
    return csv_text.encode("utf-8-sig")


def workbook_bytes(plan_payload: JsonPayload) -> bytes:
    """Return an XLSX workbook with summary, route, diagnostic, and stop sheets."""
    tables = build_export_tables(plan_payload)
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
    return output.getvalue()


def _safe_sheet_name(value: str) -> str:
    cleaned = "".join(character if character not in "[]:*?/\\'" else "-" for character in value)
    cleaned = cleaned.strip() or "Route"
    return cleaned[:31]
