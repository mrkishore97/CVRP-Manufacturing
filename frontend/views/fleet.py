"""Fleet: trucks and shifts, with a shift generator (plan §9.3).

Capacities carry the scenario's unit label, durations are h:mm, and distances are
kilometres. Shifts default to starting and ending at the plant. The generator builds
many shifts in one form and adds only new ones; adding a shift outside the planning
period extends the period to whole days around it.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import streamlit as st

from frontend.state.fleet import (
    WEEKDAY_LABELS,
    WORKING_DAYS,
    GeneratedStatus,
    ShiftEdit,
    add_shift,
    add_vehicle,
    apply_generated_shifts,
    duplicate_shift,
    duplicate_vehicle,
    edit_shift,
    edit_vehicle,
    fleet_tags,
    generate_shifts,
    parse_tags,
    plant_id,
    shift_bounds,
    shift_table_rows,
    timezone_of,
    vehicle_label,
    vehicle_table_rows,
)
from frontend.state.scenario_state import (
    ReferencedItemError,
    ScenarioEditError,
    delete_shift,
    delete_vehicle,
    find_row,
    rename_shift_id,
    rename_vehicle_id,
    row_ids,
    rows,
    vehicle_dependants,
)
from frontend.state.settings import period_bounds, planner_defaults
from frontend.state.units import meters_to_km, seconds_to_hmm
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    next_step_button,
    optional_hmm,
    row_revision,
    table,
)

TRUCK_EDIT_KEY = "fleet_truck_edit_id"
TRUCK_EDIT_NEXT_KEY = "fleet_truck_edit_next"
TRUCK_ADD_ROUND_KEY = "fleet_truck_add_round"
SHIFT_EDIT_KEY = "fleet_shift_edit_id"
SHIFT_EDIT_NEXT_KEY = "fleet_shift_edit_next"
SHIFT_ADD_ROUND_KEY = "fleet_shift_add_round"
GENERATOR_KEY = "fleet_generator_request"
HMM_HELP = "Hours and minutes, such as 9:30. Leave empty for no limit."


def render(ctx: AppContext) -> None:
    del ctx
    st.header("Fleet")
    st.caption(
        "Trucks and the shifts they work. A truck is planned only inside its shifts; "
        "each shift starts and ends at the plant unless you choose other places."
    )
    scenario = get_workspace().scenario
    unit = str(planner_defaults(scenario)["capacity_unit"])

    st.subheader("Trucks")
    if rows(scenario, "vehicles"):
        table(vehicle_table_rows(scenario, unit))
    else:
        st.info("No trucks yet. Add the first one below.")
    tab_add, tab_edit = st.tabs(["Add a truck", "Edit, duplicate, or delete"])
    with tab_add:
        _render_add_truck(scenario, unit)
    with tab_edit:
        _render_edit_truck(scenario, unit)

    st.divider()
    st.subheader("Shifts")
    if rows(scenario, "vehicle_shifts"):
        table(shift_table_rows(scenario))
    else:
        st.info("No shifts yet. Add one below, or generate many at once.")
    if not rows(scenario, "vehicles"):
        st.caption("Add a truck before giving it shifts.")
    else:
        tab_generate, tab_add_shift, tab_edit_shift = st.tabs(
            ["Generate shifts", "Add one shift", "Edit, copy, or delete"]
        )
        with tab_generate:
            _render_generator(scenario)
        with tab_add_shift:
            _render_add_shift(scenario)
        with tab_edit_shift:
            _render_edit_shift(scenario)
    next_step_button("tasks", "Next: Tasks")


# --- trucks -------------------------------------------------------------------------


def _truck_fields(
    prefix: str, unit: str, vehicle: dict[str, Any] | None
) -> tuple[str, float, bool, str, str, float | None]:
    vehicle = vehicle or {}
    name = st.text_input("Name", value=str(vehicle.get("name", "")), key=f"{prefix}-name")
    capacity = st.number_input(
        f"Capacity ({unit})",
        min_value=0.001,
        value=float(vehicle.get("capacity", 10)),
        step=1.0,
        format="%.3f",
        key=f"{prefix}-capacity",
        help="Up to three decimals.",
    )
    enabled = st.checkbox(
        "Enabled",
        value=bool(vehicle.get("enabled", True)),
        key=f"{prefix}-enabled",
        help="A disabled truck is kept but never planned.",
    )
    tags = st.text_input(
        "Tags",
        value=", ".join(parse_tags(vehicle.get("tags"))),
        key=f"{prefix}-tags",
        help="Comma-separated, such as REFRIGERATED. Tasks can require tags.",
    )
    duration = vehicle.get("maximum_route_duration_seconds")
    max_time = st.text_input(
        "Maximum route time (h:mm, optional)",
        value=seconds_to_hmm(duration) if duration else "",
        key=f"{prefix}-max-time",
        help=HMM_HELP,
    )
    distance = vehicle.get("maximum_route_distance_meters")
    max_km = st.number_input(
        "Maximum route distance (km, optional)",
        min_value=0.0,
        value=meters_to_km(distance) if distance else None,
        step=10.0,
        key=f"{prefix}-max-km",
        help="Leave empty for no limit.",
    )
    return name, float(capacity), bool(enabled), tags, max_time, max_km


def _render_add_truck(scenario: dict[str, Any], unit: str) -> None:
    round_ = int(st.session_state.get(TRUCK_ADD_ROUND_KEY, 0))
    with st.container():
        existing = fleet_tags(scenario)
        if existing:
            st.caption(f"Tags in use: {', '.join(existing)}")
        with st.form(f"add_truck_{round_}"):
            prefix = f"truck-add-{round_}"
            name, capacity, enabled, tags, max_time, max_km = _truck_fields(prefix, unit, None)
            with st.expander("Advanced: truck ID"):
                vehicle_id = st.text_input(
                    "Truck ID",
                    key=f"{prefix}-id",
                    help="Leave empty to have one suggested from the name.",
                )
            submitted = st.form_submit_button("Add truck", type="primary")
    if submitted:
        try:
            updated, new_id = add_vehicle(
                scenario,
                name=name,
                capacity=capacity,
                enabled=enabled,
                tags=tags,
                max_duration_seconds=optional_hmm(max_time, "Maximum route time"),
                max_distance_km=max_km or None,
                vehicle_id=vehicle_id or None,
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        st.session_state[TRUCK_ADD_ROUND_KEY] = round_ + 1
        st.session_state[TRUCK_EDIT_NEXT_KEY] = new_id
        commit_edit(updated, message=f"Added truck {new_id}. Give it shifts next.")


def _render_edit_truck(scenario: dict[str, Any], unit: str) -> None:
    vehicle_ids = row_ids(scenario, "vehicles")
    if not vehicle_ids:
        st.caption("No trucks to edit yet.")
        return
    selected = _selection(TRUCK_EDIT_KEY, TRUCK_EDIT_NEXT_KEY, vehicle_ids)
    selected = str(
        st.selectbox(
            "Truck",
            options=vehicle_ids,
            format_func=lambda key: vehicle_label(scenario, key),
            key=TRUCK_EDIT_KEY,
        )
    )
    vehicle = find_row(scenario, "vehicles", selected)
    if vehicle is None:
        return
    prefix = f"truck-edit-{row_revision(vehicle)}"
    with st.form(f"edit_truck_{selected}"):
        name, capacity, enabled, tags, max_time, max_km = _truck_fields(prefix, unit, vehicle)
        with st.expander("Advanced: truck ID"):
            new_id = st.text_input(
                "Truck ID",
                value=selected,
                key=f"{prefix}-id",
                help="Renaming the ID updates its shifts too.",
            )
        submitted = st.form_submit_button("Save truck")
    if submitted:
        try:
            updated = edit_vehicle(
                scenario,
                selected,
                name=name,
                capacity=capacity,
                enabled=enabled,
                tags=tags,
                max_duration_seconds=optional_hmm(max_time, "Maximum route time"),
                max_distance_km=max_km or None,
            )
            clean_id = new_id.strip() or selected
            if clean_id != selected:
                updated = rename_vehicle_id(updated, selected, clean_id)
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        # The picker's labels may change with the name; keep this truck selected.
        st.session_state[TRUCK_EDIT_NEXT_KEY] = clean_id
        commit_edit(updated, message="Truck saved.")

    col_duplicate, col_delete = st.columns(2)
    if col_duplicate.button("Duplicate truck", key="duplicate-truck"):
        updated, copy_id = duplicate_vehicle(scenario, selected)
        st.session_state[TRUCK_EDIT_NEXT_KEY] = copy_id
        commit_edit(updated, message=f"Duplicated as {copy_id}. Its shifts were not copied.")
    with col_delete:
        shifts = vehicle_dependants(scenario, selected)
        also = False
        if shifts:
            also = st.checkbox(
                f"Also delete its {len(shifts)} shift(s)", key=f"delete-truck-shifts-{selected}"
            )
        if st.button("Delete truck", key="delete-truck"):
            try:
                updated = delete_vehicle(scenario, selected, delete_dependants=also)
            except ReferencedItemError as exc:
                st.error(f"{exc} Tick the box to delete them too.")
                return
            commit_edit(updated, message=f"Deleted truck {selected}.")


# --- shifts -------------------------------------------------------------------------


def _location_options(scenario: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    plant = plant_id(scenario)
    ids = [plant, *[i for i in row_ids(scenario, "locations") if i != plant]]
    labels = {}
    for location_id in ids:
        location = find_row(scenario, "locations", location_id)
        name = location.get("name") if location else None
        mark = " — plant" if location_id == plant else ""
        labels[location_id] = f"{name or location_id} ({location_id}){mark}"
    return ids, labels


def _shift_fields(
    scenario: dict[str, Any], prefix: str, shift: dict[str, Any] | None, default_day: date
) -> tuple[str, date, time, time, str, str, str]:
    vehicle_ids = row_ids(scenario, "vehicles")
    location_ids, labels = _location_options(scenario)
    plant = plant_id(scenario)
    bounds = shift_bounds(shift, timezone_of(scenario)) if shift else None
    vehicle_id = st.selectbox(
        "Truck",
        options=vehicle_ids,
        index=vehicle_ids.index(shift["vehicle_id"])
        if shift and shift.get("vehicle_id") in vehicle_ids
        else 0,
        format_func=lambda key: vehicle_label(scenario, key),
        key=f"{prefix}-truck",
    )
    day = st.date_input(
        "Date", value=bounds[0].date() if bounds else default_day, key=f"{prefix}-date"
    )
    col_start, col_end = st.columns(2)
    start = col_start.time_input(
        "Start time",
        value=bounds[0].time().replace(tzinfo=None) if bounds else time(7, 0),
        step=timedelta(minutes=5),
        key=f"{prefix}-start",
    )
    end = col_end.time_input(
        "End time",
        value=bounds[1].time().replace(tzinfo=None) if bounds else time(17, 0),
        step=timedelta(minutes=5),
        key=f"{prefix}-end",
        help="An end time at or before the start time ends on the next day.",
    )
    start_at = str(shift.get("start_location_id", plant)) if shift else plant
    end_at = str(shift.get("end_location_id", plant)) if shift else plant
    col_from, col_to = st.columns(2)
    start_location = col_from.selectbox(
        "Starts at",
        options=location_ids,
        index=location_ids.index(start_at) if start_at in location_ids else 0,
        format_func=lambda key: labels[key],
        key=f"{prefix}-from",
    )
    end_location = col_to.selectbox(
        "Ends at",
        options=location_ids,
        index=location_ids.index(end_at) if end_at in location_ids else 0,
        format_func=lambda key: labels[key],
        key=f"{prefix}-to",
    )
    limit = shift.get("maximum_route_duration_seconds") if shift else None
    max_time = st.text_input(
        "Maximum route time for this shift (h:mm, optional)",
        value=seconds_to_hmm(limit) if limit else "",
        key=f"{prefix}-max-time",
        help=HMM_HELP,
    )
    return (
        str(vehicle_id),
        day if isinstance(day, date) else default_day,
        start,
        end,
        str(start_location),
        str(end_location),
        max_time,
    )


def _period_note(edit: ShiftEdit) -> str:
    return " The planning period was extended to include it." if edit.period_extended else ""


def _first_day(scenario: dict[str, Any]) -> date:
    bounds = period_bounds(scenario)
    return bounds[0].date() if bounds else date.today()


def _render_add_shift(scenario: dict[str, Any]) -> None:
    round_ = int(st.session_state.get(SHIFT_ADD_ROUND_KEY, 0))
    with st.form(f"add_shift_{round_}"):
        prefix = f"shift-add-{round_}"
        fields = _shift_fields(scenario, prefix, None, _first_day(scenario))
        with st.expander("Advanced: shift ID"):
            shift_id = st.text_input(
                "Shift ID", key=f"{prefix}-id", help="Leave empty for truck ID plus date."
            )
        submitted = st.form_submit_button("Add shift", type="primary")
    if submitted:
        vehicle_id, day, start, end, start_location, end_location, max_time = fields
        try:
            outcome = add_shift(
                scenario,
                vehicle_id=vehicle_id,
                day=day,
                start=start,
                end=end,
                start_location_id=start_location,
                end_location_id=end_location,
                max_duration_seconds=optional_hmm(max_time, "Maximum route time"),
                shift_id=shift_id or None,
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        st.session_state[SHIFT_ADD_ROUND_KEY] = round_ + 1
        st.session_state[SHIFT_EDIT_NEXT_KEY] = outcome.shift_id
        commit_edit(
            outcome.scenario, message=f"Added shift {outcome.shift_id}.{_period_note(outcome)}"
        )


def _render_edit_shift(scenario: dict[str, Any]) -> None:
    shift_ids = row_ids(scenario, "vehicle_shifts")
    if not shift_ids:
        st.caption("No shifts to edit yet.")
        return
    timezone = timezone_of(scenario)

    def label(shift_id: str) -> str:
        shift = find_row(scenario, "vehicle_shifts", shift_id)
        bounds = shift_bounds(shift, timezone) if shift else None
        when = bounds[0].strftime("%a %Y-%m-%d %H:%M") if bounds else ""
        truck = vehicle_label(scenario, str(shift.get("vehicle_id"))) if shift else ""
        return f"{truck} · {when} ({shift_id})"

    _selection(SHIFT_EDIT_KEY, SHIFT_EDIT_NEXT_KEY, shift_ids)
    selected = str(st.selectbox("Shift", options=shift_ids, format_func=label, key=SHIFT_EDIT_KEY))
    shift = find_row(scenario, "vehicle_shifts", selected)
    if shift is None:
        return
    prefix = f"shift-edit-{row_revision(shift)}"
    with st.form(f"edit_shift_{selected}"):
        fields = _shift_fields(scenario, prefix, shift, _first_day(scenario))
        with st.expander("Advanced: shift ID"):
            new_id = st.text_input("Shift ID", value=selected, key=f"{prefix}-id")
        submitted = st.form_submit_button("Save shift")
    if submitted:
        vehicle_id, day, start, end, start_location, end_location, max_time = fields
        try:
            outcome = edit_shift(
                scenario,
                selected,
                vehicle_id=vehicle_id,
                day=day,
                start=start,
                end=end,
                start_location_id=start_location,
                end_location_id=end_location,
                max_duration_seconds=optional_hmm(max_time, "Maximum route time"),
            )
            updated = outcome.scenario
            clean_id = new_id.strip() or selected
            if clean_id != selected:
                updated = rename_shift_id(updated, selected, clean_id)
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        st.session_state[SHIFT_EDIT_NEXT_KEY] = clean_id
        commit_edit(updated, message=f"Shift saved.{_period_note(outcome)}")

    col_duplicate, col_delete = st.columns(2)
    if col_duplicate.button("Copy to the next day", key="duplicate-shift"):
        outcome = duplicate_shift(scenario, selected)
        st.session_state[SHIFT_EDIT_NEXT_KEY] = outcome.shift_id
        commit_edit(
            outcome.scenario,
            message=f"Copied as {outcome.shift_id}.{_period_note(outcome)}",
        )
    if col_delete.button("Delete shift", key="delete-shift"):
        commit_edit(delete_shift(scenario, selected), message=f"Deleted shift {selected}.")


def _render_generator(scenario: dict[str, Any]) -> None:
    with st.container():
        st.caption(
            "Choose trucks, days, and hours. The preview flags shifts that already exist "
            "or overlap another shift of the same truck; only new shifts are added."
        )
        vehicle_ids = row_ids(scenario, "vehicles")
        enabled = [
            str(vehicle["vehicle_id"])
            for vehicle in rows(scenario, "vehicles")
            if vehicle.get("enabled", True) and vehicle.get("vehicle_id")
        ]
        bounds = period_bounds(scenario)
        first = bounds[0].date() if bounds else date.today()
        last = (bounds[1] - timedelta(seconds=1)).date() if bounds else first
        location_ids, labels = _location_options(scenario)
        with st.form("shift_generator"):
            chosen = st.multiselect(
                "Trucks",
                options=vehicle_ids,
                default=enabled,
                format_func=lambda key: vehicle_label(scenario, key),
                key="generator-trucks",
            )
            col_first, col_last = st.columns(2)
            first_day = col_first.date_input("First day", value=first, key="generator-first")
            last_day = col_last.date_input("Last day", value=last, key="generator-last")
            weekdays = st.multiselect(
                "Weekdays",
                options=list(range(7)),
                default=sorted(WORKING_DAYS),
                format_func=lambda day: WEEKDAY_LABELS[day],
                key="generator-weekdays",
            )
            col_start, col_end = st.columns(2)
            start = col_start.time_input(
                "Start time", value=time(7, 0), step=timedelta(minutes=5), key="generator-start"
            )
            end = col_end.time_input(
                "End time",
                value=time(17, 0),
                step=timedelta(minutes=5),
                key="generator-end",
                help="An end time at or before the start time ends on the next day.",
            )
            col_from, col_to = st.columns(2)
            start_location = col_from.selectbox(
                "Starts at",
                options=location_ids,
                format_func=lambda key: labels[key],
                key="generator-from",
            )
            end_location = col_to.selectbox(
                "Ends at",
                options=location_ids,
                format_func=lambda key: labels[key],
                key="generator-to",
            )
            max_time = st.text_input(
                "Maximum route time per shift (h:mm, optional)",
                key="generator-max-time",
                help=HMM_HELP,
            )
            preview = st.form_submit_button("Preview shifts")
        if preview:
            st.session_state[GENERATOR_KEY] = {
                "vehicle_ids": list(chosen),
                "first_day": first_day,
                "last_day": last_day,
                "weekdays": list(weekdays),
                "start": start,
                "end": end,
                "start_location_id": start_location,
                "end_location_id": end_location,
                "max_time": max_time,
            }
        request = st.session_state.get(GENERATOR_KEY)
        if isinstance(request, dict):
            _render_generator_preview(scenario, request)


def _render_generator_preview(scenario: dict[str, Any], request: dict[str, Any]) -> None:
    try:
        generated = generate_shifts(
            scenario,
            vehicle_ids=request["vehicle_ids"],
            first_day=request["first_day"],
            last_day=request["last_day"],
            weekdays=request["weekdays"],
            start=request["start"],
            end=request["end"],
        )
        max_seconds = optional_hmm(str(request["max_time"]), "Maximum route time")
    except ScenarioEditError as exc:
        st.error(str(exc))
        return
    if not generated:
        st.info("No day in that range falls on the chosen weekdays.")
        return
    new = [item for item in generated if item.status is GeneratedStatus.NEW]
    table(
        [
            {
                "Truck": vehicle_label(scenario, item.vehicle_id),
                "Date": item.day.strftime("%a %Y-%m-%d"),
                "Start": item.start[11:16],
                "End": item.end[11:16],
                "Shift ID": item.shift_id or "—",
                "Status": item.status.value + (f" ({item.note})" if item.note else ""),
            }
            for item in generated
        ]
    )
    skipped = len(generated) - len(new)
    st.caption(f"{len(new)} new shift(s); {skipped} skipped.")
    if st.button(
        f"Add {len(new)} new shift(s)", type="primary", disabled=not new, key="generator-apply"
    ):
        try:
            outcome = apply_generated_shifts(
                scenario,
                generated,
                start_location_id=str(request["start_location_id"]),
                end_location_id=str(request["end_location_id"]),
                max_duration_seconds=max_seconds,
            )
        except ScenarioEditError as exc:
            st.error(f"Nothing was added. {exc}")
            return
        st.session_state.pop(GENERATOR_KEY, None)
        note = (
            " The planning period was extended to include them." if outcome.period_extended else ""
        )
        commit_edit(
            outcome.scenario,
            message=f"Added {len(outcome.added)} shift(s); {outcome.skipped} skipped.{note}",
        )


def _selection(key: str, next_key: str, options: list[str]) -> str:
    """Apply a pending selection before the selectbox exists, and keep it valid."""
    requested = st.session_state.pop(next_key, None)
    if requested in options:
        st.session_state[key] = requested
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    return str(st.session_state[key])
