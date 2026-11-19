"""Tasks: current PO task lines and a spreadsheet import preview."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from frontend.import_preview import ImportPreview, preview_task_import
from frontend.state.scenario_state import rows
from frontend.views.components import AppContext, get_workspace, next_step_button, table


def render(ctx: AppContext) -> None:
    del ctx
    st.header("Tasks")
    st.caption("PO tasks are edited in Advanced JSON for now.")
    table(rows(get_workspace().scenario, "tasks"))

    st.subheader("Import preview")
    uploaded_file = st.file_uploader("Preview task CSV/XLSX", type=("csv", "xlsx"))
    if uploaded_file is None:
        st.caption("Preview checks columns and blank required cells before backend validation.")
    else:
        _render_preview(uploaded_file)
    next_step_button("review", "Next: Review")


def _render_preview(uploaded_file: Any) -> None:
    try:
        preview = _preview_uploaded_tasks(uploaded_file)
    except Exception as exc:  # any unreadable upload is reported, not raised
        st.error(f"Could not read the uploaded file: {exc}")
        return
    if preview.has_blocking_errors:
        st.error("Import preview found errors to fix before these rows can be used.")
    elif preview.issues:
        st.warning("Import preview found warnings, but no blocking row errors.")
    else:
        st.success("Import preview did not find column or required-cell issues.")
    table(preview.rows)
    if preview.issues:
        table(preview.issue_rows())


def _preview_uploaded_tasks(uploaded_file: Any) -> ImportPreview:
    if str(uploaded_file.name).casefold().endswith(".csv"):
        frame = pd.read_csv(uploaded_file)
    else:
        frame = pd.read_excel(uploaded_file)
    return preview_task_import(frame)
