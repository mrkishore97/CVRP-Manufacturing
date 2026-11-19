"""Travel times: the active matrix, location readiness, and the matrix actions."""

from __future__ import annotations

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.readiness import LocationReadiness
from frontend.state.scenario_state import rows
from frontend.state.workspace import (
    activate_embedded_matrix,
    matrix_matches_locations,
    record_matrix,
    routing_locations,
)
from frontend.views.components import (
    AppContext,
    get_workspace,
    next_step_button,
    render_backend_error,
    set_flash,
    set_workspace,
    table,
)

READINESS_LABELS = {
    LocationReadiness.READY: "Resolved",
    LocationReadiness.SUPPLIED: "Supplied coordinates",
    LocationReadiness.NOT_RESOLVED: "Not resolved yet",
    LocationReadiness.NEEDS_REVIEW: "Needs review",
    LocationReadiness.FAILED: "Not found",
    LocationReadiness.STALE: "Address changed — resolve again",
    LocationReadiness.EXPIRED: "Older than 30 days — resolve again",
}


def render(ctx: AppContext) -> None:
    st.header("Travel times")
    workspace = get_workspace()
    derived = workspace.derived
    status = ctx.status

    if status.matrix_current:
        origin = "from the scenario JSON" if derived.matrix_origin == "json" else "calculated"
        cache = " (cache hit)" if derived.matrix_cache_hit else ""
        st.success(f"Travel times are current — {origin}{cache}.")
    elif derived.matrix is not None:
        st.warning("Travel times are stale: locations or routing options changed since.")
    else:
        st.info("No travel times yet. Use the ones in the scenario JSON or calculate them.")

    st.subheader("Locations")
    table(
        [
            {
                "location_id": location.get("location_id"),
                "name": location.get("name"),
                "address": location.get("address"),
                "status": READINESS_LABELS[
                    status.readiness.get(
                        str(location.get("location_id")), LocationReadiness.NOT_RESOLVED
                    )
                ],
            }
            for location in rows(workspace.scenario, "locations")
        ]
    )

    embedded = derived.embedded_matrix
    embedded_usable = embedded is not None and matrix_matches_locations(
        embedded, workspace.scenario
    )
    col_json, col_calculate = st.columns(2)
    use_json = col_json.button(
        "Use travel times from JSON",
        disabled=not embedded_usable,
        help="Use the routing_matrix that came with the scenario JSON; no Google call.",
    )
    if use_json and embedded_usable:
        set_workspace(activate_embedded_matrix(workspace))
        set_flash("success", "The travel times from the JSON are now active.")
        st.rerun()
    if embedded is not None and not embedded_usable:
        col_json.caption("The travel times in the JSON do not cover exactly these locations.")

    can_calculate = status.can_compute_matrix and ctx.connected
    calculate = col_calculate.button(
        "Calculate travel times",
        disabled=not can_calculate,
        help="Calls Google through the backend; repeated requests are served from its cache.",
    )
    if calculate and can_calculate:
        _calculate(ctx)
    if not status.can_compute_matrix:
        col_calculate.caption(_why_not(ctx))

    matrix = derived.matrix
    if matrix is not None:
        col_1, col_2 = st.columns(2)
        col_1.metric("Matrix locations", str(len(matrix.get("location_ids", []))))
        col_2.metric("Source", str(matrix.get("source", "unknown")))
    st.caption("Google is called only when you press Calculate travel times.")
    next_step_button("optimize", "Next: Optimize")


def _calculate(ctx: AppContext) -> None:
    workspace = get_workspace()
    try:
        locations = routing_locations(workspace.scenario)
        options = workspace.scenario.get("routing_options")
        response = ctx.client.compute_matrix(
            locations, options=options if isinstance(options, dict) else None
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    cache_hit = bool(response.payload.get("cache_hit"))
    set_workspace(
        record_matrix(
            workspace, response.payload["matrix"], origin="calculated", cache_hit=cache_hit
        )
    )
    set_flash("success", f"Travel times ready ({'cache hit' if cache_hit else 'new matrix'}).")
    st.rerun()


def _why_not(ctx: AppContext) -> str:
    status = ctx.status
    if not status.validation_valid:
        return "Calculation needs a valid scenario (see Review)."
    if not status.locations_usable:
        return "Calculation needs every location resolved."
    return "The backend is not connected."
