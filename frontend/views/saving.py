"""Saving scenarios to the backend (shared by Scenario and Advanced JSON) (plan §11.3).

- **Save** replaces the saved scenario this session opened or saved. Saving under
  another ID that is already saved asks first (the overwrite guard).
- **Save as** saves under a new name and ID and never overwrites.
- **Duplicate** copies a saved scenario to a new ID without opening it.
- **Delete** removes a saved scenario with its plans and draft, after a confirmation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

import streamlit as st

from frontend.api_client import BackendApiError, BackendClientError
from frontend.state.drafts import scenario_key
from frontend.state.ids import suggest_scenario_id
from frontend.state.workspace import (
    edit,
    mark_saved,
    mark_unsaved,
    matrix_is_storable,
    save_document,
    save_replaces_own_copy,
)
from frontend.views.components import (
    AppContext,
    get_workspace,
    render_backend_error,
    set_flash,
    set_workspace,
)

SAVED_LIST_KEY = "saved_scenarios"
"""Session cache of the saved-scenario list; cleared by every save."""
OVERWRITE_KEY = "overwrite_pending"
"""The scenario ID whose saved copy Save would replace, awaiting the planner's answer."""
SCENARIO_EXISTS = "SCENARIO_EXISTS"


def _google_note(workspace_matrix: Mapping[str, Any] | None, dropped: Any) -> str:
    google_matrix = workspace_matrix is not None and not matrix_is_storable(workspace_matrix)
    if google_matrix or dropped:
        return " Travel times from Google are not saved; calculate them again after opening it."
    return ""


def save_current(ctx: AppContext, *, overwrite_confirmed: bool = False) -> None:
    """Save under the scenario ID; Google travel times are left out (decision D6).

    Replacing a saved scenario other than the one this session opened or saved needs
    ``overwrite_confirmed``; without it the planner is asked first.
    """
    workspace = get_workspace()
    scenario_id = scenario_key(workspace)
    overwrite = overwrite_confirmed or save_replaces_own_copy(workspace)
    try:
        response = ctx.client.save_scenario(save_document(workspace), overwrite=overwrite)
    except BackendApiError as exc:
        if exc.status_code == 409 and exc.code == SCENARIO_EXISTS:
            st.session_state[OVERWRITE_KEY] = scenario_id
            st.rerun()
        render_backend_error(exc)
        return
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    st.session_state.pop(OVERWRITE_KEY, None)
    saved_id = str(response.payload.get("scenario_id", scenario_id))
    set_workspace(mark_saved(workspace, source=f"saved scenario {saved_id}", saved_id=saved_id))
    st.session_state.pop(SAVED_LIST_KEY, None)
    note = _google_note(workspace.derived.matrix, response.payload.get("routing_matrix_dropped"))
    set_flash("success", f"Saved scenario {saved_id}.{note}")
    st.rerun()


def render_overwrite_question(ctx: AppContext, *, key_prefix: str) -> None:
    """Ask before Save replaces a different saved scenario with the same ID."""
    pending = st.session_state.get(OVERWRITE_KEY)
    if not pending:
        return
    if pending != scenario_key(get_workspace()):
        st.session_state.pop(OVERWRITE_KEY, None)
        return
    st.warning(
        f"Another saved scenario already uses the ID {pending}. Saving would replace it. "
        "Replace it, or keep it and use Save as to save under a new ID."
    )
    col_replace, col_keep = st.columns(2)
    if col_replace.button(f"Replace saved {pending}", key=f"{key_prefix}-overwrite-confirm"):
        save_current(ctx, overwrite_confirmed=True)
    if col_keep.button("Keep the saved one", key=f"{key_prefix}-overwrite-cancel"):
        st.session_state.pop(OVERWRITE_KEY, None)
        st.rerun()


def unique_scenario_id(wanted: str, taken: Iterable[str]) -> str:
    """``wanted``, or ``wanted-2``, ``wanted-3``… when that ID is taken."""
    used = {value.casefold() for value in taken}
    base = wanted.strip() or "SCENARIO"
    if base.casefold() not in used:
        return base
    counter = 2
    while True:
        suffix = f"-{counter}"
        candidate = f"{base[: 120 - len(suffix)]}{suffix}"
        if candidate.casefold() not in used:
            return candidate
        counter += 1


def suggested_copy(name: str, scenario_id: str, taken: Iterable[str]) -> tuple[str, str]:
    """A name and a free ID for a copy: ``Copy of …`` and the name's slug."""
    copy_name = f"Copy of {name}".strip() if name.strip() else f"Copy of {scenario_id}"
    return copy_name, unique_scenario_id(suggest_scenario_id(copy_name), taken)


def save_as(ctx: AppContext, *, name: str, scenario_id: str) -> None:
    """Save the open scenario under a new name and ID, never overwriting; continue in it."""
    workspace = get_workspace()
    new_id = scenario_id.strip()
    if not new_id:
        st.error("Enter an ID for the copy.")
        return
    scenario = deepcopy(workspace.scenario)
    scenario["scenario_id"] = new_id
    if name.strip():
        scenario["name"] = " ".join(name.split())
    renamed = edit(workspace, scenario)
    try:
        response = ctx.client.save_scenario(save_document(renamed), overwrite=False)
    except BackendApiError as exc:
        if exc.status_code == 409 and exc.code == SCENARIO_EXISTS:
            st.error(f"A saved scenario with ID {new_id} already exists. Choose another ID.")
            return
        render_backend_error(exc)
        return
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    set_workspace(mark_saved(renamed, source=f"saved scenario {new_id}", saved_id=new_id))
    st.session_state.pop(SAVED_LIST_KEY, None)
    st.session_state.pop(OVERWRITE_KEY, None)
    note = _google_note(renamed.derived.matrix, response.payload.get("routing_matrix_dropped"))
    set_flash("success", f"Saved as {new_id}. You are now working on {new_id}.{note}")
    st.rerun()


def duplicate_saved(ctx: AppContext, source_id: str, *, name: str, new_id: str) -> None:
    """Copy a saved scenario to a new ID without opening it; never overwrites."""
    try:
        loaded = ctx.client.load_scenario(source_id)
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    document = loaded.payload.get("payload")
    if not isinstance(document, dict):
        st.error("The saved scenario could not be read.")
        return
    copy = deepcopy(document)
    copy["scenario_id"] = new_id.strip()
    if name.strip():
        copy["name"] = " ".join(name.split())
    try:
        ctx.client.save_scenario(copy, overwrite=False)
    except BackendApiError as exc:
        if exc.status_code == 409 and exc.code == SCENARIO_EXISTS:
            st.error(f"A saved scenario with ID {new_id} already exists. Choose another ID.")
            return
        render_backend_error(exc)
        return
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    st.session_state.pop(SAVED_LIST_KEY, None)
    set_flash("success", f"Copied {source_id} to {new_id.strip()}. Open it from the list.")
    st.rerun()


def delete_saved(ctx: AppContext, scenario_id: str) -> None:
    """Delete a saved scenario with its plans and draft; the open scenario stays open."""
    try:
        response = ctx.client.delete_scenario(scenario_id)
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    workspace = get_workspace()
    note = ""
    if workspace.derived.saved_scenario_id == scenario_id:
        set_workspace(mark_unsaved(workspace))
        note = " The scenario is still open here, unsaved; save it to keep it."
    st.session_state.pop(SAVED_LIST_KEY, None)
    plans = int(response.payload.get("plans_removed", 0) or 0)
    set_flash(
        "success",
        f"Deleted saved scenario {scenario_id} and {plans} stored plan(s).{note}",
    )
    st.rerun()
