"""Results: the plan in planner language, plan comparison, map links, and exports.

Plan §11.1. Every stop shows a location name and PO number rather than an internal
ID, times are plant-local, distances are kilometres and durations ``h:mm``. A stale
plan is hidden (plan §12), but every stored plan stays available, clearly dated, in
the comparison table, and can be viewed and exported as an earlier plan.

Decision D1: locations found by address resolution are shown on a map only through
Google, by "Open in Google Maps" links. The OpenStreetMap preview remains for
coordinates supplied in JSON, such as the samples.
"""

from __future__ import annotations

from typing import Any

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.api_client import BackendClientError
from frontend.export_utils import (
    build_export_tables,
    diagnostics_csv_bytes,
    route_stops_csv_bytes,
    run_sheets_workbook_bytes,
    workbook_bytes,
)
from frontend.route_map import RouteMapData, build_route_map_data
from frontend.state.optimization import OBJECTIVES, options_summary
from frontend.state.results import (
    as_dicts,
    comparison_rows,
    google_maps_links,
    local_datetime_text,
    plan_context,
    plan_headline,
    plan_problems,
    plan_uses_google_travel_times,
    route_title,
    stop_rows,
    truck_rows,
    unscheduled_rows,
    uses_resolved_locations,
)
from frontend.state.scenario_state import rows
from frontend.views.components import (
    AppContext,
    get_workspace,
    render_backend_error,
    render_google_attribution,
    table,
)

HISTORY_KEY = "plan_history"
EARLIER_PLAN_KEY = "earlier_plan"
HISTORY_CHOICE_KEY = "history-choice"


def render(ctx: AppContext) -> None:
    st.header("Results")
    workspace = get_workspace()
    scenario = workspace.scenario
    status = ctx.status
    current = workspace.derived.plan if status.plan_current else None

    earlier = st.session_state.get(EARLIER_PLAN_KEY)
    if isinstance(earlier, dict) and earlier.get("scenario_id") == scenario.get("scenario_id"):
        _render_earlier(ctx, earlier["plan"], scenario)
        _render_history(ctx, current)
        return
    st.session_state.pop(EARLIER_PLAN_KEY, None)

    if status.stale_plan_hidden:
        st.warning(
            "The last plan is hidden because the inputs or travel times changed since. "
            "Solve again on the Optimize page. Earlier plans stay listed below."
        )
    elif current is None:
        st.info("No current plan yet. Solve one on the Optimize page.")
    if current is not None:
        _render_plan(ctx, current, scenario, key="current")
    _render_history(ctx, current)


def _render_earlier(ctx: AppContext, plan: dict[str, Any], scenario: dict[str, Any]) -> None:
    timezone = plan_context(scenario).timezone
    st.warning(
        f"Earlier plan made {local_datetime_text(plan.get('created_at'), timezone)}. It may "
        "not match the scenario as it is now; names and addresses are shown as they are now."
    )
    if st.button("Back to the current plan", key="earlier-back"):
        st.session_state.pop(EARLIER_PLAN_KEY, None)
        st.rerun()
    _render_plan(ctx, plan, scenario, key="earlier")


def _render_plan(
    ctx: AppContext, plan: dict[str, Any], scenario: dict[str, Any], *, key: str
) -> None:
    context = plan_context(scenario)
    headline = plan_headline(plan, context)
    {"success": st.success, "warning": st.warning, "error": st.error}[headline.level](
        headline.sentence
    )
    figures = list(headline.figures.items())
    for start in range(0, len(figures), 3):
        chunk = figures[start : start + 3]
        for column, (label, value) in zip(st.columns(3), chunk, strict=False):
            column.metric(label, value)
    options = plan.get("optimization_options")
    st.caption(f"Made with: {options_summary(options if isinstance(options, dict) else None)}")
    st.caption(f"Plan {plan.get('plan_id', '')} · times are plant-local ({context.timezone})")
    for reason, action in plan_problems(plan, context):
        st.error(f"{reason} {action}")

    missing = unscheduled_rows(plan, context)
    if missing:
        st.subheader(f"Not planned ({len(missing)})")
        table(missing)

    routes = as_dicts(plan.get("routes"))
    if routes:
        st.subheader("Trucks")
        table(truck_rows(plan, context))
        st.subheader("Routes")
        for index, route in enumerate(routes):
            with st.expander(route_title(route, context), expanded=index == 0):
                table(stop_rows(route, context))
                links = google_maps_links(route, context)
                for part, url in enumerate(links, start=1):
                    label = "Open in Google Maps" + (
                        f" (part {part} of {len(links)})" if len(links) > 1 else ""
                    )
                    st.link_button(label, url)
        st.caption(
            "Each Google Maps link shows up to nine stops between its start and end; longer "
            "routes are split into parts. Phones may show fewer."
        )
    st.divider()
    _render_map(plan, scenario)
    render_google_attribution(
        ctx,
        addresses=uses_resolved_locations(scenario),
        travel_times=plan_uses_google_travel_times(plan),
    )
    st.divider()
    _render_exports(plan, scenario, key=key)


def _render_map(plan: dict[str, Any], scenario: dict[str, Any]) -> None:
    st.subheader("Route map")
    locations = rows(scenario, "locations")
    if uses_resolved_locations(scenario):
        # Decision D1: locations found by address resolution may be shown on a map only
        # through Google. The OpenStreetMap preview stays for coordinates supplied in JSON.
        st.info(
            "This scenario's locations were found by address resolution, so they are not "
            "drawn on the OpenStreetMap preview. Open each route in Google Maps with the "
            "links above."
        )
        return
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


def _render_exports(plan: dict[str, Any], scenario: dict[str, Any], *, key: str) -> None:
    st.subheader("Exports")
    plan_id = str(plan.get("plan_id", "route-plan"))
    safe_plan_id = "".join(c if c.isalnum() or c in "-_" else "-" for c in plan_id)
    col_runs, col_book = st.columns(2)
    col_runs.download_button(
        "Download run sheets (XLSX)",
        data=run_sheets_workbook_bytes(plan, scenario),
        file_name=f"{safe_plan_id}_run_sheets.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="One printable sheet per truck-shift: local times, names, addresses, POs.",
        key=f"{key}-runs",
    )
    col_book.download_button(
        "Download plan workbook XLSX",
        data=workbook_bytes(plan, scenario),
        file_name=f"{safe_plan_id}_plan.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Every table, with a Plan Settings sheet; Version 1.0 sheets keep their columns.",
        key=f"{key}-book",
    )
    col_route, col_diag = st.columns(2)
    col_route.download_button(
        "Download route stops CSV",
        data=route_stops_csv_bytes(plan, scenario),
        file_name=f"{safe_plan_id}_route_stops.csv",
        mime="text/csv",
        key=f"{key}-stops",
    )
    col_diag.download_button(
        "Download diagnostics CSV",
        data=diagnostics_csv_bytes(plan, scenario),
        file_name=f"{safe_plan_id}_diagnostics.csv",
        mime="text/csv",
        key=f"{key}-diagnostics",
    )
    with st.expander("Route summary as exported"):
        table(build_export_tables(plan, scenario).route_summary_rows)


def _history(ctx: AppContext, scenario_id: str, newest: str | None) -> list[dict[str, Any]]:
    """The scenario's stored plans, fetched once per newest plan and kept until Refresh."""
    cache_key = f"{scenario_id}|{newest or ''}"
    cached = st.session_state.get(HISTORY_KEY)
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        plans = cached.get("plans")
        return plans if isinstance(plans, list) else []
    if not ctx.connected:
        return []
    try:
        plans = ctx.client.plan_history(scenario_id)
    except BackendClientError as exc:
        render_backend_error(exc)
        return []
    st.session_state[HISTORY_KEY] = {"key": cache_key, "plans": plans}
    return plans


def _render_history(ctx: AppContext, current: dict[str, Any] | None) -> None:
    workspace = get_workspace()
    scenario_id = str(workspace.scenario.get("scenario_id") or "")
    newest = workspace.derived.plan.get("plan_id") if workspace.derived.plan else None
    history = _history(ctx, scenario_id, str(newest) if newest else None) if scenario_id else []
    st.divider()
    st.subheader("Compare plans")
    if not history:
        st.caption("Plans solved for this scenario are listed here, newest first.")
        return
    timezone = plan_context(workspace.scenario).timezone
    st.caption(
        'Plans solved for this scenario ID, newest first. "Inputs: Same" means the POs, '
        "trucks, shifts, and travel times were the same as for the plan shown, so the "
        "difference comes from the settings."
    )
    table(comparison_rows(history, timezone=timezone, current=current))
    shown = current.get("plan_id") if current else None
    labels = {
        str(summary.get("plan_id")): (
            f"{local_datetime_text(summary.get('created_at'), timezone)} · "
            f"{OBJECTIVES.get(str(summary.get('objective_mode')), 'Fewest trucks')} · "
            f"{summary.get('plan_id')}"
        )
        for summary in history
        if summary.get("plan_id") != shown
    }
    col_pick, col_view, col_refresh = st.columns([3, 1, 1])
    if labels:
        choice = col_pick.selectbox(
            "Earlier plan",
            options=list(labels),
            format_func=lambda plan_id: labels[plan_id],
            key=HISTORY_CHOICE_KEY,
        )
        if col_view.button("View this plan", key="history-view") and choice:
            _open_earlier(ctx, str(choice), scenario_id, current)
    if col_refresh.button("Refresh", key="history-refresh"):
        st.session_state.pop(HISTORY_KEY, None)
        st.rerun()


def _open_earlier(
    ctx: AppContext, plan_id: str, scenario_id: str, current: dict[str, Any] | None
) -> None:
    if current is not None and current.get("plan_id") == plan_id:
        st.session_state.pop(EARLIER_PLAN_KEY, None)
        st.rerun()
    try:
        plan = ctx.client.get_plan(plan_id).raw.get("plan")
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    if not isinstance(plan, dict):
        st.error("The stored plan could not be read.")
        return
    st.session_state[EARLIER_PLAN_KEY] = {"scenario_id": scenario_id, "plan": plan}
    st.rerun()
