"""The scenario plus everything derived from it, and the transitions between states.

``Workspace.scenario`` is the canonical scenario the planner edits. ``Workspace.derived``
holds what backend calls produced — validation, the active travel-time matrix, the plan —
together with the fingerprints of the inputs each was produced from. Freshness is always
computed by comparing those fingerprints with the current scenario
(``readiness.workflow_status``), never stored as a flag.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from frontend.state.fingerprints import (
    matrix_identity,
    matrix_input_fingerprint,
    plan_input_fingerprint,
    saved_fingerprint,
    stable_fingerprint,
)
from frontend.state.json_io import (
    ExportMode,
    carry_over_derived,
    document_for_export,
    split_document,
)
from frontend.state.scenario_state import Scenario, row_ids, rows

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Derived:
    """Backend results and the input fingerprints they were produced from."""

    validation: JsonObject | None = None
    validation_fingerprint: str | None = None
    validation_request_id: str | None = None
    validation_error: str | None = None
    validation_attempt_fingerprint: str | None = None
    matrix: JsonObject | None = None
    matrix_input_fingerprint: str | None = None
    matrix_origin: str | None = None  # "json" or "calculated"
    matrix_cache_hit: bool | None = None
    embedded_matrix: JsonObject | None = None
    matrix_estimate: JsonObject | None = None
    matrix_estimate_fingerprint: str | None = None
    resolutions: Mapping[str, JsonObject] = field(default_factory=dict)
    """Latest resolve result per location ID, for review details (alternatives, reasons).

    Kept for this session only; the location itself holds what must survive a save.
    Each entry records the address it was for, so an edited address shows nothing stale.
    """
    plan: JsonObject | None = None
    plan_input_fingerprint: str | None = None
    plan_request_id: str | None = None
    baseline_fingerprint: str | None = None
    loaded_from: str | None = None


@dataclass(frozen=True, slots=True)
class Workspace:
    scenario: Scenario
    derived: Derived = field(default_factory=Derived)


def load_document(document: Mapping[str, Any], *, source: str) -> Workspace:
    """Start from a JSON document; a matching embedded matrix becomes the active one."""
    scenario, matrix = split_document(document)
    derived = Derived(
        embedded_matrix=matrix,
        baseline_fingerprint=saved_fingerprint(scenario),
        loaded_from=source,
    )
    workspace = Workspace(scenario=scenario, derived=derived)
    if matrix is not None and matrix_matches_locations(matrix, scenario):
        workspace = record_matrix(workspace, matrix, origin="json")
    return workspace


def edit(
    workspace: Workspace,
    new_scenario: Mapping[str, Any],
    *,
    renamed_locations: Mapping[str, str] | None = None,
) -> Workspace:
    """Replace the scenario after an edit, keeping derived results that are still valid.

    Derived results are never cleared here; they become stale through their
    fingerprints. Two edits keep the travel-time matrix current: deleting locations
    whose remaining inputs are unchanged slices the matrix, and renaming location IDs
    renames them in the matrix.
    """
    derived = workspace.derived
    old_scenario: Mapping[str, Any] = workspace.scenario
    matrix = derived.matrix
    matrix_fingerprint = derived.matrix_input_fingerprint
    was_current = matrix is not None and matrix_fingerprint == matrix_input_fingerprint(
        old_scenario
    )
    renames = dict(renamed_locations or {})
    embedded = derived.embedded_matrix
    resolutions = dict(derived.resolutions)
    if renames:
        matrix = _rename_matrix(matrix, renames)
        embedded = _rename_matrix(embedded, renames)
        old_scenario = _rename_locations(old_scenario, renames)
        resolutions = {renames.get(key, key): value for key, value in resolutions.items()}
    if matrix is not None and was_current:
        new_ids = row_ids(new_scenario, "locations")
        matrix_ids = [str(value) for value in matrix.get("location_ids", [])]
        restricted = _restrict_locations(old_scenario, new_ids)
        if set(new_ids) <= set(matrix_ids) and matrix_input_fingerprint(
            restricted
        ) == matrix_input_fingerprint(new_scenario):
            if set(new_ids) != set(matrix_ids):
                matrix = slice_matrix(matrix, new_ids)
            matrix_fingerprint = matrix_input_fingerprint(new_scenario)
    return Workspace(
        scenario=deepcopy(dict(new_scenario)),
        derived=replace(
            derived,
            matrix=matrix,
            matrix_input_fingerprint=matrix_fingerprint,
            embedded_matrix=embedded,
            resolutions=resolutions,
        ),
    )


def apply_document(
    workspace: Workspace, document: Mapping[str, Any], *, carry_derived: bool
) -> Workspace:
    """Apply JSON edited in the Advanced JSON view as an edit of the current scenario.

    ``carry_derived`` is used for the clean view, which hides derived fields: locations
    whose address did not change keep their resolution. An embedded ``routing_matrix``
    that differs from the active one, and covers exactly the locations, becomes the
    active matrix, as "Use routing matrix from payload" did in Version 1.0.
    """
    scenario, matrix = split_document(document)
    if carry_derived:
        scenario = carry_over_derived(scenario, workspace.scenario)
    updated = edit(workspace, scenario)
    if matrix is None:
        return updated
    updated = replace(updated, derived=replace(updated.derived, embedded_matrix=matrix))
    if matrix_identity(matrix) != matrix_identity(updated.derived.matrix) and (
        matrix_matches_locations(matrix, updated.scenario)
    ):
        updated = record_matrix(updated, matrix, origin="json")
    return updated


def routing_locations(scenario: Mapping[str, Any]) -> list[JsonObject]:
    """Locations in the shape ``/matrices/compute`` expects; coordinates are required."""
    result: list[JsonObject] = []
    for location in rows(scenario, "locations"):
        location_id = str(location.get("location_id", "")).strip()
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if not location_id or latitude is None or longitude is None:
            raise ValueError(
                f"Location {location_id or '(no ID)'} has no resolved coordinates yet."
            )
        result.append(
            {
                "location_id": location_id,
                "formatted_address": str(
                    location.get("formatted_address")
                    or location.get("address")
                    or location.get("name")
                    or location_id
                ).strip(),
                "latitude": latitude,
                "longitude": longitude,
                "place_id": location.get("place_id"),
            }
        )
    return result


def validation_payload(workspace: Workspace) -> JsonObject:
    """What automatic validation sends: the scenario, without a matrix."""
    return deepcopy(workspace.scenario)


def validation_payload_fingerprint(workspace: Workspace) -> str:
    return stable_fingerprint(validation_payload(workspace))


def solve_payload(workspace: Workspace) -> JsonObject:
    """What a solve sends: the scenario plus the active matrix."""
    payload = deepcopy(workspace.scenario)
    if workspace.derived.matrix is not None:
        payload["routing_matrix"] = deepcopy(workspace.derived.matrix)
    return payload


GOOGLE_MATRIX_SOURCES = frozenset({"google_routes"})
"""Matrix ``source`` values that must not be stored or downloaded (decision D6)."""


def matrix_is_storable(matrix: Mapping[str, Any] | None) -> bool:
    """Whether a matrix may leave the session; Google travel times may not (D6)."""
    return matrix is not None and str(matrix.get("source", "")) not in GOOGLE_MATRIX_SOURCES


def storable_matrix(workspace: Workspace) -> JsonObject | None:
    """The active matrix if it may be saved or downloaded, else ``None``."""
    matrix = workspace.derived.matrix
    return matrix if matrix is not None and matrix_is_storable(matrix) else None


def save_document(workspace: Workspace) -> JsonObject:
    """What "Save scenario" stores: the complete scenario, plus the active matrix if allowed.

    Decision D6: Google travel times are kept only for the session, so a scenario whose
    travel times came from Google is saved without them and recalculated after opening.
    Matrices from JSON (such as the samples) are saved as in Version 1.0.
    """
    return document_for_export(
        workspace.scenario, mode=ExportMode.COMPLETE, matrix=storable_matrix(workspace)
    )


def record_resolutions(
    workspace: Workspace,
    scenario: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    sent_addresses: Mapping[str, str],
) -> Workspace:
    """Apply an edited scenario after a resolve, remembering each result's details."""
    updated = edit(workspace, scenario)
    details = dict(updated.derived.resolutions)
    for result in results:
        location_id = str(result.get("location_id", ""))
        if location_id in sent_addresses:
            details[location_id] = {**dict(result), "address": sent_addresses[location_id]}
    return replace(updated, derived=replace(updated.derived, resolutions=details))


def record_estimate(workspace: Workspace, estimate: Mapping[str, Any]) -> Workspace:
    """Remember a matrix estimate for the current locations and routing options."""
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            matrix_estimate=deepcopy(dict(estimate)),
            matrix_estimate_fingerprint=matrix_input_fingerprint(workspace.scenario),
        ),
    )


def current_estimate(workspace: Workspace) -> JsonObject | None:
    """The remembered estimate if it was made for the current locations and options."""
    derived = workspace.derived
    if derived.matrix_estimate is None:
        return None
    if derived.matrix_estimate_fingerprint != matrix_input_fingerprint(workspace.scenario):
        return None
    return derived.matrix_estimate


def record_validation(
    workspace: Workspace,
    *,
    payload_fingerprint: str,
    validation: JsonObject,
    request_id: str | None,
) -> Workspace:
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            validation=deepcopy(validation),
            validation_fingerprint=payload_fingerprint,
            validation_request_id=request_id,
            validation_error=None,
            validation_attempt_fingerprint=payload_fingerprint,
        ),
    )


def record_validation_failure(
    workspace: Workspace, *, payload_fingerprint: str, message: str
) -> Workspace:
    """Remember a failed automatic validation so it is not retried on every rerun."""
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            validation_error=message,
            validation_attempt_fingerprint=payload_fingerprint,
        ),
    )


def record_matrix(
    workspace: Workspace,
    matrix: Mapping[str, Any],
    *,
    origin: str,
    cache_hit: bool | None = None,
) -> Workspace:
    """Make ``matrix`` the active one for the current locations and routing options."""
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            matrix=deepcopy(dict(matrix)),
            matrix_input_fingerprint=matrix_input_fingerprint(workspace.scenario),
            matrix_origin=origin,
            matrix_cache_hit=cache_hit,
        ),
    )


def activate_embedded_matrix(workspace: Workspace) -> Workspace:
    """Use the matrix that came with the imported JSON, if it covers the locations."""
    embedded = workspace.derived.embedded_matrix
    if embedded is None:
        raise ValueError("The scenario JSON did not include travel times.")
    if not matrix_matches_locations(embedded, workspace.scenario):
        raise ValueError("The travel times in the JSON do not cover exactly these locations.")
    return record_matrix(workspace, embedded, origin="json")


def record_plan(
    workspace: Workspace,
    *,
    plan: JsonObject,
    validation: JsonObject | None,
    request_id: str | None,
) -> Workspace:
    derived = replace(
        workspace.derived,
        plan=deepcopy(plan),
        plan_input_fingerprint=plan_input_fingerprint(workspace.scenario, workspace.derived.matrix),
        plan_request_id=request_id,
    )
    updated = replace(workspace, derived=derived)
    if validation is not None:
        updated = record_validation(
            updated,
            payload_fingerprint=validation_payload_fingerprint(updated),
            validation=validation,
            request_id=request_id,
        )
    return updated


def mark_saved(workspace: Workspace, *, source: str | None = None) -> Workspace:
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            baseline_fingerprint=saved_fingerprint(workspace.scenario),
            loaded_from=source or workspace.derived.loaded_from,
        ),
    )


def has_unsaved_edits(workspace: Workspace) -> bool:
    """Whether the scenario changed since it was last loaded or saved."""
    return workspace.derived.baseline_fingerprint != saved_fingerprint(workspace.scenario)


def matrix_matches_locations(matrix: Mapping[str, Any], scenario: Mapping[str, Any]) -> bool:
    location_ids = matrix.get("location_ids")
    if not isinstance(location_ids, list):
        return False
    return bool(location_ids) and set(map(str, location_ids)) == set(row_ids(scenario, "locations"))


def slice_matrix(matrix: Mapping[str, Any], keep_ids: Sequence[str]) -> JsonObject:
    """The sub-matrix for ``keep_ids``, in the matrix's own order; no provider call."""
    location_ids = [str(value) for value in matrix.get("location_ids", [])]
    keep = set(keep_ids)
    indexes = [index for index, location_id in enumerate(location_ids) if location_id in keep]
    sliced = deepcopy(dict(matrix))
    sliced["location_ids"] = [location_ids[index] for index in indexes]
    for key in ("distance_meters", "duration_seconds"):
        values = matrix.get(key)
        if isinstance(values, list):
            sliced[key] = [[values[row][column] for column in indexes] for row in indexes]
    issues = matrix.get("element_issues")
    if isinstance(issues, list):
        sliced["element_issues"] = [
            issue
            for issue in issues
            if isinstance(issue, dict)
            and issue.get("origin_location_id") in keep
            and issue.get("destination_location_id") in keep
        ]
    return sliced


def validation_issue_rows(validation: Mapping[str, Any] | None) -> list[JsonObject]:
    """Backend validation issues as table rows."""
    if not validation:
        return []
    issues = validation.get("issues", ())
    if not isinstance(issues, list):
        return []
    return [
        {
            "severity": issue.get("severity"),
            "code": issue.get("code"),
            "row_number": issue.get("row_number"),
            "field": issue.get("field"),
            "task_id": issue.get("task_id"),
            "message": issue.get("message"),
            "section": issue.get("section"),
            "item_id": issue.get("item_id"),
        }
        for issue in issues
        if isinstance(issue, dict)
    ]


def _rename_matrix(
    matrix: Mapping[str, Any] | None, renames: Mapping[str, str]
) -> JsonObject | None:
    if matrix is None:
        return None
    renamed = deepcopy(dict(matrix))
    location_ids = renamed.get("location_ids")
    if isinstance(location_ids, list):
        renamed["location_ids"] = [renames.get(str(value), value) for value in location_ids]
    issues = renamed.get("element_issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                for key in ("origin_location_id", "destination_location_id"):
                    if issue.get(key) in renames:
                        issue[key] = renames[str(issue[key])]
    return renamed


def _rename_locations(scenario: Mapping[str, Any], renames: Mapping[str, str]) -> Scenario:
    renamed = deepcopy(dict(scenario))
    locations = rows(renamed, "locations")
    for location in locations:
        old_id = str(location.get("location_id"))
        if old_id in renames:
            location["location_id"] = renames[old_id]
    renamed["locations"] = locations
    return renamed


def _restrict_locations(scenario: Mapping[str, Any], keep_ids: Sequence[str]) -> Scenario:
    keep = set(keep_ids)
    restricted = deepcopy(dict(scenario))
    restricted["locations"] = [
        location
        for location in rows(restricted, "locations")
        if str(location.get("location_id")) in keep
    ]
    return restricted
