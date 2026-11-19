"""Fleet: trucks and their shifts (read-only until the fleet forms arrive)."""

from __future__ import annotations

import streamlit as st

from frontend.state.scenario_state import rows
from frontend.state.timeutil import format_local
from frontend.views.components import AppContext, get_workspace, next_step_button, table


def render(ctx: AppContext) -> None:
    del ctx
    st.header("Fleet")
    st.caption("Trucks and shifts are edited in Advanced JSON for now.")
    scenario = get_workspace().scenario
    timezone = str(scenario.get("timezone", "America/Toronto"))
    st.subheader("Trucks")
    table(rows(scenario, "vehicles"))
    st.subheader("Shifts")
    shifts = rows(scenario, "vehicle_shifts")
    table(
        [
            {
                **shift,
                "start (local)": _local(shift.get("start"), timezone),
                "end (local)": _local(shift.get("end"), timezone),
            }
            for shift in shifts
        ]
    )
    next_step_button("tasks", "Next: Tasks")


def _local(value: object, timezone: str) -> str:
    try:
        return format_local(str(value), timezone) if value else "—"
    except (ValueError, KeyError):
        return str(value)
