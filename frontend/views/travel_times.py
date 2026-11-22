"""Travel times: readiness, cost estimate, confirmation, calculation, routing options.

"Calculate travel times" is the only billable matrix action (plan §8.7). Before it the
page shows what the calculation would send, from ``/matrices/estimate``, which never
calls Google. Above the confirmation threshold the planner must tick a confirmation.
Google travel times are kept only for this session (decision D6).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.locations import unused_ids
from frontend.state.readiness import USABLE_READINESS
from frontend.state.results import GOOGLE_MATRIX_SOURCE
from frontend.state.scenario_state import ScenarioEditError, set_fields
from frontend.state.timeutil import (
    format_local,
    local_iso,
    parse_datetime_text,
    split_for_form,
    to_local,
    wall_clock_text,
)
from frontend.state.workspace import (
    activate_embedded_matrix,
    current_estimate,
    matrix_is_storable,
    matrix_matches_locations,
    record_estimate,
    record_matrix,
    routing_locations,
)
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    go_to,
    next_step_button,
    render_backend_error,
    render_google_attribution,
    set_flash,
    set_workspace,
)

CONFIRM_LARGE_KEY = "confirm_large_matrix"
CONFIRM_FORCE_KEY = "confirm_force_refresh"
CONFIRM_ROUND_KEY = "travel_confirm_round"
"""Bumped after each calculation, so every confirmation box starts unticked again."""
DEFAULT_MAX_MATRIX_LOCATIONS = 100
"""The backend's limit when its config is not known (``GET /config`` → limits)."""
PREFERENCE_LABELS = {
    "TRAFFIC_UNAWARE": "Typical driving times (no live traffic)",
    "TRAFFIC_AWARE": "With traffic at the departure time",
    "TRAFFIC_AWARE_OPTIMAL": "With traffic, best-quality routes",
}
SOURCE_LABELS = {
    "google_routes": "Google",
    "deterministic_offline_fixture": "sample data",
    "fake": "offline test provider",
}


def render(ctx: AppContext) -> None:
    st.header("Travel times")
    workspace = get_workspace()
    derived = workspace.derived
    status = ctx.status
    matrix = derived.matrix

    if status.matrix_current and matrix is not None:
        origin = "from the scenario JSON" if derived.matrix_origin == "json" else "calculated"
        source = SOURCE_LABELS.get(str(matrix.get("source")), str(matrix.get("source", "")))
        cache = ", served from the backend cache" if derived.matrix_cache_hit else ""
        st.success(f"Travel times are current: {origin} ({source}{cache}).")
    elif matrix is not None:
        st.warning("Travel times are out of date: locations or routing options changed since.")
    else:
        st.info("No travel times yet.")
    if matrix is not None and not matrix_is_storable(matrix):
        st.caption(
            "Google travel times are kept only for this session. They are not saved with "
            "the scenario and are recalculated after it is opened again."
        )

    _render_readiness(ctx)
    st.divider()
    _render_calculate(ctx)
    _render_embedded(ctx)
    st.divider()
    _render_advanced(ctx)
    if matrix is not None:
        col_1, col_2, col_3 = st.columns(3)
        col_1.metric("Locations in travel times", str(len(matrix.get("location_ids", []))))
        col_2.metric(
            "Source",
            SOURCE_LABELS.get(str(matrix.get("source")), str(matrix.get("source", "unknown"))),
        )
        created = matrix.get("created_at")
        timezone = str(workspace.scenario.get("timezone") or "America/Toronto")
        col_3.metric("Calculated", format_local(str(created), timezone) if created else "—")
        render_google_attribution(
            ctx, travel_times=str(matrix.get("source")) == GOOGLE_MATRIX_SOURCE
        )
    st.caption("Google is called only when you press Calculate travel times.")
    next_step_button("optimize", "Next: Optimize")


def _render_readiness(ctx: AppContext) -> None:
    status = ctx.status
    total = len(status.readiness)
    usable = sum(value in USABLE_READINESS for value in status.readiness.values())
    if total and usable == total:
        st.markdown(f"✅ All {total} locations are resolved.")
    else:
        st.markdown(f"⬜ {usable} of {total} locations are resolved.")
        if st.button("Resolve them on the Locations page", key="travel-go-locations"):
            go_to("locations")
    unused = unused_ids(get_workspace().scenario)
    if unused:
        st.caption(
            f"{len(unused)} location(s) are not used by any task or shift "
            f"({', '.join(unused)}). Each one makes the travel-time calculation larger; "
            "delete them on the Locations page if they are not needed."
        )


def _render_calculate(ctx: AppContext) -> None:
    st.subheader("Calculate")
    status = ctx.status
    if status.matrix_current:
        st.caption(
            "Nothing to calculate: the travel times match the current locations and "
            "routing options. To recalculate anyway, open Advanced below."
        )
        return
    if not status.can_compute_matrix or not ctx.connected:
        st.caption(_why_not(ctx))
        st.button("Calculate travel times", disabled=True, key="calculate-disabled")
        return
    blocker = _calculation_blocker(ctx)
    if blocker:
        st.warning(blocker)
        st.button("Calculate travel times", disabled=True, key="calculate-blocked")
        return
    estimate = _estimate(ctx)
    if estimate is None:
        return
    col_1, col_2, col_3, col_4 = st.columns(4)
    col_1.metric("Locations", str(estimate.get("location_count", "—")))
    col_2.metric("Billable elements", f"{int(estimate.get('billable_element_count', 0)):,}")
    col_3.metric("Google requests", str(estimate.get("billable_request_count", 0)))
    col_4.metric("Backend cache", _cache_text(estimate))
    confirmed = True
    if estimate.get("confirmation_required"):
        confirmed = st.checkbox(
            f"I understand this sends {int(estimate.get('billable_element_count', 0)):,} "
            "billable elements to Google",
            key=_confirm_key(CONFIRM_LARGE_KEY),
        )
    clicked = st.button("Calculate travel times", type="primary", disabled=not confirmed)
    if clicked and confirmed:
        _calculate(ctx, force_refresh=False)


def _render_embedded(ctx: AppContext) -> None:
    workspace = get_workspace()
    embedded = workspace.derived.embedded_matrix
    if embedded is None:
        return
    usable = matrix_matches_locations(embedded, workspace.scenario)
    if (
        st.button(
            "Use travel times from the scenario JSON",
            disabled=not usable or ctx.status.matrix_current,
            help="Uses the routing_matrix that came with the JSON; no Google call.",
        )
        and usable
    ):
        set_workspace(activate_embedded_matrix(workspace))
        set_flash("success", "The travel times from the JSON are now active.")
        st.rerun()
    if not usable:
        st.caption("The travel times in the JSON do not cover exactly these locations.")


def _render_advanced(ctx: AppContext) -> None:
    workspace = get_workspace()
    scenario = workspace.scenario
    options = scenario.get("routing_options")
    current = options if isinstance(options, dict) else {}
    timezone = str(scenario.get("timezone") or "America/Toronto")
    with st.expander("Advanced: routing options and recalculation"):
        preferences = list(PREFERENCE_LABELS)
        preference = str(current.get("routing_preference") or "TRAFFIC_UNAWARE")
        departure = current.get("departure_time")
        with st.form("routing_options"):
            chosen = st.selectbox(
                "Driving times",
                options=preferences,
                index=preferences.index(preference) if preference in preferences else 0,
                format_func=lambda key: PREFERENCE_LABELS[key],
                help="Traffic-aware options are billed by Google at a higher rate.",
            )
            use_departure = st.checkbox(
                "Set a departure time (used by the traffic options; must be in the future)",
                value=bool(departure),
            )
            day, clock = (
                split_for_form(str(departure), timezone)
                if departure
                else (ctx.now.date(), time(7, 0))
            )
            col_day, col_time = st.columns(2)
            departure_day = col_day.date_input("Departure date", value=day)
            departure_time = col_time.time_input("Departure time", value=clock, step=900)
            submitted = st.form_submit_button("Save routing options")
        if submitted:
            _save_options(
                scenario,
                preference=str(chosen),
                departure=(departure_day, departure_time) if use_departure else None,
                timezone=timezone,
                now=ctx.now,
            )

        st.markdown("**Recalculate**")
        st.caption(
            "Calculates again even when the travel times are current. This is billable "
            "and is rarely needed."
        )
        can_force = ctx.status.can_compute_matrix and ctx.connected
        force_confirmed = st.checkbox(
            "I want to recalculate and accept the Google charge",
            key=_confirm_key(CONFIRM_FORCE_KEY),
            disabled=not can_force,
        )
        if st.button("Recalculate travel times", disabled=not (can_force and force_confirmed)) and (
            can_force and force_confirmed
        ):
            _calculate(ctx, force_refresh=True)


def _save_options(
    scenario: dict[str, Any],
    *,
    preference: str,
    departure: tuple[Any, Any] | None,
    timezone: str,
    now: datetime,
) -> None:
    options: dict[str, Any] = {}
    if preference != "TRAFFIC_UNAWARE":
        options["routing_preference"] = preference
    if departure is not None:
        day, clock = departure
        if not isinstance(day, date) or not isinstance(clock, time):
            st.error("Choose a departure date and time.")
            return
        try:
            options["departure_time"] = local_iso(wall_clock_text(day, clock), timezone)
        except ValueError as exc:
            st.error(str(exc))
            return
        if to_local(options["departure_time"], timezone) <= now:
            st.error("Choose a departure time in the future: Google rejects one in the past.")
            return
    try:
        updated = set_fields(scenario, routing_options=options or None)
    except ScenarioEditError as exc:
        st.error(str(exc))
        return
    commit_edit(updated, message="Routing options saved. Travel times need recalculating.")


def _estimate(ctx: AppContext) -> dict[str, Any] | None:
    """The estimate for the current locations and options, asked for once per change."""
    workspace = get_workspace()
    remembered = current_estimate(workspace)
    if remembered is not None:
        return remembered
    try:
        locations = routing_locations(workspace.scenario)
        response = ctx.client.estimate_matrix(locations, options=_routing_options(workspace))
    except ValueError as exc:
        st.error(str(exc))
        return None
    except BackendClientError as exc:
        render_backend_error(exc)
        return None
    set_workspace(record_estimate(workspace, response.payload))
    return response.payload


def _calculate(ctx: AppContext, *, force_refresh: bool) -> None:
    workspace = get_workspace()
    try:
        locations = routing_locations(workspace.scenario)
        response = ctx.client.compute_matrix(
            locations, force_refresh=force_refresh, options=_routing_options(workspace)
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
    st.session_state[CONFIRM_ROUND_KEY] = int(st.session_state.get(CONFIRM_ROUND_KEY, 0)) + 1
    set_flash(
        "success",
        "Travel times ready"
        + (" (served from the backend cache, no charge)." if cache_hit else "."),
    )
    st.rerun()


def _confirm_key(base: str) -> str:
    return f"{base}-{st.session_state.get(CONFIRM_ROUND_KEY, 0)}"


def _routing_options(workspace: Any) -> dict[str, Any] | None:
    options = workspace.scenario.get("routing_options")
    return options if isinstance(options, dict) and options else None


def _cache_text(estimate: dict[str, Any]) -> str:
    if estimate.get("cache_hit"):
        return "Cached"
    if estimate.get("cache_enabled") is False:
        return "Not stored"
    return "Not cached"


def _calculation_blocker(ctx: AppContext) -> str | None:
    """Why a calculation would be refused before it is sent, in planner words."""
    scenario = get_workspace().scenario
    locations = scenario.get("locations")
    count = len(locations) if isinstance(locations, list) else 0
    limit = DEFAULT_MAX_MATRIX_LOCATIONS
    if ctx.config is not None:
        limit = int(ctx.config.limits.get("max_matrix_locations", limit))
    if count > limit:
        return (
            f"Travel times can be calculated for at most {limit} locations at a time, and "
            f"this scenario has {count}. Delete locations that no task or shift uses, or "
            "split the scenario into smaller ones."
        )
    departure = past_departure(scenario, ctx.now)
    if departure is not None:
        return (
            f"The departure time under Advanced ({departure}) is in the past, and Google "
            "accepts only a future one. Clear it or choose a later time before calculating."
        )
    return None


def past_departure(scenario: dict[str, Any], now: datetime) -> str | None:
    """The routing options' departure time as plant-local text, if it has passed."""
    options = scenario.get("routing_options")
    departure = options.get("departure_time") if isinstance(options, dict) else None
    if not isinstance(departure, str) or not departure:
        return None
    timezone = str(scenario.get("timezone") or "America/Toronto")
    try:
        instant = parse_datetime_text(departure)
        local = to_local(instant, timezone)
    except ValueError:
        return None
    return format_local(departure, timezone) if local <= now else None


def _why_not(ctx: AppContext) -> str:
    status = ctx.status
    if not ctx.connected:
        return "Calculation needs the backend."
    if not status.validation_valid:
        return "Calculation needs a valid scenario (see Review)."
    if not status.locations_usable:
        return "Calculation needs every location resolved (see Locations)."
    return "Calculation is not available."
