"""JSON round-trip coverage for public M2 request and result contracts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.app.domain import (
    PlanResult,
    PlanRoute,
    PlanStatus,
    PlanStop,
    StopKind,
    TaskDiagnostic,
    ValidationCode,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    validate_planning_payload,
)
from backend.tests.fixtures.canonical import planning_payload


def assert_json_round_trip(model: object) -> None:
    model_type = type(model)
    restored = model_type.model_validate_json(model.model_dump_json())  # type: ignore[attr-defined]
    assert restored == model


def test_request_and_nested_input_contracts_round_trip() -> None:
    validation = validate_planning_payload(planning_payload("A"))
    assert validation.normalized_request is not None
    request = validation.normalized_request

    for model in (
        request.locations[0],
        request.vehicles[0],
        request.vehicle_shifts[0],
        request.tasks[0],
        request.routing_matrix,
        request.horizon,
        request,
        validation,
    ):
        assert model is not None
        assert_json_round_trip(model)


def test_validation_issue_and_invalid_result_round_trip() -> None:
    issue = ValidationIssue(
        severity=ValidationSeverity.ERROR,
        code=ValidationCode.INVALID_VALUE,
        message="Example error",
        row_number=2,
        field="quantity",
        task_id="TASK-1",
    )
    result = ValidationResult(valid=False, issues=(issue,))

    assert_json_round_trip(issue)
    assert_json_round_trip(result)


def test_plan_result_contracts_round_trip() -> None:
    arrival = datetime(2026, 6, 22, 13, tzinfo=UTC)
    stop = PlanStop(
        sequence=0,
        node_id="TASK-1::pickup",
        kind=StopKind.PICKUP,
        location_id="SUPPLIER_A",
        task_id="TASK-1",
        arrival_at=arrival,
        service_start_at=arrival,
        departure_at=arrival + timedelta(minutes=15),
        load_after=Decimal("4.5"),
        distance_from_previous_meters=28_000,
        duration_from_previous_seconds=1_800,
        due_at=arrival + timedelta(hours=2),
        slack_seconds=6_300,
    )
    route = PlanRoute(
        vehicle_id="TRUCK-1",
        shift_id="TRUCK-1-20260622",
        stops=(stop,),
        total_distance_meters=28_000,
        driving_seconds=1_800,
        service_seconds=900,
        waiting_seconds=0,
        peak_load=Decimal("4.5"),
    )
    diagnostic = TaskDiagnostic(
        task_id="TASK-2",
        po_number="PO-2",
        code="CAPACITY_EXCEEDED",
        message="Quantity exceeds capacity.",
        due_at=arrival,
    )
    result = PlanResult(
        plan_id="PLAN-1",
        status=PlanStatus.PARTIALLY_FEASIBLE,
        routes=(route,),
        diagnostics=(diagnostic,),
        scheduled_task_ids=("TASK-1",),
        unscheduled_task_ids=("TASK-2",),
        total_distance_meters=28_000,
        total_driving_seconds=1_800,
        total_service_seconds=900,
        solver_elapsed_seconds=0.25,
    )

    for model in (stop, route, diagnostic, result):
        assert_json_round_trip(model)
