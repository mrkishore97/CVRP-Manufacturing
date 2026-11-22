"""Opening another scenario: a sample, a saved scenario, or an empty one.

Shared by the Scenario and Advanced JSON pages. Opening replaces the scenario, so it
asks first when there are unsaved edits (plan §7.3).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.samples import SAMPLE_LABELS, load_sample_payload
from frontend.state.scenario_state import new_scenario
from frontend.state.settings import DEFAULT_PLANNER_DEFAULTS, DEFAULT_TIMEZONE
from frontend.state.workspace import Workspace, load_document
from frontend.views.components import (
    AppContext,
    editor_follows_scenario,
    render_backend_error,
    set_flash,
    set_workspace,
)
from frontend.views.saving import SAVED_LIST_KEY

CONFIRM_KEYS = ("confirm_discard_edits", "scenario_confirm_discard")


def discard_allowed(ctx: AppContext, key: str) -> bool:
    """Whether replacing the scenario may go ahead; asks when there are unsaved edits."""
    if not ctx.status.unsaved_edits:
        return True
    st.warning("This scenario has edits that are not saved.")
    return bool(st.checkbox("Discard unsaved edits when opening another scenario", key=key))


def replace_workspace(workspace: Workspace) -> None:
    set_workspace(workspace)
    for key in CONFIRM_KEYS:
        st.session_state.pop(key, None)
    editor_follows_scenario()


def open_sample(letter: str) -> None:
    label = SAMPLE_LABELS[letter]
    replace_workspace(load_document(load_sample_payload(letter), source=f"sample {letter}"))
    set_flash("success", f"Opened the {label}.")
    st.rerun()


def open_empty(ctx: AppContext) -> None:
    timezone = ctx.config.default_timezone if ctx.config is not None else DEFAULT_TIMEZONE
    scenario = new_scenario(
        name="New scenario", timezone=timezone, start_day=ctx.now.astimezone().date()
    )
    scenario["planner_defaults"] = dict(DEFAULT_PLANNER_DEFAULTS)
    replace_workspace(load_document(scenario, source="new empty scenario"))
    set_flash("success", "Started an empty scenario. Add the plant on this page first.")
    st.rerun()


def open_saved(ctx: AppContext, scenario_id: str) -> None:
    try:
        response = ctx.client.load_scenario(scenario_id)
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    document = response.payload.get("payload")
    if not isinstance(document, dict):
        st.error("Saved scenario response did not contain a scenario.")
        return
    loaded_id = str(response.payload.get("scenario_id", scenario_id))
    replace_workspace(
        load_document(document, source=f"saved scenario {loaded_id}", saved_id=loaded_id)
    )
    set_flash("success", f"Opened saved scenario {loaded_id}.{expired_note(response.payload)}")
    st.rerun()


def expired_note(payload: dict[str, Any]) -> str:
    """What to tell the planner when the backend removed coordinates older than 30 days."""
    removed = int(payload.get("expired_coordinates_removed", 0) or 0)
    if not removed:
        return ""
    return (
        f" {removed} location(s) had coordinates older than 30 days; they were removed, as "
        "Google's terms require. Resolve them again on the Locations page."
    )


def saved_scenario_label(summary: dict[str, object]) -> str:
    """``WEEK-26 — Inbound week 26 (7 locations, 12 tasks, 3 plans; saved 2026-11-18)``."""
    name = summary.get("name")
    updated = str(summary.get("updated_at", ""))[:10]
    counts = f"{summary.get('location_count', 0)} locations, {summary.get('task_count', 0)} tasks"
    plans = summary.get("plan_count")
    if isinstance(plans, int) and plans:
        counts += f", {plans} plan{'s' if plans != 1 else ''}"
    return (
        f"{summary.get('scenario_id')}"
        + (f" — {name}" if name else "")
        + f" ({counts}; saved {updated})"
    )


def saved_scenarios(ctx: AppContext) -> list[dict[str, Any]]:
    """The saved-scenario list, fetched once and kept until Refresh or a save."""
    cached = st.session_state.get(SAVED_LIST_KEY)
    if isinstance(cached, list):
        return cached
    if not ctx.connected:
        return []
    try:
        summaries = ctx.client.list_scenarios()
    except BackendClientError as exc:
        render_backend_error(exc)
        return []
    st.session_state[SAVED_LIST_KEY] = summaries
    return summaries
