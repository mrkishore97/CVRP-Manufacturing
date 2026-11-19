"""Scenario: name, timezone, planning period, plant, defaults; open, save, start new.

Form fields have no widget keys on purpose: Streamlit then identifies each field by its
label and default value, so the form shows the current scenario again whenever the
scenario changes on another page or through JSON.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import streamlit as st

from frontend.samples import SAMPLE_LABELS
from frontend.state.ids import suggest_scenario_id
from frontend.state.locations import ADDRESS_HINT, READINESS_LABELS
from frontend.state.readiness import LocationReadiness
from frontend.state.scenario_state import ScenarioEditError, rows
from frontend.state.settings import (
    DEFAULT_TIMEZONE,
    choose_plant,
    fit_period,
    fitted_period,
    period_bounds,
    planner_defaults,
    plant_location,
    set_identity,
    set_period,
    set_planner_defaults,
    set_plant,
    set_timezone,
    timezone_choices,
)
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    go_to,
    next_step_button,
)
from frontend.views.opening import (
    discard_allowed,
    open_empty,
    open_sample,
    open_saved,
    saved_scenario_label,
    saved_scenarios,
)
from frontend.views.saving import SAVED_LIST_KEY, save_current

CONFIRM_DISCARD_KEY = "scenario_confirm_discard"


def render(ctx: AppContext) -> None:
    st.header("Scenario")
    st.caption(
        "Name the scenario, set the plant's timezone and planning period, and enter the "
        "plant's address. Then add suppliers and customers on the Locations page."
    )
    scenario = get_workspace().scenario
    _render_details(scenario)
    st.divider()
    _render_plant(ctx, scenario)
    st.divider()
    _render_defaults(scenario)
    st.divider()
    _render_open_and_save(ctx)
    next_step_button("locations", "Next: Locations")


def _render_details(scenario: dict[str, Any]) -> None:
    st.subheader("Details")
    current_name = str(scenario.get("name") or "")
    current_id = str(scenario.get("scenario_id") or "")
    current_zone = str(scenario.get("timezone") or DEFAULT_TIMEZONE)
    zones = timezone_choices(current_zone)
    bounds = period_bounds(scenario)
    start, end = bounds if bounds is not None else _default_period()
    with st.form("scenario_details"):
        name = st.text_input("Scenario name", value=current_name)
        timezone = st.selectbox(
            "Plant timezone",
            options=zones,
            index=zones.index(current_zone),
            help="Every date and time in this scenario is in this timezone.",
        )
        st.markdown("**Planning period** (plant-local time)")
        col_1, col_2, col_3, col_4 = st.columns(4)
        start_day = col_1.date_input("Start date", value=start.date())
        start_time = col_2.time_input(
            "Start time", value=start.time().replace(tzinfo=None), step=900
        )
        end_day = col_3.date_input("End date", value=end.date())
        end_time = col_4.time_input("End time", value=end.time().replace(tzinfo=None), step=900)
        with st.expander("Advanced: scenario ID"):
            scenario_id = st.text_input(
                "Scenario ID",
                value=current_id,
                help="The scenario is saved under this ID. It is suggested from the name.",
            )
        submitted = st.form_submit_button("Save details", type="primary")
    if submitted:
        chosen_id = scenario_id.strip()
        if chosen_id == current_id and _id_follows_name(current_id, current_name):
            chosen_id = suggest_scenario_id(name) if name.strip() else current_id
        try:
            updated = set_identity(scenario, name=name, scenario_id=chosen_id)
            updated = set_timezone(updated, str(timezone))
            updated = set_period(
                updated,
                start_day=_as_date(start_day),
                start_time=_as_time(start_time),
                end_day=_as_date(end_day),
                end_time=_as_time(end_time),
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
        else:
            commit_edit(updated, message="Scenario details saved.")

    fitted = fitted_period(scenario)
    col_fit, col_note = st.columns([1, 3])
    fit = col_fit.button(
        "Fit to shifts and tasks",
        disabled=fitted is None,
        help="Sets the period to whole days covering every shift and task window.",
    )
    if fitted is not None:
        col_note.caption(f"Fitting would set {_period_text(fitted)}.")
    if fit and fitted is not None:
        commit_edit(fit_period(scenario), message="Planning period fitted to shifts and tasks.")


def _render_plant(ctx: AppContext, scenario: dict[str, Any]) -> None:
    st.subheader("Plant")
    plant = plant_location(scenario)
    if plant is None:
        st.info("Enter the plant's name and address. Trucks start and end their shifts here.")
    else:
        state = ctx.status.readiness.get(
            str(plant.get("location_id")), LocationReadiness.NOT_RESOLVED
        )
        matched = plant.get("formatted_address")
        st.markdown(
            f"Address status: **{READINESS_LABELS[state]}**"
            + (f" — matched “{matched}”" if matched else "")
        )
        if state not in (LocationReadiness.READY, LocationReadiness.SUPPLIED) and st.button(
            "Resolve on the Locations page", key="plant-go-locations"
        ):
            go_to("locations")
    with st.form("scenario_plant"):
        name = st.text_input("Plant name", value=str((plant or {}).get("name") or ""))
        address = st.text_input(
            "Plant address", value=str((plant or {}).get("address") or ""), help=ADDRESS_HINT
        )
        submitted = st.form_submit_button("Save plant")
    if submitted:
        try:
            updated = set_plant(scenario, name=name, address=address)
        except ScenarioEditError as exc:
            st.error(str(exc))
        else:
            commit_edit(updated, message="Plant saved. Resolve its address on the Locations page.")

    others = [
        location
        for location in rows(scenario, "locations")
        if location.get("location_id") != scenario.get("plant_location_id", "PLANT")
    ]
    if others:
        with st.expander("Advanced: use another location as the plant"):
            labels = {
                str(location["location_id"]): f"{location.get('name')} ({location['location_id']})"
                for location in others
                if location.get("location_id")
            }
            choice = st.selectbox(
                "Location", options=list(labels), format_func=lambda key: labels[key]
            )
            if st.button("Make this the plant", key="choose-plant") and choice:
                commit_edit(
                    choose_plant(scenario, str(choice)),
                    message=f"{labels[str(choice)]} is now the plant.",
                )


def _render_defaults(scenario: dict[str, Any]) -> None:
    st.subheader("Defaults for new tasks")
    defaults = planner_defaults(scenario)
    with st.form("scenario_defaults"):
        col_1, col_2, col_3 = st.columns(3)
        pickup = col_1.number_input(
            "Pickup service minutes",
            min_value=0,
            max_value=1_440,
            step=5,
            value=int(defaults["pickup_service_minutes"]),
        )
        delivery = col_2.number_input(
            "Delivery service minutes",
            min_value=0,
            max_value=1_440,
            step=5,
            value=int(defaults["delivery_service_minutes"]),
        )
        unit = col_3.text_input(
            "Capacity unit label",
            value=str(defaults["capacity_unit"]),
            help="Shown beside quantities and capacities, such as pallets or kg.",
        )
        submitted = st.form_submit_button("Save defaults")
    if submitted:
        try:
            updated = set_planner_defaults(
                scenario,
                pickup_service_minutes=int(pickup),
                delivery_service_minutes=int(delivery),
                capacity_unit=unit,
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
        else:
            commit_edit(updated, message="Defaults saved.")


def _render_open_and_save(ctx: AppContext) -> None:
    st.subheader("Open, save, or start over")
    workspace = get_workspace()
    if workspace.derived.loaded_from:
        st.caption(f"Opened from: {workspace.derived.loaded_from}")
    col_save, col_status = st.columns([1, 3])
    if col_save.button("Save scenario", type="primary", disabled=not ctx.connected) and (
        ctx.connected
    ):
        save_current(ctx)
    col_status.caption("Unsaved edits." if ctx.status.unsaved_edits else "No unsaved edits.")

    allowed = discard_allowed(ctx, CONFIRM_DISCARD_KEY)
    col_saved, col_sample = st.columns(2)
    with col_saved:
        summaries = saved_scenarios(ctx)
        if summaries:
            by_id = {str(summary.get("scenario_id")): summary for summary in summaries}
            chosen = st.selectbox(
                "Saved scenario",
                options=list(by_id),
                format_func=lambda key: saved_scenario_label(by_id[key]),
            )
            if st.button("Open saved scenario", disabled=not allowed) and allowed and chosen:
                open_saved(ctx, str(chosen))
        elif ctx.connected:
            st.caption("No saved scenarios yet.")
        if st.button("Refresh list", disabled=not ctx.connected) and ctx.connected:
            st.session_state.pop(SAVED_LIST_KEY, None)
            st.rerun()
    with col_sample:
        letter = st.selectbox(
            "Sample",
            options=list(SAMPLE_LABELS),
            format_func=lambda key: SAMPLE_LABELS[key].capitalize(),
        )
        if st.button("Open sample", disabled=not allowed) and allowed and letter:
            open_sample(str(letter))
        if st.button("Start a new empty scenario", disabled=not allowed) and allowed:
            open_empty(ctx)


def _id_follows_name(scenario_id: str, name: str) -> bool:
    """Whether the ID is still the one suggested, so a new name may suggest a new ID."""
    return scenario_id in ("NEW-SCENARIO", "") or (
        bool(name.strip()) and scenario_id == suggest_scenario_id(name)
    )


def _default_period() -> tuple[datetime, datetime]:
    start = datetime.combine(date.today(), time(0, 0))
    return start, start + timedelta(days=1)


def _period_text(period: tuple[str, str]) -> str:
    start, end = (datetime.fromisoformat(value) for value in period)
    return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M}"


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    raise ScenarioEditError("Choose a date.")


def _as_time(value: Any) -> time:
    if isinstance(value, time):
        return value
    raise ScenarioEditError("Choose a time.")
