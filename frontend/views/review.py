"""Review: automatic validation results and normalised task times."""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.state.timeutil import format_local
from frontend.state.workspace import validation_issue_rows
from frontend.views.components import (
    AppContext,
    get_workspace,
    next_step_button,
    table,
)
from frontend.views.validation import run_validation


def render(ctx: AppContext) -> None:
    st.header("Review")
    st.caption("The scenario is checked automatically whenever it changes.")
    workspace = get_workspace()
    derived = workspace.derived
    status = ctx.status

    if not status.validation_current:
        if derived.validation_error:
            st.warning(f"Validation could not run: {derived.validation_error}")
        else:
            st.info("Not checked yet. The backend checks the scenario as soon as it is reachable.")
    elif status.validation_valid:
        warnings = f" with {status.warning_count} warning(s)" if status.warning_count else ""
        st.success(f"The scenario is valid{warnings}.")
    else:
        st.error(f"The scenario has {status.error_count} error(s) that block planning.")
    if derived.validation_request_id and status.validation_current:
        st.caption(f"Request ID: {derived.validation_request_id}")
    if st.button("Revalidate", disabled=not ctx.connected) and ctx.connected:
        run_validation(ctx.client, force=True)
        st.rerun()

    if status.validation_current:
        issues = validation_issue_rows(derived.validation)
        if issues:
            st.subheader("Issues")
            table(issues)
        normalized = _normalized_tasks(derived.validation)
        if normalized:
            timezone = str(workspace.scenario.get("timezone", "America/Toronto"))
            st.subheader("Task times")
            st.caption(f"Plant-local times ({timezone}) as the backend understood them.")
            table(
                [
                    {
                        "task_id": task.get("task_id"),
                        "po_number": task.get("po_number"),
                        "task_type": task.get("task_type"),
                        "ready (local)": format_local(task.get("ready_at"), timezone),
                        "due (local)": format_local(task.get("due_at"), timezone),
                        "due_event": task.get("due_event"),
                        "ready_at (UTC)": task.get("ready_at"),
                        "due_at (UTC)": task.get("due_at"),
                    }
                    for task in normalized
                ]
            )
    next_step_button("travel_times", "Next: Travel times")


def _normalized_tasks(validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    request = validation.get("normalized_request") if validation else None
    if not isinstance(request, dict) or not isinstance(request.get("tasks"), list):
        return []
    return [task for task in request["tasks"] if isinstance(task, dict)]
