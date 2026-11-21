"""Shared pieces of the spreadsheet imports: template downloads.

The template's columns come from the backend import contract, fetched once per session
(it is free: no Google call). Without a backend there is nothing to download.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.import_preview import template_csv_bytes, template_xlsx_bytes
from frontend.views.components import AppContext

TEMPLATE_KEY = "import_template_{kind}"


def import_template(ctx: AppContext, kind: str) -> dict[str, Any] | None:
    key = TEMPLATE_KEY.format(kind=kind)
    cached = st.session_state.get(key)
    if isinstance(cached, dict):
        return cached
    if not ctx.connected:
        return None
    try:
        template = ctx.client.import_template(kind).payload
    except BackendClientError:
        return None
    st.session_state[key] = template
    return template


def render_template_downloads(ctx: AppContext, kind: str, label: str) -> None:
    template = import_template(ctx, kind)
    if template is None:
        st.caption("Templates are available while the backend is connected.")
        return
    col_csv, col_xlsx = st.columns(2)
    col_csv.download_button(
        f"Download {label} template (CSV)",
        data=template_csv_bytes(template),
        file_name=f"{kind}_template.csv",
        mime="text/csv",
        key=f"template-{kind}-csv",
    )
    col_xlsx.download_button(
        f"Download {label} template (Excel)",
        data=template_xlsx_bytes(template),
        file_name=f"{kind}_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"template-{kind}-xlsx",
    )
