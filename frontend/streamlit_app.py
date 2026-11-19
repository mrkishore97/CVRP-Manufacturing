"""Streamlit shell for manufacturing PO routing: client, router, and status sidebar.

The pages live in ``frontend/views`` and every rule about the scenario lives in
``frontend/state``. This script only wires them together for one run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from frontend.api_client import BackendClient, BackendClientError, BackendConfig
from frontend.samples import load_sample_payload
from frontend.state.readiness import workflow_status
from frontend.state.workspace import load_document
from frontend.views.components import (
    WORKSPACE_KEY,
    AppContext,
    get_workspace,
    remember_widgets,
    render_backend_error,
    render_flash,
)
from frontend.views.navigation import current_page, render_navigation
from frontend.views.status import render_status
from frontend.views.validation import run_validation

CONFIG_KEY = "backend_config"

__all__ = ["load_sample_payload", "render_app"]


def _ensure_workspace() -> None:
    if WORKSPACE_KEY not in st.session_state:
        st.session_state[WORKSPACE_KEY] = load_document(load_sample_payload("A"), source="sample A")


def _backend_config(client: BackendClient) -> BackendConfig | None:
    cached = st.session_state.get(CONFIG_KEY)
    if isinstance(cached, BackendConfig):
        return cached
    try:
        config = client.get_config()
    except BackendClientError:
        return None
    st.session_state[CONFIG_KEY] = config
    return config


def render_app() -> None:
    """Render one run of the planning app."""
    st.set_page_config(
        page_title="Manufacturing PO Route Optimizer",
        page_icon="🚚",
        layout="wide",
    )
    remember_widgets()
    _ensure_workspace()
    client = BackendClient.from_environment()
    health_error: BackendClientError | None = None
    version: str | None = None
    try:
        version = client.get_health().version
    except BackendClientError as exc:
        health_error = exc
    connected = health_error is None
    config = _backend_config(client) if connected else None
    if connected:
        run_validation(client)

    now = datetime.now(UTC)
    context = AppContext(
        client=client,
        connected=connected,
        backend_version=version,
        config=config,
        now=now,
        status=workflow_status(get_workspace(), now=now),
    )
    page = current_page()
    with st.sidebar:
        st.markdown("### 🚚 Route Optimizer")
        render_navigation(page)
        st.divider()
        render_status(context)

    st.title("Manufacturing PO Route Optimizer")
    st.caption("Deadline-aware pickup, drop, and pickup-drop planning for ready POs")
    if health_error is not None:
        render_backend_error(health_error)
        st.info("You can still view and edit the scenario. Checking and planning need the API.")
    render_flash()
    page.render(context)


if __name__ == "__main__":
    render_app()
