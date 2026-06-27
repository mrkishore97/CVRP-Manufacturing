"""Streamlit planning workflow for manufacturing PO routing."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from frontend.api_client import (
    BackendApiError,
    BackendClient,
    BackendClientError,
    BackendResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
)
from frontend.export_utils import (
    build_export_tables,
    diagnostics_csv_bytes,
    route_stops_csv_bytes,
    workbook_bytes,
)
from frontend.import_preview import ImportPreview, preview_task_import
from frontend.route_map import RouteMapData, build_route_map_data
from frontend.session_models import (
    JsonPayload,
    attach_matrix_to_payload,
    location_fingerprint,
    task_fingerprint,
    validation_fingerprint,
    validation_issue_rows,
    workflow_status,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = PROJECT_ROOT / "sample_data" / "canonical"
SAMPLE_SCENARIOS = {
    "A": "scenario_a_feasible_mixed.json",
    "C": "scenario_c_deadline_impossible.json",
    "D": "scenario_d_collective_shortage.json",
}
PLANNING_PAYLOAD_KEYS = {
    "scenario_id",
    "timezone",
    "planning_horizon",
    "plant_location_id",
    "locations",
    "vehicles",
    "vehicle_shifts",
    "tasks",
    "routing_matrix",
}


def _load_json(path: Path) -> JsonPayload:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object in {path.name}.")
    return value


def load_sample_payload(scenario: str = "A", *, include_matrix: bool = True) -> JsonPayload:
    """Load one canonical sample as a clean planning payload."""
    scenario_file = SAMPLE_SCENARIOS.get(scenario.upper(), SAMPLE_SCENARIOS["A"])
    fixture = _load_json(CANONICAL_DIR / scenario_file)
    payload = {
        key: deepcopy(value) for key, value in fixture.items() if key in PLANNING_PAYLOAD_KEYS
    }
    locations_ref = fixture.get("locations_ref")
    if isinstance(locations_ref, str):
        payload["locations"] = deepcopy(_load_json(CANONICAL_DIR / locations_ref)["locations"])
    if include_matrix:
        matrix_ref = fixture.get("matrix_ref")
        if isinstance(matrix_ref, str):
            payload["routing_matrix"] = deepcopy(_load_json(CANONICAL_DIR / matrix_ref))
    else:
        payload.pop("routing_matrix", None)
    return payload


def _sample_payload_text(scenario: str = "A") -> str:
    return json.dumps(load_sample_payload(scenario), indent=2)


def _ensure_session_state() -> None:
    defaults: dict[str, Any] = {
        "payload_text": _sample_payload_text("A"),
        "validation_payload": None,
        "validation_source_fingerprint": None,
        "matrix_payload": None,
        "matrix_source_location_fingerprint": None,
        "plan_payload": None,
        "plan_source_task_fingerprint": None,
        "last_request_id": None,
        "flash_message": None,
        "load_scenario_id": "A",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _reset_validation_matrix_and_plan() -> None:
    st.session_state["validation_payload"] = None
    st.session_state["validation_source_fingerprint"] = None
    st.session_state["matrix_payload"] = None
    st.session_state["matrix_source_location_fingerprint"] = None
    st.session_state["plan_payload"] = None
    st.session_state["plan_source_task_fingerprint"] = None
    st.session_state["last_request_id"] = None


def _reset_matrix_and_plan() -> None:
    st.session_state["matrix_payload"] = None
    st.session_state["matrix_source_location_fingerprint"] = None
    st.session_state["plan_payload"] = None
    st.session_state["plan_source_task_fingerprint"] = None


def _set_flash(level: str, message: str) -> None:
    st.session_state["flash_message"] = {"level": level, "message": message}


def _render_flash() -> None:
    flash = st.session_state.pop("flash_message", None)
    if not isinstance(flash, dict):
        return
    level = str(flash.get("level", "info"))
    message = str(flash.get("message", ""))
    if not message:
        return
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def _current_payload() -> tuple[JsonPayload | None, str | None]:
    raw_text = str(st.session_state.get("payload_text", ""))
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, f"JSON line {exc.lineno}, column {exc.colno}: {exc.msg}"
    if not isinstance(payload, dict):
        return None, "Planning payload must be a JSON object."
    return payload, None


def _state_value(key: str) -> Any:
    return st.session_state.get(key)


def _validation_is_valid(validation_payload: Any) -> bool:
    return isinstance(validation_payload, dict) and bool(validation_payload.get("valid"))


def _routing_locations(payload: JsonPayload) -> list[dict[str, Any]]:
    locations = payload.get("locations", [])
    if not isinstance(locations, list):
        raise ValueError("locations must be a list before matrix calculation.")
    routing_locations: list[dict[str, Any]] = []
    for index, location in enumerate(locations, start=1):
        if not isinstance(location, dict):
            raise ValueError(f"Location row {index} is not an object.")
        location_id = str(location.get("location_id", "")).strip()
        formatted_address = str(
            location.get("formatted_address")
            or location.get("address")
            or location.get("name")
            or location_id
        ).strip()
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if not location_id or latitude is None or longitude is None:
            raise ValueError(
                "Every location needs location_id, latitude, and longitude before "
                "matrix calculation."
            )
        routing_locations.append(
            {
                "location_id": location_id,
                "formatted_address": formatted_address,
                "latitude": latitude,
                "longitude": longitude,
                "place_id": location.get("place_id"),
            }
        )
    return routing_locations


def _preview_uploaded_tasks(uploaded_file: Any) -> ImportPreview:
    if str(uploaded_file.name).casefold().endswith(".csv"):
        frame = pd.read_csv(uploaded_file)
    else:
        frame = pd.read_excel(uploaded_file)
    return preview_task_import(frame)


def _table_rows(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _normalized_task_rows(validation_payload: JsonPayload | None) -> list[dict[str, Any]]:
    if not validation_payload:
        return []
    normalized_request = validation_payload.get("normalized_request")
    if not isinstance(normalized_request, dict):
        return []
    return _table_rows(normalized_request.get("tasks"))


def _route_rows(plan_payload: JsonPayload | None) -> list[dict[str, Any]]:
    if not plan_payload:
        return []
    rows: list[dict[str, Any]] = []
    routes = plan_payload.get("routes", [])
    if not isinstance(routes, list):
        return rows
    for route in routes:
        if not isinstance(route, dict):
            continue
        stops = route.get("stops", [])
        if not isinstance(stops, list):
            continue
        for stop in stops:
            if not isinstance(stop, dict):
                continue
            rows.append(
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
    return rows


def _diagnostic_rows(plan_payload: JsonPayload | None) -> list[dict[str, Any]]:
    if not plan_payload:
        return []
    diagnostics = plan_payload.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        return []
    return [diagnostic for diagnostic in diagnostics if isinstance(diagnostic, dict)]


def _location_rows(payload: JsonPayload | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    return _table_rows(payload.get("locations"))


def _render_backend_error(error: BackendClientError) -> None:
    if isinstance(error, BackendApiError):
        st.error(f"{error.code}: {error}")
        if error.request_id:
            st.caption(f"Request ID: {error.request_id}")
        if error.details:
            st.dataframe(
                pd.DataFrame(
                    {
                        "code": detail.code,
                        "row_number": detail.row_number,
                        "field": detail.field,
                        "task_id": detail.task_id,
                        "message": detail.message,
                    }
                    for detail in error.details
                ),
                hide_index=True,
                use_container_width=True,
            )
        return
    if isinstance(error, BackendTimeoutError):
        st.warning(str(error))
        return
    if isinstance(error, BackendUnavailableError):
        st.warning(str(error))
        st.info("Start the backend service, then rerun the action.")
        return
    if isinstance(error, BackendResponseError):
        st.error(str(error))
        st.info("The backend responded in an unexpected format. Check API version alignment.")
        return
    st.error(str(error))


def _render_backend_status(client: BackendClient) -> bool:
    st.subheader("Backend status")
    try:
        health = client.get_health()
    except BackendClientError as exc:
        _render_backend_error(exc)
        st.info("You can still edit and preview files. Planning actions require the API.")
        return False
    st.success(f"Connected to backend {health.version} ({health.environment}).")
    return True


def _render_scenario_persistence(
    client: BackendClient,
    payload: JsonPayload | None,
    parse_error: str | None,
) -> None:
    st.write("Scenario persistence")
    col_save, col_load = st.columns(2)
    save_disabled = payload is None or parse_error is not None
    if col_save.button("Save scenario", disabled=save_disabled):
        if payload is None:
            st.error("Fix setup JSON before saving.")
        else:
            try:
                response = client.save_scenario(payload)
            except BackendClientError as exc:
                _render_backend_error(exc)
            else:
                saved_id = response.payload.get("scenario_id", payload.get("scenario_id"))
                _set_flash("success", f"Saved scenario {saved_id}.")
                st.rerun()

    scenario_id = col_load.text_input("Scenario ID to load", key="load_scenario_id")
    if col_load.button("Load saved scenario", disabled=not scenario_id.strip()):
        try:
            response = client.load_scenario(scenario_id.strip())
        except BackendClientError as exc:
            _render_backend_error(exc)
        else:
            loaded_payload = response.payload.get("payload")
            if not isinstance(loaded_payload, dict):
                st.error("Saved scenario response did not contain a payload object.")
            else:
                st.session_state["payload_text"] = json.dumps(loaded_payload, indent=2)
                _reset_validation_matrix_and_plan()
                _set_flash("success", f"Loaded scenario {response.payload.get('scenario_id')}.")
                st.rerun()


def _render_setup_tab(
    client: BackendClient,
    payload: JsonPayload | None,
    parse_error: str | None,
) -> None:
    st.subheader("Setup")
    st.write("Start with the sample scenario or paste a planning payload from another tool.")
    col_a, col_b, col_c, col_d = st.columns(4)
    if col_a.button("Load feasible sample"):
        st.session_state["payload_text"] = _sample_payload_text("A")
        _reset_validation_matrix_and_plan()
        st.rerun()
    if col_b.button("Load deadline issue sample"):
        st.session_state["payload_text"] = _sample_payload_text("C")
        _reset_validation_matrix_and_plan()
        st.rerun()
    if col_c.button("Load fleet shortage sample"):
        st.session_state["payload_text"] = _sample_payload_text("D")
        _reset_validation_matrix_and_plan()
        st.rerun()
    if col_d.button("Clear results"):
        _reset_validation_matrix_and_plan()
        st.rerun()

    st.text_area("Planning payload JSON", key="payload_text", height=360)
    st.divider()
    _render_scenario_persistence(client, payload, parse_error)
    if parse_error:
        st.error(parse_error)
        return
    if payload is None:
        return
    horizon = payload.get("planning_horizon", {})
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Scenario", str(payload.get("scenario_id", "not set")))
    col_2.metric("Timezone", str(payload.get("timezone", "not set")))
    if isinstance(horizon, dict):
        col_3.metric("Horizon start", str(horizon.get("start", "not set")))
    st.caption("API keys stay in backend configuration; this UI never asks planners for them.")


def _render_fleet_tab(payload: JsonPayload | None) -> None:
    st.subheader("Fleet")
    if payload is None:
        st.info("Fix setup JSON before reviewing fleet.")
        return
    vehicles = _table_rows(payload.get("vehicles"))
    shifts = _table_rows(payload.get("vehicle_shifts"))
    st.write("Vehicles")
    st.dataframe(pd.DataFrame(vehicles), hide_index=True, use_container_width=True)
    st.write("Shifts")
    st.dataframe(pd.DataFrame(shifts), hide_index=True, use_container_width=True)


def _render_tasks_tab(payload: JsonPayload | None) -> None:
    st.subheader("Tasks and import preview")
    if payload is None:
        st.info("Fix setup JSON before reviewing tasks.")
        return
    tasks = _table_rows(payload.get("tasks"))
    st.write("Current PO task lines")
    st.dataframe(pd.DataFrame(tasks), hide_index=True, use_container_width=True)

    uploaded_file = st.file_uploader("Preview task CSV/XLSX", type=("csv", "xlsx"))
    if uploaded_file is None:
        st.caption("Preview checks columns and blank required cells before backend validation.")
        return
    try:
        preview = _preview_uploaded_tasks(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read the uploaded file: {exc}")
        return

    if preview.has_blocking_errors:
        st.error("Import preview found errors to fix before these rows can be used.")
    elif preview.issues:
        st.warning("Import preview found warnings, but no blocking row errors.")
    else:
        st.success("Import preview did not find column or required-cell issues.")
    st.dataframe(pd.DataFrame(preview.rows), hide_index=True, use_container_width=True)
    if preview.issues:
        st.dataframe(pd.DataFrame(preview.issue_rows()), hide_index=True, use_container_width=True)


def _render_validation_tab(
    client: BackendClient,
    payload: JsonPayload | None,
    parse_error: str | None,
) -> None:
    st.subheader("Validation")
    if parse_error or payload is None:
        st.info("Fix setup JSON before validation.")
        return
    if st.button("Validate payload"):
        try:
            response = client.validate_plan(payload)
        except BackendClientError as exc:
            _render_backend_error(exc)
        else:
            st.session_state["validation_payload"] = response.raw["validation"]
            st.session_state["validation_source_fingerprint"] = validation_fingerprint(payload)
            st.session_state["last_request_id"] = response.request_id
            if response.validation and response.validation.valid:
                _set_flash("success", "Payload is valid and ready for matrix confirmation.")
            else:
                _set_flash("warning", "Payload has validation issues.")
            st.rerun()

    validation_payload = _state_value("validation_payload")
    if not isinstance(validation_payload, dict):
        st.info("No validation response yet.")
        return

    if _validation_is_valid(validation_payload):
        st.success("Latest validation response is valid.")
    else:
        st.error("Latest validation response contains blocking issues.")
    if st.session_state.get("last_request_id"):
        st.caption(f"Request ID: {st.session_state['last_request_id']}")

    issue_rows = validation_issue_rows(validation_payload)
    if issue_rows:
        st.write("Validation issues")
        st.dataframe(pd.DataFrame(issue_rows), hide_index=True, use_container_width=True)

    normalized_tasks = _normalized_task_rows(validation_payload)
    if normalized_tasks:
        st.write("Normalized task due datetimes")
        st.dataframe(
            pd.DataFrame(normalized_tasks)[
                ["task_id", "po_number", "task_type", "ready_at", "due_at", "due_event"]
            ],
            hide_index=True,
            use_container_width=True,
        )


def _render_matrix_tab(
    client: BackendClient,
    payload: JsonPayload | None,
    status_can_compute: bool,
    matrix_is_current: bool,
) -> None:
    st.subheader("Distance matrix")
    if payload is None:
        st.info("Fix setup JSON before matrix confirmation.")
        return
    if matrix_is_current:
        st.success("Matrix is current for the current locations.")
    elif _state_value("matrix_payload") is not None:
        st.warning("Stored matrix is stale because locations or routing options changed.")
    else:
        st.info("Confirm a matrix before optimization.")

    col_a, col_b = st.columns(2)
    embedded_matrix = payload.get("routing_matrix")
    if col_a.button(
        "Use routing matrix from payload",
        disabled=not isinstance(embedded_matrix, dict),
    ):
        st.session_state["matrix_payload"] = embedded_matrix
        st.session_state["matrix_source_location_fingerprint"] = location_fingerprint(payload)
        st.session_state["plan_payload"] = None
        st.session_state["plan_source_task_fingerprint"] = None
        _set_flash("success", "Embedded matrix is now active for this location set.")
        st.rerun()

    if col_b.button("Compute matrix from locations", disabled=not status_can_compute):
        try:
            locations = _routing_locations(payload)
            response = client.compute_matrix(locations)
        except ValueError as exc:
            st.error(str(exc))
        except BackendClientError as exc:
            _render_backend_error(exc)
        else:
            matrix = response.payload["matrix"]
            st.session_state["matrix_payload"] = matrix
            st.session_state["matrix_source_location_fingerprint"] = location_fingerprint(payload)
            st.session_state["plan_payload"] = None
            st.session_state["plan_source_task_fingerprint"] = None
            st.session_state["last_request_id"] = response.request_id
            cache_label = "cache hit" if response.payload.get("cache_hit") else "new matrix"
            _set_flash("success", f"Matrix ready ({cache_label}).")
            st.rerun()

    matrix_payload = _state_value("matrix_payload")
    if isinstance(matrix_payload, dict):
        location_ids = matrix_payload.get("location_ids") or matrix_payload.get("location_order")
        if isinstance(location_ids, list):
            col_1, col_2 = st.columns(2)
            col_1.metric("Matrix locations", str(len(location_ids)))
            col_2.metric("Source", str(matrix_payload.get("source", "unknown")))
        st.caption("Matrix calls happen only when you press a matrix button.")


def _render_optimize_tab(
    client: BackendClient,
    payload: JsonPayload | None,
    can_solve: bool,
) -> None:
    st.subheader("Optimization")
    if payload is None:
        st.info("Fix setup JSON before optimization.")
        return
    if not can_solve:
        st.info("Solve is enabled after current validation and matrix steps succeed.")
    if st.button("Solve route plan", disabled=not can_solve):
        matrix_payload = _state_value("matrix_payload")
        payload_with_matrix = attach_matrix_to_payload(payload, matrix_payload)
        try:
            response = client.solve_plan(payload_with_matrix)
        except BackendClientError as exc:
            _render_backend_error(exc)
        else:
            st.session_state["validation_payload"] = response.raw["validation"]
            st.session_state["validation_source_fingerprint"] = validation_fingerprint(payload)
            st.session_state["plan_payload"] = response.raw["plan"]
            st.session_state["plan_source_task_fingerprint"] = task_fingerprint(payload)
            st.session_state["last_request_id"] = response.request_id
            plan_status = response.plan.status if response.plan else "unknown"
            if plan_status == "FEASIBLE":
                _set_flash("success", "All valid PO tasks were scheduled before their due dates.")
            else:
                _set_flash(
                    "warning",
                    "A partial or infeasible plan was returned. Review diagnostics.",
                )
            st.rerun()


def _render_route_map(payload: JsonPayload | None, plan_payload: JsonPayload) -> None:
    st.write("Route map")
    map_data = build_route_map_data(plan_payload, _location_rows(payload))
    if not map_data.markers or map_data.center is None:
        st.info("No mappable route stops with latitude/longitude are available.")
        return

    show_lines = st.checkbox(
        "Show route-order preview lines",
        value=True,
        help=("Lines connect backend stop order directly. They are not billable road polylines."),
    )
    route_map = _folium_map(map_data, show_lines=show_lines)
    st_folium(route_map, height=500, use_container_width=True)
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


def _render_plan_exports(plan_payload: JsonPayload) -> None:
    st.write("Exports")
    tables = build_export_tables(plan_payload)
    if tables.route_summary_rows:
        st.write("Route summary")
        st.dataframe(
            pd.DataFrame(tables.route_summary_rows),
            hide_index=True,
            use_container_width=True,
        )

    plan_id = str(plan_payload.get("plan_id", "route-plan"))
    safe_plan_id = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in plan_id
    )
    col_route, col_diag, col_book = st.columns(3)
    col_route.download_button(
        "Download route stops CSV",
        data=route_stops_csv_bytes(plan_payload),
        file_name=f"{safe_plan_id}_route_stops.csv",
        mime="text/csv",
    )
    col_diag.download_button(
        "Download diagnostics CSV",
        data=diagnostics_csv_bytes(plan_payload),
        file_name=f"{safe_plan_id}_diagnostics.csv",
        mime="text/csv",
    )
    col_book.download_button(
        "Download plan workbook XLSX",
        data=workbook_bytes(plan_payload),
        file_name=f"{safe_plan_id}_plan.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _render_results_tab(
    payload: JsonPayload | None,
    plan_payload: JsonPayload | None,
    plan_is_current: bool,
    stale_plan_hidden: bool,
) -> None:
    st.subheader("Results")
    if stale_plan_hidden:
        st.warning("A previous solution is hidden because the current inputs changed.")
        return
    if not plan_payload or not plan_is_current:
        st.info("No current solution yet.")
        return

    scheduled = plan_payload.get("scheduled_task_ids", [])
    unscheduled = plan_payload.get("unscheduled_task_ids", [])
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Plan status", str(plan_payload.get("status", "unknown")))
    col_2.metric("Scheduled POs", str(len(scheduled) if isinstance(scheduled, list) else 0))
    col_3.metric(
        "Unscheduled POs",
        str(len(unscheduled) if isinstance(unscheduled, list) else 0),
    )

    route_rows = _route_rows(plan_payload)
    if route_rows:
        st.write("Route stops")
        st.dataframe(pd.DataFrame(route_rows), hide_index=True, use_container_width=True)
    diagnostics = _diagnostic_rows(plan_payload)
    if diagnostics:
        st.write("Diagnostics for infeasible or unscheduled POs")
        st.dataframe(pd.DataFrame(diagnostics), hide_index=True, use_container_width=True)
    elif route_rows:
        st.success("No unscheduled PO diagnostics were returned.")
    st.divider()
    _render_route_map(payload, plan_payload)
    st.divider()
    _render_plan_exports(plan_payload)


def render_app() -> None:
    """Render the planning app."""
    st.set_page_config(
        page_title="Manufacturing PO Route Optimizer",
        page_icon="🚚",
        layout="wide",
    )
    _ensure_session_state()

    st.title("Manufacturing PO Route Optimizer")
    st.caption("Deadline-aware pickup, drop, and pickup-drop planning for ready POs")
    client = BackendClient.from_environment()
    _render_backend_status(client)
    _render_flash()

    payload, parse_error = _current_payload()
    validation_payload = _state_value("validation_payload")
    status = workflow_status(
        payload or {},
        validation_valid=_validation_is_valid(validation_payload),
        validation_source_fingerprint=_state_value("validation_source_fingerprint"),
        matrix_payload=_state_value("matrix_payload"),
        matrix_source_location_fingerprint=_state_value("matrix_source_location_fingerprint"),
        plan_payload=_state_value("plan_payload"),
        plan_source_task_fingerprint=_state_value("plan_source_task_fingerprint"),
    )

    if validation_payload is not None and not status.validation_is_current:
        st.warning("Validation is stale. Revalidate before matrix calculation or solving.")
    if _state_value("matrix_payload") is not None and not status.matrix_is_current:
        st.warning("Matrix is stale. Reconfirm or recompute it before solving.")
    if status.stale_plan_hidden:
        st.warning("Previous plan is stale and will stay hidden until you solve again.")

    tabs = st.tabs(
        [
            "Setup",
            "Fleet",
            "Tasks & import",
            "Validation",
            "Matrix",
            "Optimization",
            "Results",
        ]
    )
    with tabs[0]:
        _render_setup_tab(client, payload, parse_error)
    with tabs[1]:
        _render_fleet_tab(payload)
    with tabs[2]:
        _render_tasks_tab(payload)
    with tabs[3]:
        _render_validation_tab(client, payload, parse_error)
    with tabs[4]:
        _render_matrix_tab(
            client,
            payload,
            status.can_compute_matrix,
            status.matrix_is_current,
        )
    with tabs[5]:
        _render_optimize_tab(client, payload, status.can_solve)
    with tabs[6]:
        plan_payload = _state_value("plan_payload")
        _render_results_tab(
            payload,
            plan_payload if isinstance(plan_payload, dict) else None,
            status.plan_is_current,
            status.stale_plan_hidden,
        )


if __name__ == "__main__":
    render_app()
