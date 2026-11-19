"""Optimize: pre-flight checks and the solve action."""

from __future__ import annotations

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.workspace import record_plan, solve_payload
from frontend.views.components import (
    AppContext,
    get_workspace,
    go_to,
    render_backend_error,
    set_flash,
    set_workspace,
)


def render(ctx: AppContext) -> None:
    st.header("Optimize")
    status = ctx.status
    checks = (
        ("Inputs are valid", status.validation_valid),
        ("Travel times are current", status.matrix_current),
        ("Backend is connected", ctx.connected),
    )
    for label, passed in checks:
        st.markdown(f"{'✅' if passed else '⬜'} {label}")
    if not status.can_solve:
        st.info("Solving is enabled once the inputs are valid and travel times are current.")
    clicked = st.button("Solve route plan", type="primary", disabled=not status.can_solve)
    if clicked and status.can_solve:
        _solve(ctx)


def _solve(ctx: AppContext) -> None:
    workspace = get_workspace()
    try:
        response = ctx.client.solve_plan(solve_payload(workspace))
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
