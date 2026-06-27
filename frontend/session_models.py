"""Frontend-only workflow state and invalidation helpers.

Business-domain behavior remains in backend contracts. These helpers track only
frontend freshness so stale matrices/plans are not presented after edits.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FrontendSessionState:
    """Connectivity and workflow freshness state stored in Streamlit session."""

    backend_connected: bool = False


JsonPayload = dict[str, Any]


@dataclass(frozen=True, slots=True)
class WorkflowFingerprints:
    """Stable hashes for the pieces of state that invalidate downstream results."""

    validation_fingerprint: str
    location_fingerprint: str
    task_fingerprint: str
    matrix_fingerprint: str | None = None
    plan_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    """Derived UI enablement and staleness status."""

    validation_is_current: bool
    matrix_is_current: bool
    plan_is_current: bool
    can_compute_matrix: bool
    can_solve: bool
    stale_plan_hidden: bool


def stable_fingerprint(value: Any) -> str:
    """Return a deterministic short hash for JSON-like values."""
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def location_fingerprint(payload: JsonPayload) -> str:
    """Hash address/location content that affects geocoding and matrices."""
    return stable_fingerprint(
        {
            "plant_location_id": payload.get("plant_location_id"),
            "locations": payload.get("locations", ()),
            "routing_options": payload.get("routing_options", {}),
        }
    )


def task_fingerprint(payload: JsonPayload) -> str:
    """Hash fleet, shifts, tasks, horizon, and due dates that affect a plan."""
    return stable_fingerprint(
        {
            "scenario_id": payload.get("scenario_id"),
            "timezone": payload.get("timezone"),
            "planning_horizon": payload.get("planning_horizon", payload.get("horizon")),
            "plant_location_id": payload.get("plant_location_id"),
            "vehicles": payload.get("vehicles", ()),
            "vehicle_shifts": payload.get("vehicle_shifts", ()),
            "tasks": payload.get("tasks", ()),
        }
    )


def validation_fingerprint(payload: JsonPayload) -> str:
    """Hash editable planning inputs that require a fresh validation pass."""
    return stable_fingerprint(
        {
            "location_fingerprint": location_fingerprint(payload),
            "task_fingerprint": task_fingerprint(payload),
        }
    )


def payload_fingerprints(payload: JsonPayload) -> WorkflowFingerprints:
    """Return current payload fingerprints before matrix/plan results are attached."""
    return WorkflowFingerprints(
        validation_fingerprint=validation_fingerprint(payload),
        location_fingerprint=location_fingerprint(payload),
        task_fingerprint=task_fingerprint(payload),
    )


def workflow_status(
    payload: JsonPayload,
    *,
    validation_valid: bool,
    validation_source_fingerprint: str | None,
    matrix_payload: JsonPayload | None,
    matrix_source_location_fingerprint: str | None,
    plan_payload: JsonPayload | None,
    plan_source_task_fingerprint: str | None,
) -> WorkflowStatus:
    """Calculate frontend freshness and action enablement flags."""
    current_locations = location_fingerprint(payload)
    current_tasks = task_fingerprint(payload)
    validation_is_current = (
        validation_valid and validation_source_fingerprint == validation_fingerprint(payload)
    )
    matrix_is_current = (
        matrix_payload is not None and matrix_source_location_fingerprint == current_locations
    )
    plan_is_current = (
        plan_payload is not None
        and plan_source_task_fingerprint == current_tasks
        and matrix_is_current
    )
    return WorkflowStatus(
        validation_is_current=validation_is_current,
        matrix_is_current=matrix_is_current,
        plan_is_current=plan_is_current,
        can_compute_matrix=validation_is_current and bool(payload.get("locations")),
        can_solve=validation_is_current and matrix_is_current,
        stale_plan_hidden=plan_payload is not None and not plan_is_current,
    )


def attach_matrix_to_payload(payload: JsonPayload, matrix: JsonPayload | None) -> JsonPayload:
    """Return a copy of a planning payload with the current matrix inserted or removed."""
    updated = dict(payload)
    if matrix is None:
        updated.pop("routing_matrix", None)
    else:
        updated["routing_matrix"] = matrix
    return updated


def validation_issue_rows(validation_payload: JsonPayload | None) -> list[dict[str, Any]]:
    """Convert backend validation issues into rows for Streamlit display."""
    if not validation_payload:
        return []
    issues = validation_payload.get("issues", ())
    if not isinstance(issues, list):
        return []
    rows: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        rows.append(
            {
                "severity": issue.get("severity"),
                "code": issue.get("code"),
                "row_number": issue.get("row_number"),
                "field": issue.get("field"),
                "task_id": issue.get("task_id"),
                "message": issue.get("message"),
            }
        )
    return rows
