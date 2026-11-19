"""Advanced JSON: view, edit, apply, upload, download, save, and load the scenario.

The editor shows the same canonical scenario the other pages use; there is no second
copy. Applying follows plan §7.3: parse (syntax errors change nothing), validate with
the backend, and refuse JSON with errors while the current scenario is valid.
Replacing the scenario with another one (sample, saved scenario, uploaded file) asks
first when there are unsaved edits.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.samples import SAMPLE_LABELS, load_sample_payload
from frontend.state.fingerprints import saved_fingerprint, stable_fingerprint
from frontend.state.json_io import ExportMode, parse_document, scenario_to_json
from frontend.state.scenario_state import new_scenario, rows
from frontend.state.workspace import (
    Workspace,
    apply_document,
    load_document,
    mark_saved,
    record_validation,
    save_document,
    validation_issue_rows,
    validation_payload,
    validation_payload_fingerprint,
)
from frontend.views.components import (
    AppContext,
    get_workspace,
    kept_widget_value,
    next_step_button,
    remember_widget,
    render_backend_error,
    restore_widget,
    set_flash,
    set_workspace,
    table,
)

EDITOR_KEY = "json_editor_text"
EDITOR_SOURCE_KEY = "json_editor_source"
EDITOR_FILLED_KEY = "json_editor_filled_text"
MODE_KEY = "json_view_mode"
CONFIRM_DISCARD_KEY = "confirm_discard_edits"
MODE_LABELS = {
    ExportMode.CLEAN: "Clean — planner inputs",
    ExportMode.COMPLETE: "Complete — with derived data",
}


def render(ctx: AppContext) -> None:
    st.header("Advanced JSON")
    st.caption(
        "The whole scenario as JSON. Edit it and press Apply JSON; nothing changes until "
        "the JSON is valid. The clean view hides coordinates and other data found by "
        "address resolution; the complete view shows them."
    )
    workspace = get_workspace()
    _render_summary(workspace)
    st.divider()
    _render_replace_actions(ctx, workspace)
    st.divider()
    _render_editor(ctx, workspace)
    st.divider()
    _render_downloads_and_save(ctx, workspace)
    next_step_button("review", "Next: Review")


def _render_summary(workspace: Workspace) -> None:
    scenario = workspace.scenario
    horizon = scenario.get("planning_horizon") or {}
    col_1, col_2, col_3 = st.columns(3)
    col_1.metric("Scenario", str(scenario.get("scenario_id", "not set")))
    col_2.metric("Timezone", str(scenario.get("timezone", "not set")))
    col_3.metric(
        "Period start",
        str(horizon.get("start", "not set")) if isinstance(horizon, dict) else "not set",
    )
    counts = {
        label: len(rows(scenario, collection))
        for label, collection in (
            ("Locations", "locations"),
            ("Trucks", "vehicles"),
            ("Shifts", "vehicle_shifts"),
            ("Tasks", "tasks"),
        )
    }
    st.caption(" · ".join(f"{label}: {count}" for label, count in counts.items()))
    if workspace.derived.loaded_from:
        st.caption(f"Loaded from: {workspace.derived.loaded_from}")


def _render_replace_actions(ctx: AppContext, workspace: Workspace) -> None:
    st.subheader("Open a scenario")
    allowed = True
    if ctx.status.unsaved_edits:
        st.warning("This scenario has edits that are not saved.")
        allowed = st.checkbox(
            "Discard unsaved edits when opening another scenario", key=CONFIRM_DISCARD_KEY
        )
    columns = st.columns(4)
    for column, (letter, label) in zip(columns, SAMPLE_LABELS.items(), strict=False):
        if column.button(f"Load {label}", disabled=not allowed) and allowed:
            _replace(load_document(load_sample_payload(letter), source=f"sample {letter}"))
            set_flash("success", f"Loaded the {label}.")
            st.rerun()
    if columns[3].button("Start empty scenario", disabled=not allowed) and allowed:
        _replace(load_document(new_scenario(), source="new empty scenario"))
        set_flash("success", "Started an empty scenario.")
        st.rerun()

    col_load, col_upload = st.columns(2)
    scenario_id = col_load.text_input("Scenario ID to load", key="load_scenario_id")
    can_load = allowed and bool(scenario_id.strip())
    if col_load.button("Load saved scenario", disabled=not can_load) and can_load:
        _load_saved(ctx, scenario_id.strip())
    uploaded = col_upload.file_uploader("Upload scenario JSON", type=("json",))
    can_open = allowed and uploaded is not None
    if col_upload.button("Open uploaded file", disabled=not can_open) and can_open:
        text = uploaded.getvalue().decode("utf-8-sig") if uploaded is not None else ""
        _apply_text(ctx, workspace, text, mode=ExportMode.COMPLETE, replace_from="uploaded file")


def _load_saved(ctx: AppContext, scenario_id: str) -> None:
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
    _replace(load_document(document, source=f"saved scenario {loaded_id}"))
    set_flash("success", f"Loaded scenario {loaded_id}.")
    st.rerun()


def _replace(workspace: Workspace) -> None:
    set_workspace(workspace)
    st.session_state.pop(CONFIRM_DISCARD_KEY, None)
    _editor_follows_scenario()


def _render_editor(ctx: AppContext, workspace: Workspace) -> None:
    st.subheader("Scenario JSON")
    restore_widget(MODE_KEY)
    mode = ExportMode(
        st.radio(
            "View",
            options=[mode.value for mode in ExportMode],
            format_func=lambda value: MODE_LABELS[ExportMode(value)],
            key=MODE_KEY,
            horizontal=True,
        )
    )
    remember_widget(MODE_KEY)
    expected = scenario_to_json(
        workspace.scenario,
        mode=mode,
        matrix=workspace.derived.matrix if mode is ExportMode.COMPLETE else None,
    )
    source = stable_fingerprint([saved_fingerprint(workspace.scenario), mode.value, expected])
    restore_widget(EDITOR_KEY)
    unapplied = st.session_state.get(EDITOR_KEY) not in (
        None,
        st.session_state.get(EDITOR_FILLED_KEY),
    )
    if EDITOR_KEY not in st.session_state:
        _fill_editor(expected, source)
    elif st.session_state.get(EDITOR_SOURCE_KEY) != source:
        if unapplied:
            st.warning(
                "The editor has changes that are not applied, and the scenario or view "
                "changed since. Apply them, or press Reset editor to discard them."
            )
        else:
            _fill_editor(expected, source)
    st.text_area("Scenario JSON", key=EDITOR_KEY, height=420, label_visibility="collapsed")
    remember_widget(EDITOR_KEY)
    col_apply, col_reset = st.columns(2)
    if col_apply.button("Apply JSON", type="primary"):
        _apply_text(ctx, workspace, str(st.session_state.get(EDITOR_KEY, "")), mode=mode)
    if col_reset.button("Reset editor"):
        _editor_follows_scenario()
        st.rerun()


def _fill_editor(text: str, source: str) -> None:
    """Only before the text area is created in a run (Streamlit forbids it after)."""
    st.session_state[EDITOR_KEY] = text
    st.session_state[EDITOR_FILLED_KEY] = text
    st.session_state[EDITOR_SOURCE_KEY] = source


def _editor_follows_scenario() -> None:
    """Treat the editor as unedited, so the next run refills it from the scenario."""
    st.session_state[EDITOR_FILLED_KEY] = st.session_state.get(
        EDITOR_KEY, kept_widget_value(EDITOR_KEY)
    )
    st.session_state[EDITOR_SOURCE_KEY] = None


def _apply_text(
    ctx: AppContext,
    workspace: Workspace,
    text: str,
    *,
    mode: ExportMode,
    replace_from: str | None = None,
) -> None:
    """Parse, validate, and apply; invalid JSON never replaces a valid scenario."""
    parsed = parse_document(text)
    if parsed.document is None:
        st.error(f"Nothing was applied. {parsed.error}")
        return
    if replace_from is not None:
        candidate = load_document(parsed.document, source=replace_from)
    else:
        candidate = apply_document(
            workspace, parsed.document, carry_derived=mode is ExportMode.CLEAN
        )
    current_is_valid = ctx.status.validation_valid
    validation = _validate(ctx, candidate)
    if validation is None and current_is_valid:
        st.error(
            "Nothing was applied: the backend is needed to check the JSON before it "
            "replaces a valid scenario."
        )
        return
    if validation is not None and not validation.get("valid") and current_is_valid:
        st.error(
            "Nothing was applied: the JSON has validation errors, and the current "
            "scenario is valid. Fix the errors below and apply again."
        )
        table(validation_issue_rows(validation))
        return
    if validation is not None:
        candidate = record_validation(
            candidate,
            payload_fingerprint=validation_payload_fingerprint(candidate),
            validation=validation,
            request_id=None,
        )
    if replace_from is not None:
        _replace(candidate)
        set_flash("success", f"Opened the {replace_from}.")
    else:
        set_workspace(candidate)
        _editor_follows_scenario()
        set_flash("success", "JSON applied.")
    st.rerun()


def _validate(ctx: AppContext, candidate: Workspace) -> dict[str, Any] | None:
    if not ctx.connected:
        return None
    try:
        response = ctx.client.validate_plan(validation_payload(candidate))
    except BackendClientError as exc:
        render_backend_error(exc)
        return None
    validation = response.raw.get("validation")
    return validation if isinstance(validation, dict) else None


def _render_downloads_and_save(ctx: AppContext, workspace: Workspace) -> None:
    st.subheader("Download and save")
    scenario_id = str(workspace.scenario.get("scenario_id", "scenario"))
    safe_id = "".join(c if c.isalnum() or c in "-_" else "-" for c in scenario_id)
    col_clean, col_complete, col_save = st.columns(3)
    col_clean.download_button(
        "Download clean JSON",
        data=scenario_to_json(workspace.scenario, mode=ExportMode.CLEAN),
        file_name=f"{safe_id}_clean.json",
        mime="application/json",
        help="Planner inputs only. Safe to share; addresses are resolved again on import.",
    )
    col_complete.download_button(
        "Download complete JSON",
        data=scenario_to_json(
            workspace.scenario, mode=ExportMode.COMPLETE, matrix=workspace.derived.matrix
        ),
        file_name=f"{safe_id}_complete.json",
        mime="application/json",
        help="Also includes resolved coordinates and the active travel times.",
    )
    if col_save.button("Save scenario"):
        try:
            response = ctx.client.save_scenario(save_document(workspace))
        except BackendClientError as exc:
            render_backend_error(exc)
        else:
            saved_id = response.payload.get("scenario_id", scenario_id)
            set_workspace(mark_saved(workspace, source=f"saved scenario {saved_id}"))
            set_flash("success", f"Saved scenario {saved_id}.")
            st.rerun()
    st.caption("API keys stay in backend configuration; this app never asks for them.")
