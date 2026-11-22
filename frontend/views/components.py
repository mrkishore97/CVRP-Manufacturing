"""Shared view helpers: session access, page routing, messages, and backend errors.

Navigation is a small single-script router: the current page lives in session state
and in the ``?page=`` query parameter, so a browser refresh stays on the same page.
``st.navigation`` was not used because Streamlit's ``AppTest`` (1.43.2) returns to the
default page on the rerun after ``st.switch_page``, which would leave multi-page
workflows untestable (plan risk "Navigation change breaks UI testability").
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from frontend.api_client import (
    BackendApiError,
    BackendClient,
    BackendClientError,
    BackendConfig,
    BackendResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
)
from frontend.state.readiness import WorkflowStatus
from frontend.state.results import google_attribution
from frontend.state.scenario_state import ScenarioEditError
from frontend.state.units import hmm_to_seconds
from frontend.state.workspace import Workspace, edit

WORKSPACE_KEY = "workspace"
PAGE_KEY = "current_page"
FLASH_KEY = "flash_message"
KEPT_SUFFIX = "__kept"
EDITOR_KEY = "json_editor_text"
EDITOR_SOURCE_KEY = "json_editor_source"
EDITOR_FILLED_KEY = "json_editor_filled_text"
PERSISTENT_WIDGET_KEYS = (EDITOR_KEY, "json_view_mode")
"""Widgets whose value must survive visiting another page (Streamlit drops it)."""


@dataclass(frozen=True, slots=True)
class AppContext:
    """What every page needs for one script run."""

    client: BackendClient
    connected: bool
    backend_version: str | None
    config: BackendConfig | None
    now: datetime
    status: WorkflowStatus


def get_workspace() -> Workspace:
    workspace = st.session_state[WORKSPACE_KEY]
    if not isinstance(workspace, Workspace):
        raise RuntimeError("Session workspace is missing.")
    return workspace


def set_workspace(workspace: Workspace) -> None:
    st.session_state[WORKSPACE_KEY] = workspace


def commit_edit(
    scenario: Mapping[str, Any],
    *,
    message: str | None = None,
    renamed_locations: Mapping[str, str] | None = None,
) -> None:
    """Make a form edit the current scenario, then rerun so every page shows it."""
    set_workspace(edit(get_workspace(), scenario, renamed_locations=renamed_locations))
    if message:
        set_flash("success", message)
    st.rerun()


def editor_follows_scenario() -> None:
    """Treat the JSON editor as unedited, so it is refilled from the scenario."""
    st.session_state[EDITOR_FILLED_KEY] = st.session_state.get(
        EDITOR_KEY, kept_widget_value(EDITOR_KEY)
    )
    st.session_state[EDITOR_SOURCE_KEY] = None


def remember_widget(key: str) -> None:
    """Keep a copy of a widget's value outside Streamlit's widget state."""
    if key in st.session_state:
        st.session_state[f"{key}{KEPT_SUFFIX}"] = st.session_state[key]


def remember_widgets() -> None:
    """Called first in every run, before navigation can leave the page."""
    for key in PERSISTENT_WIDGET_KEYS:
        remember_widget(key)


def restore_widget(key: str) -> None:
    """Before creating the widget: bring back the value Streamlit dropped."""
    kept = f"{key}{KEPT_SUFFIX}"
    if key not in st.session_state and kept in st.session_state:
        st.session_state[key] = st.session_state[kept]


def kept_widget_value(key: str) -> Any:
    return st.session_state.get(f"{key}{KEPT_SUFFIX}")


def go_to(page_key: str) -> None:
    """Switch page and rerun now."""
    st.session_state[PAGE_KEY] = page_key
    st.query_params["page"] = page_key
    st.rerun()


def next_step_button(page_key: str, label: str) -> None:
    st.divider()
    if st.button(label, key=f"next-{page_key}", type="primary"):
        go_to(page_key)


def set_flash(level: str, message: str) -> None:
    """A message shown once, on the next run (after ``st.rerun``)."""
    st.session_state[FLASH_KEY] = {"level": level, "message": message}


def render_flash() -> None:
    flash = st.session_state.pop(FLASH_KEY, None)
    if not isinstance(flash, dict) or not flash.get("message"):
        return
    show = {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
    }.get(str(flash.get("level")), st.info)
    show(str(flash["message"]))


def row_revision(row: Mapping[str, Any] | None) -> str:
    """A short fingerprint of a row, for edit-form widget keys.

    Keys that change whenever the row changes (from a form, an import, or the JSON
    view) make the form show the row as it is now instead of stale widget state.
    """
    text = json.dumps(row or {}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def optional_hmm(text: str, label: str) -> int | None:
    """Seconds from optional ``h:mm`` text; empty means no limit."""
    if not text.strip():
        return None
    try:
        return hmm_to_seconds(text)
    except ValueError as exc:
        raise ScenarioEditError(f"{label}: {exc}") from None


def table(rows: Sequence[dict[str, Any]], *, columns: Sequence[str] | None = None) -> None:
    frame = pd.DataFrame(list(rows))
    if columns is not None and not frame.empty:
        frame = frame[[column for column in columns if column in frame.columns]]
    st.dataframe(frame, hide_index=True, use_container_width=True)


def render_google_attribution(
    ctx: AppContext, *, addresses: bool = False, travel_times: bool = False
) -> None:
    """Credit Google wherever its addresses or travel times are shown off a Google map."""
    text = google_attribution(
        addresses=addresses,
        travel_times=travel_times,
        google_configured=bool(ctx.config and ctx.config.google_maps_configured),
    )
    if text:
        st.caption(text)


def render_backend_error(error: BackendClientError) -> None:
    if isinstance(error, BackendApiError):
        st.error(f"{error.code}: {error}")
        if error.request_id:
            st.caption(f"Request ID: {error.request_id}")
        if error.details:
            table(
                [
                    {
                        "code": detail.code,
                        "row_number": detail.row_number,
                        "field": detail.field,
                        "task_id": detail.task_id,
                        "message": detail.message,
                    }
                    for detail in error.details
                ]
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
