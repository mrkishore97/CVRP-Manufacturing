"""Session start, the scenario ID in the URL, drafts, and restoring them (plan §11.3).

A browser refresh starts a new Streamlit session with nothing in it. The page URL
keeps ``?scenario=<id>``, so the new session opens that scenario again: the saved copy
if there is one, else the sample with that ID. If the backend kept a draft for it, the
app offers "Restore unsaved changes from …" or "Discard". While the offer is open,
nothing is written over the draft.
"""

from __future__ import annotations

import contextlib
from typing import Any

import streamlit as st

from frontend.api_client import BackendApiError, BackendClient, BackendClientError
from frontend.samples import load_sample_payload, sample_key_for
from frontend.state.drafts import (
    DraftRecord,
    draft_plan_id,
    dropped_matrix,
    plan_draft_sync,
    restore_workspace,
    scenario_key,
)
from frontend.state.results import as_object, local_datetime_text
from frontend.state.settings import DEFAULT_TIMEZONE
from frontend.state.workspace import Workspace, load_document, record_plan
from frontend.views.components import WORKSPACE_KEY, get_workspace, set_flash
from frontend.views.opening import expired_note, replace_workspace

SCENARIO_PARAM = "scenario"
DRAFT_RECORD_KEY = "draft_record"
RESTORE_OFFER_KEY = "restore_offer"
DRAFT_ERROR_KEY = "draft_error"


def ensure_workspace(client: BackendClient, *, connected: bool) -> None:
    """Open the scenario named in the URL on a new session; else the feasible sample."""
    if WORKSPACE_KEY in st.session_state:
        return
    requested = str(st.query_params.get(SCENARIO_PARAM, "") or "").strip()
    workspace: Workspace | None = None
    note = ""
    if requested and connected:
        workspace, note = _open_requested(client, requested)
        try:
            draft = client.get_draft(requested)
        except BackendClientError:
            draft = None
        if draft is not None:
            st.session_state[RESTORE_OFFER_KEY] = draft
    if workspace is None:
        key = sample_key_for(requested) if requested else None
        letter = key or "A"
        workspace = load_document(load_sample_payload(letter), source=f"sample {letter}")
    st.session_state[WORKSPACE_KEY] = workspace
    if note:
        set_flash("info", note.strip())


def _open_requested(client: BackendClient, scenario_id: str) -> tuple[Workspace | None, str]:
    try:
        response = client.load_scenario(scenario_id)
    except BackendClientError:  # not saved (404) or unreadable: fall back to a sample
        return None, ""
    document = response.payload.get("payload")
    if not isinstance(document, dict):
        return None, ""
    workspace = load_document(
        document, source=f"saved scenario {scenario_id}", saved_id=scenario_id
    )
    return workspace, expired_note(response.payload)


def keep_scenario_in_url() -> None:
    """The URL names the open scenario, so a refresh can find it again."""
    key = scenario_key(get_workspace())
    if key and st.query_params.get(SCENARIO_PARAM) != key:
        st.query_params[SCENARIO_PARAM] = key


def sync_draft(client: BackendClient) -> None:
    """Write or remove the draft after a change; nothing while a restore is offered."""
    if RESTORE_OFFER_KEY in st.session_state:
        return
    last = st.session_state.get(DRAFT_RECORD_KEY)
    plan = plan_draft_sync(get_workspace(), last if isinstance(last, DraftRecord) else None)
    try:
        for scenario_id in plan.delete:
            client.delete_draft(scenario_id)
        if plan.put is not None:
            client.put_draft(*plan.put)
    except BackendApiError as exc:
        # A rejected draft (for example over the size limits) is not retried every run.
        st.session_state[DRAFT_ERROR_KEY] = f"{exc.code}: {exc}"
        st.session_state[DRAFT_RECORD_KEY] = plan.record
        return
    except BackendClientError:
        return  # the backend is unreachable; the next run tries again
    st.session_state.pop(DRAFT_ERROR_KEY, None)
    st.session_state[DRAFT_RECORD_KEY] = plan.record


def render_restore_offer(client: BackendClient) -> None:
    """The banner offering to restore a kept draft, until the planner answers."""
    draft = st.session_state.get(RESTORE_OFFER_KEY)
    if not isinstance(draft, dict):
        return
    payload = as_object(draft.get("payload"))
    scenario_id = str(draft.get("scenario_id") or payload.get("scenario_id") or "")
    name = payload.get("name")
    timezone = str(payload.get("timezone") or DEFAULT_TIMEZONE)
    when = local_datetime_text(draft.get("updated_at"), timezone)
    label = f"{scenario_id} ({name})" if name else scenario_id
    with st.container(border=True):
        st.warning(f"Unsaved changes to {label} from {when} were kept when the page closed.")
        st.caption("Restoring replaces what is open now. Discarding deletes the kept changes.")
        col_restore, col_discard = st.columns(2)
        if col_restore.button("Restore unsaved changes", type="primary", key="draft-restore"):
            _restore(client, draft)
        if col_discard.button("Discard them", key="draft-discard"):
            _discard(client, scenario_id)


def _restore(client: BackendClient, draft: dict[str, Any]) -> None:
    try:
        workspace = restore_workspace(draft)
    except ValueError as exc:
        st.error(str(exc))
        return
    plan_id = draft_plan_id(draft)
    if plan_id and workspace.derived.matrix is not None:
        try:
            plan = client.get_plan(plan_id).raw.get("plan")
        except BackendClientError:
            plan = None
        if isinstance(plan, dict):
            workspace = record_plan(workspace, plan=plan, validation=None, request_id=None)
    replace_workspace(workspace)
    st.session_state.pop(RESTORE_OFFER_KEY, None)
    st.session_state.pop(DRAFT_RECORD_KEY, None)
    notes = ["Restored the unsaved changes."]
    if dropped_matrix(draft) is not None:
        notes.append(
            "Travel times from Google are not kept, so calculate them again on the Travel "
            "times page."
        )
    if int(draft.get("expired_coordinates_removed", 0) or 0):
        notes.append(expired_note(draft).strip())
    set_flash("success", " ".join(notes))
    st.rerun()


def _discard(client: BackendClient, scenario_id: str) -> None:
    # The offer goes away either way; a later save or edit replaces the draft.
    with contextlib.suppress(BackendClientError):
        client.delete_draft(scenario_id)
    st.session_state.pop(RESTORE_OFFER_KEY, None)
    set_flash("info", "Discarded the kept changes.")
    st.rerun()
