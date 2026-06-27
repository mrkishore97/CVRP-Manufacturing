"""Versioned planning validation, solve, retrieval, and export endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, status

from backend.app.api.contracts import (
    ApiErrorDetail,
    ApiRequestError,
    JsonObject,
    PlanExportResponse,
    PlanResponse,
    PlanSolveResponse,
    PlanValidationResponse,
)
from backend.app.api.dependencies import (
    PlanningServiceDependency,
    PlanRepositoryDependency,
    RequestIdDependency,
    SettingsDependency,
)
from backend.app.config import Settings
from backend.app.domain import ValidationResult, validate_planning_payload
from backend.app.domain.results import PlanResult, ValidationIssue

router = APIRouter(tags=["plans"])
PAYLOAD_BODY = Body(...)


def _issue_detail(issue: ValidationIssue) -> ApiErrorDetail:
    return ApiErrorDetail(
        code=issue.code.value,
        message=issue.message,
        field=issue.field,
        row_number=issue.row_number,
        task_id=issue.task_id,
    )


def _enforce_planning_payload_limits(payload: JsonObject, settings: Settings) -> None:
    locations = payload.get("locations")
    tasks = payload.get("tasks")
    if isinstance(locations, list) and len(locations) > settings.api_max_locations:
        raise ApiRequestError(
            status_code=413,
            code="LOCATION_LIMIT_EXCEEDED",
            message=f"Payload contains more than {settings.api_max_locations} locations.",
        )
    if isinstance(tasks, list) and len(tasks) > settings.api_max_tasks:
        raise ApiRequestError(
            status_code=413,
            code="TASK_LIMIT_EXCEEDED",
            message=f"Payload contains more than {settings.api_max_tasks} tasks.",
        )


def _validate_payload_or_raise(
    payload: JsonObject,
    validation: ValidationResult,
) -> None:
    if validation.valid:
        return
    raise ApiRequestError(
        status_code=422,
        code="PLANNING_VALIDATION_FAILED",
        message="Planning payload did not pass domain validation.",
        details=tuple(_issue_detail(issue) for issue in validation.issues),
    )


def _export_route_rows(plan: PlanResult) -> tuple[JsonObject, ...]:
    rows: list[dict[str, Any]] = []
    for route in plan.routes:
        for stop in route.stops:
            rows.append(
                {
                    "plan_id": plan.plan_id,
                    "vehicle_id": route.vehicle_id,
                    "shift_id": route.shift_id,
                    "sequence": stop.sequence,
                    "node_id": stop.node_id,
                    "kind": stop.kind.value,
                    "location_id": stop.location_id,
                    "task_id": stop.task_id,
                    "arrival_at": stop.arrival_at.isoformat(),
                    "service_start_at": stop.service_start_at.isoformat(),
                    "departure_at": stop.departure_at.isoformat(),
                    "load_after": str(stop.load_after),
                    "distance_from_previous_meters": stop.distance_from_previous_meters,
                    "duration_from_previous_seconds": stop.duration_from_previous_seconds,
                    "due_at": stop.due_at.isoformat() if stop.due_at else None,
                    "slack_seconds": stop.slack_seconds,
                }
            )
    return tuple(rows)


def _export_diagnostic_rows(plan: PlanResult) -> tuple[JsonObject, ...]:
    return tuple(
        {
            "plan_id": plan.plan_id,
            "task_id": diagnostic.task_id,
            "po_number": diagnostic.po_number,
            "code": diagnostic.code,
            "message": diagnostic.message,
            "due_at": diagnostic.due_at.isoformat() if diagnostic.due_at else None,
            "estimated_completion_at": (
                diagnostic.estimated_completion_at.isoformat()
                if diagnostic.estimated_completion_at
                else None
            ),
            "late_by_seconds": diagnostic.late_by_seconds,
        }
        for diagnostic in plan.diagnostics
    )


@router.post(
    "/plans/validate",
    response_model=PlanValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_plan_payload(
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    payload: JsonObject = PAYLOAD_BODY,
) -> PlanValidationResponse:
    """Normalize and validate a planning payload without solving it."""
    _enforce_planning_payload_limits(payload, settings)
    return PlanValidationResponse(
        request_id=request_id,
        validation=validate_planning_payload(payload),
    )


@router.post(
    "/plans/solve",
    response_model=PlanSolveResponse,
    status_code=status.HTTP_200_OK,
)
async def solve_plan(
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    planning_service: PlanningServiceDependency,
    plan_repository: PlanRepositoryDependency,
    payload: JsonObject = PAYLOAD_BODY,
) -> PlanSolveResponse:
    """Validate, solve, persist, and return a plan for a planning payload."""
    _enforce_planning_payload_limits(payload, settings)
    validation = validate_planning_payload(payload)
    _validate_payload_or_raise(payload, validation)
    if validation.normalized_request is None:
        raise ApiRequestError(
            status_code=422,
            code="PLANNING_VALIDATION_FAILED",
            message="Planning payload did not produce a normalized request.",
        )
    plan = planning_service.optimize(validation.normalized_request)
    plan_repository.save(validation.normalized_request.scenario_id, plan)
    return PlanSolveResponse(request_id=request_id, validation=validation, plan=plan)


@router.get(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
)
async def get_plan(
    plan_id: str,
    request_id: RequestIdDependency,
    plan_repository: PlanRepositoryDependency,
) -> PlanResponse:
    """Retrieve a previously solved plan."""
    persisted = plan_repository.get(plan_id)
    if persisted is None:
        raise ApiRequestError(
            status_code=404,
            code="PLAN_NOT_FOUND",
            message=f"Plan does not exist: {plan_id}",
        )
    return PlanResponse(
        request_id=request_id,
        plan=persisted.plan,
        scenario_id=persisted.scenario_id,
        created_at=persisted.created_at,
    )


@router.get(
    "/plans/{plan_id}/export",
    response_model=PlanExportResponse,
    status_code=status.HTTP_200_OK,
)
async def export_plan(
    plan_id: str,
    request_id: RequestIdDependency,
    plan_repository: PlanRepositoryDependency,
) -> PlanExportResponse:
    """Return route and diagnostic rows suitable for later CSV/XLSX export work."""
    persisted = plan_repository.get(plan_id)
    if persisted is None:
        raise ApiRequestError(
            status_code=404,
            code="PLAN_NOT_FOUND",
            message=f"Plan does not exist: {plan_id}",
        )
    return PlanExportResponse(
        request_id=request_id,
        plan_id=plan_id,
        route_rows=_export_route_rows(persisted.plan),
        diagnostic_rows=_export_diagnostic_rows(persisted.plan),
    )
