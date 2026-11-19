"""Saving the current scenario to the backend (shared by Scenario and Advanced JSON)."""

from __future__ import annotations

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.workspace import mark_saved, matrix_is_storable, save_document
from frontend.views.components import (
    AppContext,
    get_workspace,
    render_backend_error,
    set_flash,
    set_workspace,
)

SAVED_LIST_KEY = "saved_scenarios"
"""Session cache of the saved-scenario list; cleared by every save."""


def save_current(ctx: AppContext) -> None:
    """Save under the scenario ID; Google travel times are left out (decision D6)."""
    workspace = get_workspace()
    try:
        response = ctx.client.save_scenario(save_document(workspace))
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    saved_id = response.payload.get("scenario_id", workspace.scenario.get("scenario_id"))
    set_workspace(mark_saved(workspace, source=f"saved scenario {saved_id}"))
    st.session_state.pop(SAVED_LIST_KEY, None)
    matrix = workspace.derived.matrix
    google_matrix = matrix is not None and not matrix_is_storable(matrix)
    note = (
        " Travel times from Google are not saved; calculate them again after opening it."
        if google_matrix or response.payload.get("routing_matrix_dropped")
        else ""
    )
    set_flash("success", f"Saved scenario {saved_id}.{note}")
    st.rerun()
