"""Tasks: PO movements through forms, with filters, warnings, and spreadsheet import.

Choosing the movement fills and locks the plant end (plan §9.4): a pickup is delivered
to the plant, a drop is picked up there, and a pickup-drop touches neither. The
movement choice sits outside the form so the form can show the right pickers at once.
Importing goes through the backend contract and applies all rows or none (§9.5).
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

import streamlit as st

from frontend.api_client import BackendClientError
from frontend.import_preview import read_table_rows
from frontend.state.fleet import fleet_tags
from frontend.state.scenario_state import (
    ScenarioEditError,
    delete_task,
    find_row,
    rename_task_id,
    row_ids,
    rows,
)
from frontend.state.settings import period_bounds, planner_defaults
from frontend.state.tasks import (
    DROP,
    DUE_EVENT_HELP,
    DUE_EVENTS,
    IMPORT_MODE_LABELS,
    MOVEMENT_SHORT,
    MOVEMENTS,
    PICKUP,
    PRIORITY_HELP,
    PRIORITY_LABELS,
    ImportMode,
    TaskEdit,
    TaskFields,
    add_task,
    apply_imported_tasks,
    duplicate_task,
    edit_task,
    filter_tasks,
    form_fields,
    free_end_choices,
    location_label,
    plant_id,
    task_table_rows,
    task_warnings,
)
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    next_step_button,
    render_backend_error,
    row_revision,
    set_flash,
    table,
)
from frontend.views.imports import render_template_downloads

EDIT_KEY = "tasks_edit_id"
EDIT_NEXT_KEY = "tasks_edit_next"
ADD_ROUND_KEY = "tasks_add_round"
ADD_MOVEMENT_KEY = "tasks_add_movement"
IMPORT_PREVIEW_KEY = "tasks_import_preview"


def render(ctx: AppContext) -> None:
    st.header("Tasks")
    st.caption(
        "Each task moves one PO line: a pickup brings goods to the plant, a drop takes "
        "them to a customer, and a pickup-drop goes between two other places."
    )
    scenario = get_workspace().scenario
    unit = str(planner_defaults(scenario)["capacity_unit"])
    _render_table(scenario, unit)
    tab_add, tab_edit, tab_import = st.tabs(
        ["Add a task", "Edit, duplicate, or delete", "Import from a spreadsheet"]
    )
    with tab_add:
        if len(row_ids(scenario, "locations")) < 2:
            st.info("Add the plant and at least one other location before adding tasks.")
        else:
            _render_add(scenario, unit)
    with tab_edit:
        _render_edit(scenario, unit)
    with tab_import:
        _render_import(ctx)
    next_step_button("review", "Next: Review")


def _render_table(scenario: dict[str, Any], unit: str) -> None:
    tasks = rows(scenario, "tasks")
    if not tasks:
        st.info("No tasks yet.")
        return
    col_movement, col_location, col_priority = st.columns(3)
    movements = col_movement.multiselect(
        "Movement",
        options=list(MOVEMENTS),
        format_func=lambda key: MOVEMENT_SHORT[key],
        key="tasks_filter_movement",
    )
    location_options = ["", *row_ids(scenario, "locations")]
    location = col_location.selectbox(
        "Location",
        options=location_options,
        format_func=lambda key: "Any location" if not key else location_label(scenario, key),
        key="tasks_filter_location",
    )
    priorities = col_priority.multiselect(
        "Priority",
        options=list(PRIORITY_LABELS),
        format_func=lambda value: f"{value} {PRIORITY_LABELS[value]}",
        key="tasks_filter_priority",
    )
    shown = filter_tasks(
        scenario, movements=movements, location_id=location or None, priorities=priorities
    )
    st.caption(f"{len(shown)} of {len(tasks)} task(s).")
    table(task_table_rows(scenario, shown, unit))


def _default_day(scenario: dict[str, Any]) -> date:
    bounds = period_bounds(scenario)
    return bounds[0].date() if bounds else date.today()


def _movement_choice(key: str, current: str) -> str:
    if st.session_state.get(key) not in MOVEMENTS:
        st.session_state[key] = current if current in MOVEMENTS else PICKUP
    return str(
        st.radio(
            "Movement",
            options=list(MOVEMENTS),
            format_func=lambda value: MOVEMENTS[value],
            horizontal=True,
            key=key,
        )
    )


def _task_form_fields(
    scenario: dict[str, Any],
    prefix: str,
    movement: str,
    unit: str,
    current: TaskFields,
) -> TaskFields:
    plant = plant_id(scenario)
    free = free_end_choices(scenario)

    def picker(label: str, value: str | None, key: str) -> str | None:
        if not free:
            st.warning("There is no location other than the plant yet.")
            return None
        return str(
            st.selectbox(
                label,
                options=free,
                index=free.index(value) if value in free else 0,
                format_func=lambda location_id: location_label(scenario, location_id),
                key=key,
            )
        )

    def locked(label: str, key: str) -> str:
        st.selectbox(
            label,
            options=[plant],
            format_func=lambda location_id: location_label(scenario, location_id),
            disabled=True,
            key=key,
            help="Fixed by the movement: this end is the plant.",
        )
        return plant

    po_number = st.text_input("PO number", value=current.po_number, key=f"{prefix}-po")
    col_from, col_to = st.columns(2)
    with col_from:
        origin = (
            locked("Pick up at", f"{prefix}-from-plant")
            if movement == DROP
            else picker("Pick up at", current.origin, f"{prefix}-from")
        )
    with col_to:
        destination = (
            locked("Deliver to", f"{prefix}-to-plant")
            if movement == PICKUP
            else picker("Deliver to", current.destination, f"{prefix}-to")
        )
    quantity = st.number_input(
        f"Quantity ({unit})",
        min_value=0.001,
        value=float(current.quantity),
        step=1.0,
        format="%.3f",
        key=f"{prefix}-quantity",
    )
    col_ready_day, col_ready_time, col_due_day, col_due_time = st.columns(4)
    ready_day = col_ready_day.date_input(
        "Ready date", value=current.ready_day, key=f"{prefix}-ready-day"
    )
    ready_time = col_ready_time.time_input(
        "Ready time", value=current.ready_time, step=timedelta(minutes=5), key=f"{prefix}-ready"
    )
    due_day = col_due_day.date_input("Due date", value=current.due_day, key=f"{prefix}-due-day")
    due_time = col_due_time.time_input(
        "Due time", value=current.due_time, step=timedelta(minutes=5), key=f"{prefix}-due"
    )
    due_event = st.radio(
        "Deadline applies to",
        options=list(DUE_EVENTS),
        index=list(DUE_EVENTS).index(current.due_event) if current.due_event in DUE_EVENTS else 0,
        format_func=lambda value: DUE_EVENTS[value],
        horizontal=True,
        help=DUE_EVENT_HELP,
        key=f"{prefix}-due-event",
    )
    col_pickup, col_delivery = st.columns(2)
    pickup_minutes = col_pickup.number_input(
        "Pickup service minutes",
        min_value=0,
        max_value=1_440,
        value=int(current.pickup_service_minutes),
        step=5,
        key=f"{prefix}-pickup-minutes",
    )
    delivery_minutes = col_delivery.number_input(
        "Delivery service minutes",
        min_value=0,
        max_value=1_440,
        value=int(current.delivery_service_minutes),
        step=5,
        key=f"{prefix}-delivery-minutes",
    )
    priority = st.selectbox(
        "Priority",
        options=list(PRIORITY_LABELS),
        index=list(PRIORITY_LABELS).index(current.priority)
        if current.priority in PRIORITY_LABELS
        else 0,
        format_func=lambda value: f"{value} {PRIORITY_LABELS[value]}",
        help=PRIORITY_HELP,
        key=f"{prefix}-priority",
    )
    tag_options = sorted({*fleet_tags(scenario), *current.required_vehicle_tags})
    tags = st.multiselect(
        "Required truck tags",
        options=tag_options,
        default=[tag for tag in current.required_vehicle_tags if tag in tag_options],
        help="Only trucks with all of these tags may carry this PO. Tags come from the Fleet page.",
        key=f"{prefix}-tags",
    )
    notes = st.text_input("Notes", value=current.notes, key=f"{prefix}-notes")
    return TaskFields(
        po_number=po_number,
        movement=movement,
        origin=origin,
        destination=destination,
        quantity=quantity,
        ready_day=ready_day if isinstance(ready_day, date) else current.ready_day,
        ready_time=ready_time if isinstance(ready_time, time) else current.ready_time,
        due_day=due_day if isinstance(due_day, date) else current.due_day,
        due_time=due_time if isinstance(due_time, time) else current.due_time,
        due_event=str(due_event),
        pickup_service_minutes=int(pickup_minutes),
        delivery_service_minutes=int(delivery_minutes),
        priority=int(priority),
        required_vehicle_tags=list(tags),
        notes=notes,
    )


def _outcome_message(prefix: str, outcome: TaskEdit) -> str:
    message = prefix
    if outcome.period_extended:
        message += " The planning period was extended to include it."
    task = find_row(outcome.scenario, "tasks", outcome.task_id)
    warnings = task_warnings(outcome.scenario, task) if task else []
    if warnings:
        message += " " + " ".join(warnings)
    return message


def _render_add(scenario: dict[str, Any], unit: str) -> None:
    round_ = int(st.session_state.get(ADD_ROUND_KEY, 0))
    with st.container():
        movement = _movement_choice(ADD_MOVEMENT_KEY, PICKUP)
        defaults = planner_defaults(scenario)
        day = _default_day(scenario)
        blank = TaskFields(
            po_number="",
            movement=movement,
            origin=None,
            destination=None,
            quantity=1,
            ready_day=day,
            ready_time=time(7, 0),
            due_day=day,
            due_time=time(17, 0),
            pickup_service_minutes=int(defaults["pickup_service_minutes"]),
            delivery_service_minutes=int(defaults["delivery_service_minutes"]),
        )
        prefix = f"task-add-{round_}-{movement}"
        with st.form(f"add_task_{round_}"):
            fields = _task_form_fields(scenario, prefix, movement, unit, blank)
            with st.expander("Advanced: task ID"):
                task_id = st.text_input(
                    "Task ID", key=f"{prefix}-id", help="Leave empty for the next TASK-NNNN."
                )
            submitted = st.form_submit_button("Add task", type="primary")
    if submitted:
        try:
            outcome = add_task(scenario, fields, task_id=task_id or None)
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        st.session_state[ADD_ROUND_KEY] = round_ + 1
        st.session_state[EDIT_NEXT_KEY] = outcome.task_id
        commit_edit(
            outcome.scenario, message=_outcome_message(f"Added {outcome.task_id}.", outcome)
        )


def _task_label(scenario: dict[str, Any], task_id: str) -> str:
    task = find_row(scenario, "tasks", task_id)
    if task is None:
        return task_id
    movement = MOVEMENT_SHORT.get(str(task.get("task_type")), str(task.get("task_type")))
    return f"{task.get('po_number')} · {movement} ({task_id})"


def _render_edit(scenario: dict[str, Any], unit: str) -> None:
    task_ids = row_ids(scenario, "tasks")
    if not task_ids:
        st.caption("No tasks to edit yet.")
        return
    requested = st.session_state.pop(EDIT_NEXT_KEY, None)
    if requested in task_ids:
        st.session_state[EDIT_KEY] = requested
    if st.session_state.get(EDIT_KEY) not in task_ids:
        st.session_state[EDIT_KEY] = task_ids[0]
    selected = str(
        st.selectbox(
            "Task",
            options=task_ids,
            format_func=lambda key: _task_label(scenario, key),
            key=EDIT_KEY,
        )
    )
    task = find_row(scenario, "tasks", selected)
    if task is None:
        return
    for warning in task_warnings(scenario, task):
        st.warning(warning)
    current = form_fields(scenario, task)
    revision = row_revision(task)
    movement = _movement_choice(f"task-edit-{revision}-movement", current.movement)
    prefix = f"task-edit-{revision}-{movement}"
    with st.form(f"edit_task_{selected}"):
        fields = _task_form_fields(scenario, prefix, movement, unit, current)
        with st.expander("Advanced: task ID"):
            new_id = st.text_input("Task ID", value=selected, key=f"{prefix}-id")
        submitted = st.form_submit_button("Save task")
    if submitted:
        try:
            outcome = edit_task(scenario, selected, fields)
            updated = outcome.scenario
            clean_id = new_id.strip() or selected
            if clean_id != selected:
                updated = rename_task_id(updated, selected, clean_id)
        except ScenarioEditError as exc:
            st.error(str(exc))
            return
        # The picker's labels include the PO number; keep this task selected.
        st.session_state[EDIT_NEXT_KEY] = clean_id
        commit_edit(updated, message=_outcome_message("Task saved.", outcome))

    col_duplicate, col_delete = st.columns(2)
    if col_duplicate.button("Duplicate task", key="duplicate-task"):
        outcome = duplicate_task(scenario, selected)
        st.session_state[EDIT_NEXT_KEY] = outcome.task_id
        commit_edit(
            outcome.scenario,
            message=f"Duplicated as {outcome.task_id}. Enter its own PO number below.",
        )
    if col_delete.button("Delete task", key="delete-task"):
        commit_edit(delete_task(scenario, selected), message=f"Deleted task {selected}.")


def _render_import(ctx: AppContext) -> None:
    with st.container():
        st.caption(
            "A CSV or Excel file with one row per PO line. Locations may be given by ID or "
            "by exact name, and the plant end of a pickup or drop may be left empty. "
            "Nothing changes unless every row is valid."
        )
        render_template_downloads(ctx, "tasks", "task")
        uploaded = st.file_uploader("Task file", type=("csv", "xlsx"), key="tasks_import_file")
        check = st.button(
            "Check file", disabled=uploaded is None or not ctx.connected, key="tasks-import-check"
        )
        if check and uploaded is not None and ctx.connected:
            _check_file(ctx, uploaded.name, uploaded.getvalue())
        # Always shown, so the planner sees how the next file will be applied (and a
        # widget does not vanish after an import, which also keeps AppTest consistent).
        mode = ImportMode(
            st.radio(
                "How to import",
                options=[mode.value for mode in ImportMode],
                format_func=lambda value: IMPORT_MODE_LABELS[ImportMode(value)],
                key="tasks_import_mode",
            )
        )
        if mode is ImportMode.REPLACE:
            st.caption("Every current task not in the file will be deleted.")
        preview = st.session_state.get(IMPORT_PREVIEW_KEY)
        if isinstance(preview, dict):
            _render_import_preview(preview, mode)


def _check_file(ctx: AppContext, file_name: str, content: bytes) -> None:
    scenario = get_workspace().scenario
    try:
        raw_rows = read_table_rows(file_name, content)
    except ValueError as exc:
        st.error(str(exc))
        return
    defaults = planner_defaults(scenario)
    try:
        response = ctx.client.preview_task_import(
            raw_rows,
            locations=[
                {"location_id": str(location["location_id"]), "name": str(location["name"])}
                for location in rows(scenario, "locations")
                if location.get("location_id") and location.get("name")
            ],
            plant_location_id=plant_id(scenario),
            timezone=str(scenario.get("timezone") or "") or None,
            default_pickup_service_minutes=int(defaults["pickup_service_minutes"]),
            default_delivery_service_minutes=int(defaults["delivery_service_minutes"]),
        )
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    st.session_state[IMPORT_PREVIEW_KEY] = {"file": file_name, **response.payload}


def _render_import_preview(preview: dict[str, Any], mode: ImportMode) -> None:
    imported = [row for row in preview.get("rows", []) if isinstance(row, dict)]
    st.markdown(f"**{preview.get('file')}**: {len(imported)} task row(s) ready.")
    issues = [issue for issue in preview.get("issues", []) if isinstance(issue, dict)]
    if issues:
        table(issues, columns=("severity", "code", "row_number", "field", "message"))
    if imported:
        table(
            imported,
            columns=(
                "row_number",
                "task_id",
                "po_number",
                "task_type",
                "origin_location_id",
                "destination_location_id",
                "quantity",
                "ready_at",
                "due_at",
                "priority",
            ),
        )
    valid = bool(preview.get("valid")) and bool(imported)
    if not preview.get("valid"):
        st.error("The file has errors, so nothing can be imported. Fix them and check again.")
    if (
        st.button(f"Import {len(imported)} task(s)", disabled=not valid, key="tasks-import-apply")
        and valid
    ):
        try:
            outcome = apply_imported_tasks(get_workspace().scenario, imported, mode)
        except ScenarioEditError as exc:
            st.error(f"Nothing was imported. {exc}")
            return
        st.session_state.pop(IMPORT_PREVIEW_KEY, None)
        parts = [f"{len(outcome.added)} added", f"{len(outcome.updated)} updated"]
        if mode is ImportMode.REPLACE:
            parts.append(f"{len(outcome.removed)} removed")
        note = (
            " The planning period was extended to include them." if outcome.period_extended else ""
        )
        set_flash("success", f"Imported tasks: {', '.join(parts)}.{note}")
        commit_edit(outcome.scenario)
