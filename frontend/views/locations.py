"""Locations: name and address only; resolve, review, confirm, retry, import, copy.

Coordinates never appear here (plan §8.1). Resolving is an explicit, billable action
that sends only new or changed addresses; reruns and page visits send nothing.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from frontend.api_client import BackendClientError
from frontend.state.locations import (
    ADDRESS_HINT,
    READINESS_LABELS,
    add_location,
    apply_resolutions,
    confirm_match,
    copy_locations,
    duplicate_location,
    edit_location,
    failed_ids,
    locations_in_order,
    merge_imported_locations,
    pending_ids,
    plant_coordinates,
    plant_id,
    resolve_rows,
    table_rows,
    used_by,
)
from frontend.state.readiness import LocationReadiness
from frontend.state.scenario_state import (
    ReferencedItemError,
    ScenarioEditError,
    delete_location,
    find_row,
    location_dependants,
    normalize_address,
    rename_location_id,
    rows,
    update_location_address,
)
from frontend.state.workspace import record_resolutions
from frontend.views.components import (
    AppContext,
    commit_edit,
    get_workspace,
    next_step_button,
    render_backend_error,
    set_flash,
    set_workspace,
    table,
)
from frontend.views.opening import saved_scenario_label, saved_scenarios

EDIT_KEY = "locations_edit_id"
EDIT_NEXT_KEY = "locations_edit_next"
ADD_ROUND_KEY = "locations_add_round"
IMPORT_PREVIEW_KEY = "locations_import_preview"
COPY_SOURCE_KEY = "locations_copy_source"


def render(ctx: AppContext) -> None:
    st.header("Locations")
    st.caption(
        "A location needs only a name and an address. Press Resolve addresses to have "
        "the backend find them; nothing is sent to Google until you press it."
    )
    workspace = get_workspace()
    scenario = workspace.scenario
    readiness = ctx.status.readiness

    _render_summary(readiness)
    if rows(scenario, "locations"):
        table(table_rows(scenario, readiness))
    else:
        st.info("No locations yet. Add the plant on the Scenario page, then add others here.")

    _render_resolve_actions(ctx)
    _render_review(ctx)
    _render_failed(ctx)
    st.divider()
    _render_add(scenario)
    _render_edit(scenario)
    st.divider()
    _render_import(ctx)
    _render_copy(ctx)
    next_step_button("fleet", "Next: Fleet")


def _render_summary(readiness: Mapping[str, LocationReadiness]) -> None:
    counts: dict[str, int] = {}
    for value in readiness.values():
        label = READINESS_LABELS[value]
        counts[label] = counts.get(label, 0) + 1
    if counts:
        st.caption(" · ".join(f"{label}: {count}" for label, count in counts.items()))


def _render_resolve_actions(ctx: AppContext) -> None:
    scenario = get_workspace().scenario
    readiness = ctx.status.readiness
    pending = pending_ids(scenario, readiness)
    failed = failed_ids(scenario, readiness)
    col_resolve, col_retry = st.columns(2)
    resolve = col_resolve.button(
        f"Resolve addresses ({len(pending)} pending)",
        type="primary",
        disabled=not pending or not ctx.connected,
        help=(
            "Sends only new or changed addresses through the backend. Each is a billable "
            "Google lookup unless the backend's 30-day address cache already has it."
        ),
    )
    retry = col_retry.button(
        f"Retry not found ({len(failed)})",
        disabled=not failed or not ctx.connected,
        help="Looks up addresses that were not found again. Correcting them usually works better.",
    )
    if ctx.config is not None and not ctx.config.google_maps_configured:
        st.caption(
            "The backend has no Google key configured, so it cannot resolve addresses. "
            "Scenarios with coordinates and travel times in their JSON still work."
        )
    if resolve and pending and ctx.connected:
        _resolve(ctx, pending)
    if retry and failed and ctx.connected:
        _resolve(ctx, failed)


def _resolve(ctx: AppContext, location_ids: list[str]) -> None:
    workspace = get_workspace()
    scenario = workspace.scenario
    request_rows = resolve_rows(scenario, location_ids)
    try:
        response = ctx.client.resolve_locations(
            request_rows,
            plant_location_id=plant_id(scenario),
            plant_coordinates=plant_coordinates(scenario, ctx.status.readiness, location_ids),
        )
    except BackendClientError as exc:
        render_backend_error(exc)
        return
    results = [result for result in response.payload.get("results", []) if isinstance(result, dict)]
    sent = {row["location_id"]: row["address"] for row in request_rows}
    applied = apply_resolutions(scenario, results, sent_addresses=sent)
    set_workspace(record_resolutions(workspace, applied.scenario, results, sent_addresses=sent))
    set_flash("success", _resolve_summary(response.payload.get("summary")))
    st.rerun()


def _resolve_summary(summary: Any) -> str:
    if not isinstance(summary, dict):
        return "Addresses resolved."
    parts = [f"{summary.get('resolved', 0)} resolved"]
    if summary.get("needs_review"):
        count = int(summary["needs_review"])
        parts.append(f"{count} {'needs' if count == 1 else 'need'} review")
    if summary.get("failed"):
        parts.append(f"{summary['failed']} not found")
    lookups = (
        f"{summary.get('provider_calls', 0)} Google lookup(s), "
        f"{summary.get('cache_hits', 0)} from the 30-day cache"
    )
    return f"Addresses: {', '.join(parts)} ({lookups})."


def _render_review(ctx: AppContext) -> None:
    workspace = get_workspace()
    scenario = workspace.scenario
    waiting = [
        location
        for location in locations_in_order(scenario)
        if ctx.status.readiness.get(str(location.get("location_id")))
        is LocationReadiness.NEEDS_REVIEW
    ]
    if not waiting:
        return
    st.subheader(f"Needs review ({len(waiting)})")
    st.caption(
        "Google's match for these addresses is doubtful. Compare the two addresses, then "
        "confirm the match or correct the address."
    )
    for location in waiting:
        location_id = str(location["location_id"])
        details = _session_details(workspace.derived.resolutions, location)
        with st.container(border=True):
            st.markdown(f"**{location.get('name')}**")
            st.markdown(f"You typed: {location.get('address')}")
            st.markdown(f"Google matched: **{location.get('formatted_address', '—')}**")
            if location.get("geocode_warning"):
                st.caption(str(location["geocode_warning"]))
            distance = details.get("distance_from_plant_km") if details else None
            if isinstance(distance, int | float):
                st.caption(f"{distance:,.0f} km from the plant in a straight line.")
            col_confirm, col_edit = st.columns(2)
            if col_confirm.button("Confirm match", key=f"confirm-{location_id}"):
                commit_edit(
                    confirm_match(scenario, location_id),
                    message=f"Confirmed the match for {location.get('name')}.",
                )
            if col_edit.button("Correct the address", key=f"correct-{location_id}"):
                _select_for_edit(location_id)
            alternatives = details.get("alternatives") if details else None
            if isinstance(alternatives, list) and alternatives:
                st.caption("Other places Google found for this address:")
                for index, alternative in enumerate(alternatives):
                    col_text, col_use = st.columns([3, 1])
                    col_text.markdown(str(alternative))
                    if col_use.button("Use this address", key=f"alt-{location_id}-{index}"):
                        commit_edit(
                            update_location_address(scenario, location_id, str(alternative)),
                            message=(
                                f"Address of {location.get('name')} changed. Press Resolve "
                                "addresses to look it up."
                            ),
                        )


def _render_failed(ctx: AppContext) -> None:
    scenario = get_workspace().scenario
    failed = [
        location
        for location in locations_in_order(scenario)
        if ctx.status.readiness.get(str(location.get("location_id"))) is LocationReadiness.FAILED
    ]
    if not failed:
        return
    st.subheader(f"Not found ({len(failed)})")
    for location in failed:
        location_id = str(location["location_id"])
        col_text, col_edit = st.columns([3, 1])
        col_text.markdown(
            f"**{location.get('name')}** — {location.get('address')}"
            + (f"  \n{location['geocode_warning']}" if location.get("geocode_warning") else "")
        )
        if col_edit.button("Correct the address", key=f"correct-failed-{location_id}"):
            _select_for_edit(location_id)


def _render_add(scenario: dict[str, Any]) -> None:
    st.subheader("Add a location")
    # New widget keys after each add give empty fields. ``clear_on_submit`` leaves the
    # field that had focus showing its old text, inviting a wrong address next time.
    round_ = int(st.session_state.get(ADD_ROUND_KEY, 0))
    with st.form(f"add_location_{round_}"):
        name = st.text_input("Name", key=f"add_location_name_{round_}")
        address = st.text_input("Address", key=f"add_location_address_{round_}", help=ADDRESS_HINT)
        with st.expander("Advanced: location ID"):
            location_id = st.text_input(
                "Location ID",
                key=f"add_location_id_{round_}",
                help="Leave empty to have one suggested from the name.",
            )
        submitted = st.form_submit_button("Add location", type="primary")
    if submitted:
        try:
            updated = add_location(
                scenario, name=name, address=address, location_id=location_id or None
            )
        except ScenarioEditError as exc:
            st.error(str(exc))
        else:
            st.session_state[ADD_ROUND_KEY] = round_ + 1
            commit_edit(
                updated, message=f"Added {' '.join(name.split())}. Resolve its address next."
            )


def _render_edit(scenario: dict[str, Any]) -> None:
    locations = locations_in_order(scenario)
    if not locations:
        return
    st.subheader("Edit, duplicate, or delete")
    labels = {
        str(location["location_id"]): f"{location.get('name')} ({location['location_id']})"
        for location in locations
        if location.get("location_id")
    }
    requested = st.session_state.pop(EDIT_NEXT_KEY, None)
    if requested in labels:
        st.session_state[EDIT_KEY] = requested
    if st.session_state.get(EDIT_KEY) not in labels:
        st.session_state[EDIT_KEY] = next(iter(labels))
    selected = str(
        st.selectbox(
            "Location", options=list(labels), format_func=lambda key: labels[key], key=EDIT_KEY
        )
    )
    location = find_row(scenario, "locations", selected)
    if location is None:
        return
    st.caption(f"{used_by(scenario, selected)}.")
    with st.form(f"edit_location_{selected}"):
        name = st.text_input(
            "Name", value=str(location.get("name", "")), key=f"edit-{selected}-name"
        )
        address = st.text_input(
            "Address",
            value=str(location.get("address", "")),
            key=f"edit-{selected}-address",
            help="Changing the address clears its match; resolve it again afterwards.",
        )
        with st.expander("Advanced: location ID"):
            new_id = st.text_input(
                "Location ID",
                value=selected,
                key=f"edit-{selected}-id",
                help="Renaming the ID updates every task and shift that uses it.",
            )
        submitted = st.form_submit_button("Save location")
    if submitted:
        _save_edit(scenario, selected, name=name, address=address, new_id=new_id.strip())

    col_duplicate, col_delete = st.columns(2)
    if col_duplicate.button("Duplicate", key="duplicate-location"):
        updated, copy_id = duplicate_location(scenario, selected)
        st.session_state[EDIT_NEXT_KEY] = copy_id
        commit_edit(updated, message=f"Duplicated as {copy_id}.")
    with col_delete:
        _render_delete(scenario, selected)


def _save_edit(
    scenario: dict[str, Any], location_id: str, *, name: str, address: str, new_id: str
) -> None:
    location = find_row(scenario, "locations", location_id)
    assert location is not None
    address_changed = normalize_address(address) != normalize_address(
        str(location.get("address", ""))
    )
    try:
        updated = edit_location(scenario, location_id, name=name, address=address)
        renames: dict[str, str] = {}
        if new_id and new_id != location_id:
            updated = rename_location_id(updated, location_id, new_id)
            renames[location_id] = new_id
    except ScenarioEditError as exc:
        st.error(str(exc))
        return
    if renames:
        st.session_state[EDIT_NEXT_KEY] = new_id
    message = "Location saved."
    if address_changed:
        message += " Its address changed: resolve it again."
    commit_edit(updated, message=message, renamed_locations=renames)


def _render_delete(scenario: dict[str, Any], location_id: str) -> None:
    dependants = location_dependants(scenario, location_id)
    if any(dependant.kind == "plant" for dependant in dependants):
        st.caption("The plant cannot be deleted. Choose another plant on the Scenario page first.")
        return
    also_dependants = False
    if dependants:
        tasks = sum(dependant.kind == "task" for dependant in dependants)
        shifts = sum(dependant.kind == "shift" for dependant in dependants)
        also_dependants = st.checkbox(
            f"Also delete the {tasks} task(s) and {shifts} shift(s) that use it",
            key=f"delete-dependants-{location_id}",
        )
    if st.button("Delete", key="delete-location"):
        try:
            updated = delete_location(scenario, location_id, delete_dependants=also_dependants)
        except ReferencedItemError as exc:
            st.error(f"{exc} Tick the box to delete them too.")
            return
        commit_edit(updated, message=f"Deleted location {location_id}.")


def _render_import(ctx: AppContext) -> None:
    with st.expander("Import locations from a spreadsheet"):
        st.caption(
            "A CSV or Excel file with a name column and an address column (an ID column is "
            "optional). Rows matching an existing location by ID, or by a unique name, "
            "update it; other rows are added. Imported addresses are not resolved yet."
        )
        uploaded = st.file_uploader(
            "Location file", type=("csv", "xlsx"), key="locations_import_file"
        )
        check = st.button(
            "Check file", disabled=uploaded is None or not ctx.connected, key="import-check"
        )
        if check and uploaded is not None and ctx.connected:
            try:
                raw_rows = read_table_rows(uploaded.name, uploaded.getvalue())
            except ValueError as exc:
                st.error(str(exc))
                return
            try:
                response = ctx.client.preview_location_import(raw_rows)
            except BackendClientError as exc:
                render_backend_error(exc)
                return
            st.session_state[IMPORT_PREVIEW_KEY] = {
                "file": uploaded.name,
                **response.payload,
            }
        preview = st.session_state.get(IMPORT_PREVIEW_KEY)
        if not isinstance(preview, dict):
            return
        imported = [row for row in preview.get("rows", []) if isinstance(row, dict)]
        st.markdown(f"**{preview.get('file')}**: {len(imported)} location row(s) read.")
        issues = [issue for issue in preview.get("issues", []) if isinstance(issue, dict)]
        if issues:
            table(issues, columns=("severity", "code", "row_number", "field", "message"))
        if imported:
            table(imported, columns=("row_number", "location_id", "name", "address"))
        valid = bool(preview.get("valid")) and bool(imported)
        if not preview.get("valid"):
            st.error("The file has errors, so nothing can be imported. Fix them and check again.")
        if (
            st.button(f"Import {len(imported)} location(s)", disabled=not valid, key="import-apply")
            and valid
        ):
            try:
                outcome = merge_imported_locations(get_workspace().scenario, imported)
            except ScenarioEditError as exc:
                st.error(f"Nothing was imported. {exc}")
                return
            st.session_state.pop(IMPORT_PREVIEW_KEY, None)
            commit_edit(
                outcome.scenario,
                message=(
                    f"Imported locations: {len(outcome.added)} added, "
                    f"{len(outcome.updated)} updated, {len(outcome.unchanged)} unchanged."
                ),
            )


def _render_copy(ctx: AppContext) -> None:
    with st.expander("Copy locations from a saved scenario"):
        summaries = saved_scenarios(ctx)
        if not summaries:
            st.caption("No saved scenarios to copy from.")
            return
        by_id = {str(summary.get("scenario_id")): summary for summary in summaries}
        chosen = st.selectbox(
            "Saved scenario",
            options=list(by_id),
            format_func=lambda key: saved_scenario_label(by_id[key]),
            key="locations_copy_scenario",
        )
        if st.button("Show its locations", key="copy-show") and chosen:
            try:
                response = ctx.client.load_scenario(str(chosen))
            except BackendClientError as exc:
                render_backend_error(exc)
                return
            document = response.payload.get("payload")
            source_rows = rows(document, "locations") if isinstance(document, dict) else []
            st.session_state[COPY_SOURCE_KEY] = {"scenario_id": chosen, "locations": source_rows}
        source = st.session_state.get(COPY_SOURCE_KEY)
        if not isinstance(source, dict) or source.get("scenario_id") != chosen:
            return
        source_rows = [row for row in source.get("locations", []) if isinstance(row, dict)]
        options = {
            str(row.get("location_id")): f"{row.get('name')} — {row.get('address')}"
            for row in source_rows
        }
        picked = st.multiselect(
            "Locations to copy",
            options=list(options),
            format_func=lambda key: options[key],
            key="locations_copy_pick",
        )
        if st.button(f"Copy {len(picked)} location(s)", disabled=not picked, key="copy-apply"):
            outcome = copy_locations(
                get_workspace().scenario,
                [row for row in source_rows if str(row.get("location_id")) in set(picked)],
            )
            st.session_state.pop(COPY_SOURCE_KEY, None)
            skipped = (
                f" {len(outcome.skipped)} skipped because the address is already here."
                if outcome.skipped
                else ""
            )
            commit_edit(
                outcome.scenario, message=f"Copied {len(outcome.added)} location(s).{skipped}"
            )


def _select_for_edit(location_id: str) -> None:
    """Open a location in the edit form on the next run (the form is further down)."""
    st.session_state[EDIT_NEXT_KEY] = location_id
    st.rerun()


def _session_details(
    resolutions: Mapping[str, Mapping[str, Any]], location: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    """This session's resolve details for the location, if they are for its address."""
    details = resolutions.get(str(location.get("location_id")))
    if details is None:
        return None
    if normalize_address(str(details.get("address", ""))) != normalize_address(
        str(location.get("address", ""))
    ):
        return None
    return details


def read_table_rows(file_name: str, content: bytes) -> list[dict[str, Any]]:
    """Rows of a CSV or XLSX file keyed by its headers; cells are text or numbers."""
    try:
        if file_name.lower().endswith(".xlsx"):
            frame = pd.read_excel(io.BytesIO(content), dtype=object)
        else:
            frame = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8-sig")
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"The file could not be read: {exc}") from exc
    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        records.append({str(key): _cell(value) for key, value in record.items()})
    if not records:
        raise ValueError("The file has no rows.")
    return records


def _cell(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)
