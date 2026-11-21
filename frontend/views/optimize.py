"""Optimize: settings, pre-flight checks, and the solve action (plan §9.7).

Settings are part of the scenario (``optimization_options``), so they are saved with it
and shown in the JSON view. Changing them makes the current plan stale but never the
travel times: no setting here calls Google.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.optimization import (
    BALANCE_STRENGTHS,
    BALANCE_WORKLOAD,
    HARD_CONSTRAINTS_NOTE,
    MAX_BUFFER_PERCENT,
    MAX_EXTRA_TRUCK_COST_KM,
    MINIMIZE_TRUCKS,
    OBJECTIVE_HELP,
    OBJECTIVES,
    SEARCH_EFFORT_HELP,
    SEARCH_EFFORTS,
    THOROUGH,
    buffer_percent,
    current_options,
    effective_time_limit,
    options_summary,
    set_options,
    stored_options,
)
from frontend.state.scenario_state import ScenarioEditError
from frontend.state.workspace import record_plan, solve_payload
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    go_to,
    render_backend_error,
    row_revision,
    set_flash,
    set_workspace,
)

FALLBACK_DEFAULT_TIME_LIMIT = 10
FALLBACK_MAX_TIME_LIMIT = 120


def _limits(ctx: AppContext) -> tuple[int, int]:
    if ctx.config is None:
        return FALLBACK_DEFAULT_TIME_LIMIT, FALLBACK_MAX_TIME_LIMIT
    return ctx.config.solver_time_limit_seconds, ctx.config.solver_max_time_limit_seconds


def render(ctx: AppContext) -> None:
    st.header("Optimize")
    status = ctx.status
    checks = (
        ("Inputs are valid", status.validation_valid),
        ("Every location is resolved", status.locations_usable),
        ("Travel times are current", status.matrix_current),
        ("Backend is connected", ctx.connected),
    )
    for label, passed in checks:
        st.markdown(f"{'✅' if passed else '⬜'} {label}")

    _render_settings(ctx)
    st.caption(HARD_CONSTRAINTS_NOTE)

    default_limit, max_limit = _limits(ctx)
    scenario = get_workspace().scenario
    limit = effective_time_limit(
        scenario, default_time_limit=default_limit, max_time_limit=max_limit
    )
    options = current_options(scenario, default_time_limit=default_limit)
    if options["search_effort"] == THOROUGH:
        st.caption(
            f"Thorough search takes about {limit} s, and up to {2 * limit} s when not "
            "everything fits."
        )
    if not status.can_solve:
        st.info("Solving is enabled once the inputs are valid and travel times are current.")
    clicked = st.button("Solve route plan", type="primary", disabled=not status.can_solve)
    if clicked and status.can_solve:
        _solve(ctx, limit)


def _render_settings(ctx: AppContext) -> None:
    default_limit, max_limit = _limits(ctx)
    scenario = get_workspace().scenario
    options = current_options(scenario, default_time_limit=default_limit)
    st.subheader("Settings")
    st.caption(options_summary({**options}))
    prefix = f"opt-{row_revision(stored_options(scenario))}"
    with st.form("optimization_options"):
        objective = st.radio(
            "Objective",
            options=list(OBJECTIVES),
            index=_index(OBJECTIVES, options["objective_mode"]),
            format_func=lambda key: OBJECTIVES[key],
            captions=[OBJECTIVE_HELP[key] for key in OBJECTIVES],
            key=f"{prefix}-objective",
        )
        effort = st.radio(
            "Search effort",
            options=list(SEARCH_EFFORTS),
            index=_index(SEARCH_EFFORTS, options["search_effort"]),
            format_func=lambda key: SEARCH_EFFORTS[key],
            captions=[SEARCH_EFFORT_HELP[key] for key in SEARCH_EFFORTS],
            horizontal=True,
            key=f"{prefix}-effort",
        )
        time_limit = st.slider(
            "Time limit (seconds)",
            min_value=1,
            max_value=max_limit,
            value=min(max(int(options["time_limit_seconds"]), 1), max_limit),
            help=(
                "The longest the solver searches. Standard search usually stops much "
                f"sooner. This server allows up to {max_limit} s; its default is "
                f"{default_limit} s."
            ),
            key=f"{prefix}-time-limit",
        )
        buffer = st.slider(
            "Travel-time buffer (%)",
            min_value=0,
            max_value=MAX_BUFFER_PERCENT,
            value=min(max(buffer_percent(options["travel_time_factor"]), 0), MAX_BUFFER_PERCENT),
            step=5,
            help=(
                "Google's driving times are for cars. A buffer of 20 % plans every leg "
                "20 % slower. Changing it needs no new travel-time calculation."
            ),
            key=f"{prefix}-buffer",
        )
        with st.expander("Advanced"):
            extra_truck_km = st.number_input(
                "Cost of an extra truck (km)",
                min_value=0,
                max_value=MAX_EXTRA_TRUCK_COST_KM,
                value=int(options["extra_truck_cost_km"]),
                step=50,
                help=(
                    "Fewest trucks only: another truck is used when it saves more than "
                    "this many kilometres of driving."
                ),
                key=f"{prefix}-extra-truck",
            )
            strength = st.radio(
                "Balance strength",
                options=list(BALANCE_STRENGTHS),
                index=_index(BALANCE_STRENGTHS, options["balance_strength"]),
                format_func=lambda key: BALANCE_STRENGTHS[key],
                horizontal=True,
                help=(
                    "Balanced workload only: how many extra kilometres an hour less on "
                    "the longest route is worth (Light 18 km, Medium 36 km, Strong 72 km)."
                ),
                key=f"{prefix}-strength",
            )
        submitted = st.form_submit_button("Save settings")
    if submitted:
        try:
            updated = set_options(
                scenario,
                objective_mode=str(objective),
                search_effort=str(effort),
                time_limit_seconds=int(time_limit),
                buffer_percent=int(buffer),
                extra_truck_cost_km=int(extra_truck_km),
                balance_strength=str(strength),
                default_time_limit=default_limit,
                max_time_limit=max_limit,
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        if updated == scenario:
            st.info("Nothing changed.")
            return
        note = ""
        if objective != BALANCE_WORKLOAD and strength != "MEDIUM":
            note = " Balance strength applies only to Balanced workload."
        elif objective != MINIMIZE_TRUCKS and extra_truck_km != 1_000:
            note = " The cost of an extra truck applies only to Fewest trucks."
        commit_edit(updated, message=f"Settings saved. Solve again to use them.{note}")


def _index(choices: Any, value: Any) -> int:
    keys = list(choices)
    return keys.index(value) if value in keys else 0


def _solve(ctx: AppContext, time_limit: int) -> None:
    workspace = get_workspace()
    try:
        with st.spinner(f"Solving: this can take up to {2 * time_limit} s."):
            response = ctx.client.solve_plan(
                solve_payload(workspace), time_limit_seconds=time_limit
            )
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    plan = response.raw.get("plan")
    if not isinstance(plan, dict):
        st.error("The solve response did not contain a plan.")
        return
    validation = response.raw.get("validation")
    set_workspace(
        record_plan(
            workspace,
            plan=plan,
            validation=validation if isinstance(validation, dict) else None,
            request_id=response.request_id,
        )
    )
    if plan.get("status") == "FEASIBLE":
        set_flash("success", "All valid PO tasks were scheduled before their due dates.")
    else:
        set_flash("warning", "A partial or infeasible plan was returned. Review diagnostics.")
    go_to("results")
