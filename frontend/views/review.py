"""Review: automatic validation results grouped by section, with links to the rows.

Validation runs whenever the scenario changes (principle 9). Each issue names its
section and row, and "Go to" opens that row's form on its page (plan §9.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st

from frontend.state.scenario_state import ScenarioEditError
from frontend.state.settings import fit_period
from frontend.state.timeutil import format_local
from frontend.state.workspace import validation_issue_rows
from frontend.views import fleet, locations, tasks
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    go_to,
    next_step_button,
    table,
)
from frontend.views.validation import run_validation

SECTIONS: tuple[tuple[str, str, str], ...] = (
    # (section, heading, page)
    ("scenario", "Scenario", "scenario"),
    ("locations", "Locations", "locations"),
    ("vehicles", "Trucks", "fleet"),
    ("vehicle_shifts", "Shifts", "fleet"),
    ("tasks", "Tasks", "tasks"),
    ("routing_matrix", "Travel times", "travel_times"),
    ("optimization_options", "Optimization settings", "optimize"),
    ("", "Other", "json"),
)
EDIT_TARGETS: Mapping[str, str] = {
    "locations": locations.EDIT_NEXT_KEY,
    "vehicles": fleet.TRUCK_EDIT_NEXT_KEY,
    "vehicle_shifts": fleet.SHIFT_EDIT_NEXT_KEY,
    "tasks": tasks.EDIT_NEXT_KEY,
}
MAX_LINKED_ISSUES = 40


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
            _render_issues(issues)
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


def _render_issues(issues: list[dict[str, Any]]) -> None:
    st.subheader("Issues")
    if any(issue.get("code") == "OUTSIDE_PLANNING_HORIZON" for issue in issues):
        st.caption("Some shifts or tasks fall outside the planning period.")
        if st.button("Fit the planning period to shifts and tasks", key="review-fit-period"):
            try:
                updated = fit_period(get_workspace().scenario)
            except ScenarioEditError as exc:
                st.error(str(exc))
            else:
                commit_edit(updated, message="The planning period now covers every shift and task.")
    known = {section for section, _, _ in SECTIONS}
    for section, heading, page in SECTIONS:
        grouped = [
            issue
            for issue in issues
            if (issue.get("section") or "") == section
            or (section == "" and (issue.get("section") or "") not in known)
        ]
        if not grouped:
            continue
        errors = sum(issue.get("severity") == "ERROR" for issue in grouped)
        counts = f"{errors} error(s), {len(grouped) - errors} warning(s)"
        with st.expander(f"{heading}: {counts}", expanded=errors > 0):
            for index, issue in enumerate(grouped[:MAX_LINKED_ISSUES]):
                _render_issue(issue, section, page, index)
            if len(grouped) > MAX_LINKED_ISSUES:
                st.caption(f"{len(grouped) - MAX_LINKED_ISSUES} more:")
                table(
                    grouped[MAX_LINKED_ISSUES:],
                    columns=("severity", "code", "item_id", "row_number", "field", "message"),
                )


def _render_issue(issue: Mapping[str, Any], section: str, page: str, index: int) -> None:
    icon = "⛔" if issue.get("severity") == "ERROR" else "⚠️"
    item_id = issue.get("item_id") or issue.get("task_id")
    where = f" — {item_id}" if item_id else ""
    col_text, col_go = st.columns([5, 1])
    col_text.markdown(f"{icon} **{issue.get('code')}**{where}  \n{issue.get('message')}")
    if col_go.button("Go to", key=f"review-go-{section or 'other'}-{index}"):
        target = EDIT_TARGETS.get(section)
        if target and item_id:
            st.session_state[target] = str(item_id)
        go_to(page)


def _normalized_tasks(validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    request = validation.get("normalized_request") if validation else None
    if not isinstance(request, dict) or not isinstance(request.get("tasks"), list):
        return []
    return [task for task in request["tasks"] if isinstance(task, dict)]
