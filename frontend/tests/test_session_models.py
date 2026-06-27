"""Frontend workflow freshness and invalidation tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from frontend.session_models import (
    attach_matrix_to_payload,
    location_fingerprint,
    task_fingerprint,
    validation_fingerprint,
    validation_issue_rows,
    workflow_status,
)


def _payload() -> dict[str, Any]:
    return {
        "scenario_id": "M7",
        "timezone": "America/Toronto",
        "planning_horizon": {
            "start": "2026-06-22T07:00:00-04:00",
            "end": "2026-06-22T17:00:00-04:00",
        },
        "plant_location_id": "PLANT",
        "locations": [
            {"location_id": "PLANT", "address": "100 Plant Road", "latitude": 43.7},
            {
                "location_id": "SUPPLIER_A",
                "address": "200 Supplier Ave",
                "latitude": 43.8,
            },
        ],
        "vehicles": [{"vehicle_id": "TRUCK-1", "capacity": 10, "enabled": True}],
        "vehicle_shifts": [
            {
                "shift_id": "SHIFT-1",
                "vehicle_id": "TRUCK-1",
                "start": "2026-06-22T07:00:00-04:00",
                "end": "2026-06-22T17:00:00-04:00",
            }
        ],
        "tasks": [
            {
                "task_id": "TASK-1",
                "po_number": "PO-1",
                "task_type": "PICKUP",
                "origin_location_id": "SUPPLIER_A",
                "destination_location_id": "PLANT",
                "quantity": 4,
                "ready_at": "2026-06-22T07:00:00-04:00",
                "due_at": "2026-06-22T12:00:00-04:00",
            }
        ],
    }


def _matrix() -> dict[str, Any]:
    return {
        "location_ids": ["PLANT", "SUPPLIER_A"],
        "distance_meters": [[0, 10], [10, 0]],
        "duration_seconds": [[0, 60], [60, 0]],
        "source": "test",
    }


def test_editing_location_invalidates_validation_matrix_and_plan() -> None:
    payload = _payload()
    edited = deepcopy(payload)
    edited["locations"][1]["address"] = "201 Supplier Ave"

    status = workflow_status(
        edited,
        validation_valid=True,
        validation_source_fingerprint=validation_fingerprint(payload),
        matrix_payload=_matrix(),
        matrix_source_location_fingerprint=location_fingerprint(payload),
        plan_payload={"status": "FEASIBLE"},
        plan_source_task_fingerprint=task_fingerprint(payload),
    )

    assert not status.validation_is_current
    assert not status.matrix_is_current
    assert not status.plan_is_current
    assert status.stale_plan_hidden
    assert not status.can_solve


def test_editing_deadline_invalidates_plan_but_not_address_identical_matrix() -> None:
    payload = _payload()
    edited = deepcopy(payload)
    edited["tasks"][0]["due_at"] = "2026-06-22T13:00:00-04:00"

    status = workflow_status(
        edited,
        validation_valid=True,
        validation_source_fingerprint=validation_fingerprint(payload),
        matrix_payload=_matrix(),
        matrix_source_location_fingerprint=location_fingerprint(payload),
        plan_payload={"status": "FEASIBLE"},
        plan_source_task_fingerprint=task_fingerprint(payload),
    )

    assert not status.validation_is_current
    assert status.matrix_is_current
    assert not status.plan_is_current
    assert status.stale_plan_hidden


def test_solve_requires_current_validation_and_matrix() -> None:
    payload = _payload()

    unvalidated = workflow_status(
        payload,
        validation_valid=False,
        validation_source_fingerprint=None,
        matrix_payload=None,
        matrix_source_location_fingerprint=None,
        plan_payload=None,
        plan_source_task_fingerprint=None,
    )
    assert not unvalidated.can_compute_matrix
    assert not unvalidated.can_solve

    validated = workflow_status(
        payload,
        validation_valid=True,
        validation_source_fingerprint=validation_fingerprint(payload),
        matrix_payload=None,
        matrix_source_location_fingerprint=None,
        plan_payload=None,
        plan_source_task_fingerprint=None,
    )
    assert validated.can_compute_matrix
    assert not validated.can_solve

    matrix_ready = workflow_status(
        payload,
        validation_valid=True,
        validation_source_fingerprint=validation_fingerprint(payload),
        matrix_payload=_matrix(),
        matrix_source_location_fingerprint=location_fingerprint(payload),
        plan_payload=None,
        plan_source_task_fingerprint=None,
    )
    assert matrix_ready.can_solve


def test_attach_matrix_and_validation_issue_rows() -> None:
    payload = _payload()
    updated = attach_matrix_to_payload(payload, _matrix())

    assert updated is not payload
    assert updated["routing_matrix"]["source"] == "test"
    assert "routing_matrix" not in payload

    rows = validation_issue_rows(
        {
            "issues": [
                {
                    "severity": "error",
                    "code": "INVALID_VALUE",
                    "row_number": 2,
                    "field": "tasks.due_at",
                    "task_id": "TASK-1",
                    "message": "Due date is before ready time.",
                }
            ]
        }
    )
    assert rows == [
        {
            "severity": "error",
            "code": "INVALID_VALUE",
            "row_number": 2,
            "field": "tasks.due_at",
            "task_id": "TASK-1",
            "message": "Due date is before ready time.",
        }
    ]
