"""Canonical payload and row-level validation tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC
from decimal import Decimal

import pytest

from backend.app.domain import (
    TaskType,
    ValidationCode,
    ValidationSeverity,
    normalized_payload_for_display,
    validate_planning_payload,
)
from backend.tests.fixtures.canonical import planning_payload


def error_codes(result: object) -> set[ValidationCode]:
    return {
        issue.code
        for issue in result.issues  # type: ignore[attr-defined]
        if issue.severity is ValidationSeverity.ERROR
    }


def test_scenario_a_normalizes_all_three_task_types() -> None:
    result = validate_planning_payload(planning_payload("A"))

    assert result.valid
    assert result.normalized_request is not None
    assert {task.task_type for task in result.normalized_request.tasks} == {
        TaskType.PICKUP,
        TaskType.DROP,
        TaskType.PICKUP_DROP,
    }
    assert all(task.quantity > 0 for task in result.normalized_request.tasks)
    assert all(task.ready_at.tzinfo is UTC for task in result.normalized_request.tasks)
    assert all(task.due_at.tzinfo is UTC for task in result.normalized_request.tasks)


def test_normalized_payload_is_business_readable_in_local_and_utc_time() -> None:
    result = validate_planning_payload(planning_payload("A"))

    display = normalized_payload_for_display(result)

    assert display is not None
    first_task = display["tasks"][0]
    assert first_task["due_event"] == "DELIVERY_COMPLETE"
    assert first_task["due_at_local"].endswith("-04:00")
    assert first_task["due_at_utc"].endswith("+00:00")
    assert first_task["quantity"] == "4"


def test_scenario_b_reports_capacity_error_on_task_row() -> None:
    result = validate_planning_payload(planning_payload("B"))

    assert not result.valid
    issue = next(issue for issue in result.issues if issue.code is ValidationCode.CAPACITY_EXCEEDED)
    assert issue.row_number == 2
    assert issue.field == "quantity"
    assert issue.task_id == "TASK-CAPACITY-001"


def test_missing_location_address_is_row_level_error() -> None:
    payload = planning_payload("A")
    del payload["locations"][1]["address"]

    result = validate_planning_payload(payload)

    assert not result.valid
    issue = next(
        issue for issue in result.issues if issue.code is ValidationCode.MISSING_REQUIRED_FIELD
    )
    assert issue.row_number == 3
    assert issue.field == "locations.address"


def test_task_type_location_mismatch_is_specific_error() -> None:
    payload = planning_payload("A")
    payload["tasks"][0]["destination_location_id"] = "CUSTOMER_A"

    result = validate_planning_payload(payload)

    assert not result.valid
    assert ValidationCode.TASK_TYPE_LOCATION_MISMATCH in error_codes(result)


def test_duplicate_task_id_is_error_with_source_row() -> None:
    payload = planning_payload("A")
    payload["tasks"][1]["task_id"] = payload["tasks"][0]["task_id"]

    result = validate_planning_payload(payload)

    issue = next(issue for issue in result.issues if issue.code is ValidationCode.DUPLICATE_TASK_ID)
    assert not result.valid
    assert issue.row_number == 3
    assert "row 2" in issue.message


def test_duplicate_po_is_allowed_with_warning() -> None:
    payload = planning_payload("A")
    payload["tasks"][1]["po_number"] = payload["tasks"][0]["po_number"]

    result = validate_planning_payload(payload)

    warning = next(
        issue for issue in result.issues if issue.code is ValidationCode.DUPLICATE_PO_NUMBER
    )
    assert result.valid
    assert warning.severity is ValidationSeverity.WARNING
    assert warning.row_number == 3


@pytest.mark.parametrize("quantity", [0, -1, "-0.001"])
def test_nonpositive_quantity_is_rejected(quantity: object) -> None:
    payload = planning_payload("A")
    payload["tasks"][0]["quantity"] = quantity

    result = validate_planning_payload(payload)

    assert not result.valid
    assert any(issue.field == "task.quantity" for issue in result.issues)


def test_ready_after_due_has_stable_error_code() -> None:
    payload = planning_payload("A")
    payload["tasks"][0]["ready_at"] = "2026-06-22T13:00:00-04:00"
    payload["tasks"][0]["due_at"] = "2026-06-22T12:00:00-04:00"

    result = validate_planning_payload(payload)

    assert not result.valid
    assert ValidationCode.READY_AFTER_DUE in error_codes(result)


def test_date_only_ready_and_due_use_shift_boundaries() -> None:
    payload = planning_payload("A")
    payload["tasks"] = [deepcopy(payload["tasks"][0])]
    payload["tasks"][0]["ready_at"] = "2026-06-22"
    payload["tasks"][0]["due_at"] = "2026-06-22"

    result = validate_planning_payload(payload)

    assert result.valid
    assert result.normalized_request is not None
    task = result.normalized_request.tasks[0]
    assert task.ready_at.isoformat() == "2026-06-22T11:00:00+00:00"
    assert task.due_at.isoformat() == "2026-06-22T21:00:00+00:00"
    assert {
        ValidationCode.DATE_ONLY_READY_NORMALIZED,
        ValidationCode.DATE_ONLY_DEADLINE_NORMALIZED,
    } <= {issue.code for issue in result.issues}


def test_fractional_quantity_policy_accepts_three_places() -> None:
    payload = planning_payload("A")
    payload["tasks"][0]["quantity"] = "4.125"
    payload["vehicles"][0]["capacity"] = "12.500"

    result = validate_planning_payload(payload)

    assert result.valid
    assert result.normalized_request is not None
    assert result.normalized_request.tasks[0].quantity == Decimal("4.125")


def test_fractional_quantity_policy_rejects_more_than_three_places() -> None:
    payload = planning_payload("A")
    payload["tasks"][0]["quantity"] = "4.1259"

    result = validate_planning_payload(payload)

    assert not result.valid
    assert any("three decimal places" in issue.message for issue in result.issues)
