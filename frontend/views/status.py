"""The status sidebar: backend, scenario, validation, locations, travel times, plan."""

from __future__ import annotations

import streamlit as st

from frontend.state.drafts import DraftRecord
from frontend.state.readiness import USABLE_READINESS
from frontend.views.components import AppContext, get_workspace
from frontend.views.session import DRAFT_ERROR_KEY, DRAFT_RECORD_KEY


def render_status(ctx: AppContext) -> None:
    workspace = get_workspace()
    scenario = workspace.scenario
    status = ctx.status
    st.subheader("Status")

    if ctx.connected:
        google = ""
        if ctx.config is not None:
            google = (
                " · Google Maps configured"
                if ctx.config.google_maps_configured
                else " · Google Maps not configured"
            )
        st.caption(f"Backend {ctx.backend_version} connected{google}")
    else:
        st.caption("⚠️ Backend unavailable")

    name = scenario.get("name")
    st.markdown(f"**{scenario.get('scenario_id', 'Scenario')}**" + (f" — {name}" if name else ""))
    if status.unsaved_edits:
        kept = isinstance(st.session_state.get(DRAFT_RECORD_KEY), DraftRecord)
        st.caption("✏️ Unsaved edits" + (" · kept if the page reloads" if kept else ""))
    else:
        st.caption("No unsaved edits")
    draft_error = st.session_state.get(DRAFT_ERROR_KEY)
    if draft_error:
        st.caption(f"⚠️ Unsaved edits could not be kept for a reload: {draft_error}")

    if status.validation_current:
        if status.validation_valid:
            warnings = f", {status.warning_count} warning(s)" if status.warning_count else ""
            st.markdown(f"✅ Valid{warnings}")
        else:
            st.markdown(f"❌ {status.error_count} error(s)")
    elif workspace.derived.validation_error:
        st.markdown("⚠️ Could not check")
    else:
        st.markdown("⏳ Not checked")

    total = len(status.readiness)
    usable = sum(value in USABLE_READINESS for value in status.readiness.values())
    attention = total - usable
    st.markdown(
        f"📍 {usable} of {total} locations ready"
        + (f" · {attention} need attention" if attention else "")
    )

    if status.matrix_current:
        st.markdown("✅ Travel times current")
    elif workspace.derived.matrix is not None:
        st.markdown("⚠️ Travel times stale")
    else:
        st.markdown("⬜ No travel times")

    plan = workspace.derived.plan
    if status.plan_current and plan is not None:
        st.markdown(f"✅ Plan {plan.get('status', '')}")
    elif status.stale_plan_hidden:
        st.markdown("⚠️ Plan stale (hidden)")
    else:
        st.markdown("⬜ No plan")
