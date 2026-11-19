"""Results: the current plan's routes, diagnostics, map, and exports."""

from __future__ import annotations

from typing import Any

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.export_utils import (
    build_export_tables,
    diagnostics_csv_bytes,
    route_stops_csv_bytes,
    workbook_bytes,
)
from frontend.route_map import RouteMapData, build_route_map_data
from frontend.state.scenario_state import rows
from frontend.views.components import AppContext, get_workspace, table


def render(ctx: AppContext) -> None:
    st.header("Results")
    status = ctx.status
    workspace = get_workspace()
    plan = workspace.derived.plan
    if status.stale_plan_hidden:
        st.warning(
            "The last plan is hidden because the inputs or travel times changed since. "
            "Solve again on the Optimize page."
        )
        return
    if not plan or not status.plan_current:
        st.info("No current plan yet. Solve one on the Optimize page.")
        return

    scheduled = plan.get("scheduled_task_ids", [])
    unscheduled = plan.get("unscheduled_task_ids", [])
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Plan status", str(plan.get("status", "unknown")))
    col_2.metric("Scheduled POs", str(len(scheduled) if isinstance(scheduled, list) else 0))
    col_3.metric("Unscheduled POs", str(len(unscheduled) if isinstance(unscheduled, list) else 0))

    route_rows = _route_rows(plan)
    if route_rows:
        st.subheader("Route stops")
        table(route_rows)
    diagnostics = [item for item in plan.get("diagnostics", []) if isinstance(item, dict)]
    if diagnostics:
        st.subheader("Diagnostics for infeasible or unscheduled POs")
        table(diagnostics)
    elif route_rows:
        st.success("No unscheduled PO diagnostics were returned.")
    st.divider()
    _render_route_map(plan, rows(workspace.scenario, "locations"))
    st.divider()
    _render_exports(plan)


def _route_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for route in plan.get("routes", []):
        if not isinstance(route, dict):
            continue
        for stop in route.get("stops", []):
            if not isinstance(stop, dict):
                continue
            result.append(
                {
                    "vehicle_id": route.get("vehicle_id"),
                    "shift_id": route.get("shift_id"),
                    "sequence": stop.get("sequence"),
                    "kind": stop.get("kind"),
                    "location_id": stop.get("location_id"),
                    "task_id": stop.get("task_id"),
                    "arrival_at": stop.get("arrival_at"),
                    "departure_at": stop.get("departure_at"),
                    "load_after": stop.get("load_after"),
                    "slack_seconds": stop.get("slack_seconds"),
                }
            )
    return result


def _render_route_map(plan: dict[str, Any], locations: list[dict[str, Any]]) -> None:
    st.subheader("Route map")
    map_data = build_route_map_data(plan, locations)
    if not map_data.markers or map_data.center is None:
        st.info("No mappable route stops with latitude/longitude are available.")
        return
    show_lines = st.checkbox(
        "Show route-order preview lines",
        value=True,
        help="Lines connect backend stop order directly. They are not billable road polylines.",
    )
    st_folium(_folium_map(map_data, show_lines=show_lines), height=500, use_container_width=True)
    if any(marker.duplicate_count > 1 for marker in map_data.markers):
        st.caption(
            "Some markers share the same source coordinates; they are slightly offset "
            "and labeled so each stop remains clickable."
        )


def _folium_map(map_data: RouteMapData, *, show_lines: bool) -> Any:
    folium_api: Any = folium
    if map_data.center is None:
        return folium_api.Map(location=[43.7, -79.4], zoom_start=10)
    route_map = folium_api.Map(location=list(map_data.center), zoom_start=10)
    if show_lines:
        for polyline in map_data.polylines:
            folium_api.PolyLine(
                locations=[list(point) for point in polyline.points],
                color=polyline.color,
                weight=4,
                opacity=0.75,
                tooltip=f"{polyline.vehicle_id} / {polyline.shift_id}",
            ).add_to(route_map)
    for marker in map_data.markers:
        folium_api.Marker(
            location=[marker.display_latitude, marker.display_longitude],
            tooltip=marker.label,
            popup=folium_api.Popup(marker.popup, max_width=320),
            icon=folium_api.Icon(color=marker.color, icon="info-sign"),
        ).add_to(route_map)
    return route_map


def _render_exports(plan: dict[str, Any]) -> None:
    st.subheader("Exports")
    tables = build_export_tables(plan)
    if tables.route_summary_rows:
        st.write("Route summary")
        table(tables.route_summary_rows)
    plan_id = str(plan.get("plan_id", "route-plan"))
    safe_plan_id = "".join(c if c.isalnum() or c in "-_" else "-" for c in plan_id)
    col_route, col_diag, col_book = st.columns(3)
    col_route.download_button(
        "Download route stops CSV",
        data=route_stops_csv_bytes(plan),
        file_name=f"{safe_plan_id}_route_stops.csv",
        mime="text/csv",
    )
    col_diag.download_button(
        "Download diagnostics CSV",
        data=diagnostics_csv_bytes(plan),
        file_name=f"{safe_plan_id}_diagnostics.csv",
        mime="text/csv",
    )
    col_book.download_button(
        "Download plan workbook XLSX",
        data=workbook_bytes(plan),
        file_name=f"{safe_plan_id}_plan.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
