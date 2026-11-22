"""Pydantic contracts returned by validation and planning services."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import Field, field_validator, model_validator

from backend.app.domain.enums import (
    IssueSection,
    PlanStatus,
    RoutingPreference,
    StopKind,
    ValidationCode,
    ValidationSeverity,
)
from backend.app.domain.models import DomainModel, Identifier, PlanningRequest, ensure_aware_utc
from backend.app.domain.options import OptimizationOptions


class ValidationIssue(DomainModel):
    """A stable validation message optionally tied to one imported row and field.

    ``section`` and ``item_id`` (added in V1.1-M4) say which part of the scenario and
    which row the issue is about, so the app can group issues and link to the row.
    """

    severity: ValidationSeverity
    code: ValidationCode
    message: str = Field(min_length=1)
    row_number: int | None = Field(default=None, ge=1)
    field: str | None = None
    task_id: str | None = None
    section: IssueSection | None = None
    item_id: str | None = None


class ValidationResult(DomainModel):
    """Result of normalizing and validating an input payload."""

    valid: bool
    normalized_request: PlanningRequest | None = None
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        has_errors = any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)
        if self.valid == has_errors:
            raise ValueError("valid must be false exactly when error issues are present")
        if self.valid and self.normalized_request is None:
            raise ValueError("valid result requires a normalized request")
        if not self.valid and self.normalized_request is not None:
            raise ValueError("invalid result cannot contain a normalized request")
        return self


class PlanStop(DomainModel):
    """One validated stop in an optimized vehicle route."""

    sequence: int = Field(ge=0)
    node_id: Identifier
    kind: StopKind
    location_id: Identifier
    task_id: Identifier | None = None
    arrival_at: datetime
    service_start_at: datetime
    departure_at: datetime
    load_after: Decimal = Field(ge=0)
    distance_from_previous_meters: int = Field(ge=0)
    duration_from_previous_seconds: int = Field(ge=0)
    due_at: datetime | None = None
    slack_seconds: int | None = None

    @field_validator("arrival_at", "service_start_at", "departure_at", "due_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_stop_timeline(self) -> Self:
        if not (self.arrival_at <= self.service_start_at <= self.departure_at):
            raise ValueError("stop timeline must be arrival <= service start <= departure")
        return self


class PlanRoute(DomainModel):
    """Ordered route assigned to one vehicle shift."""

    vehicle_id: Identifier
    shift_id: Identifier
    stops: tuple[PlanStop, ...]
    total_distance_meters: int = Field(ge=0)
    driving_seconds: int = Field(ge=0)
    service_seconds: int = Field(ge=0)
    waiting_seconds: int = Field(ge=0)
    peak_load: Decimal = Field(ge=0)
    total_duration_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Shift start to arrival at the end depot, waiting included (V1.1-M5).",
    )


class TaskDiagnostic(DomainModel):
    """Reason a task is invalid, late, or unscheduled."""

    task_id: Identifier
    po_number: str
    code: str
    message: str
    due_at: datetime | None = None
    estimated_completion_at: datetime | None = None
    late_by_seconds: int | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=1, le=5)

    @field_validator("due_at", "estimated_completion_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None


class MatrixIdentity(DomainModel):
    """Which travel times a plan was solved with (V1.1-M5)."""

    source: str
    routing_preference: RoutingPreference
    created_at: datetime | None = None
    location_count: int = Field(ge=0)
    travel_time_factor: float = Field(default=1.0, ge=1.0, le=2.0)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None


class PlanMetrics(DomainModel):
    """Figures for comparing plans (V1.1-M5).

    Route durations run from the shift start to the arrival at the end depot, waiting
    included; working time is driving plus service, which ``BALANCE_WORKLOAD`` evens
    out. Utilisations are averages over the truck-shifts used: peak load over
    capacity, and route duration over the time the route was allowed.
    """

    truck_shifts_used: int = Field(ge=0)
    truck_shifts_available: int = Field(ge=0)
    longest_route_seconds: int = Field(default=0, ge=0)
    shortest_route_seconds: int = Field(default=0, ge=0)
    longest_working_seconds: int = Field(
        default=0, ge=0, description="Driving plus service on the busiest route."
    )
    load_utilisation: float = Field(default=0, ge=0)
    time_utilisation: float = Field(default=0, ge=0)
    objective_value: int | None = None


class PlanResult(DomainModel):
    """Public planning result contract independent of solver implementation.

    The optional fields added in V1.1-M5 (``created_at``, ``optimization_options``,
    ``matrix``, ``metrics``) and V1.1-M6 (``input_fingerprint``) are absent from plans
    stored by Version 1.0, which stay readable.
    """

    plan_id: Identifier
    status: PlanStatus
    routes: tuple[PlanRoute, ...] = ()
    diagnostics: tuple[TaskDiagnostic, ...] = ()
    scheduled_task_ids: tuple[Identifier, ...] = ()
    unscheduled_task_ids: tuple[Identifier, ...] = ()
    total_distance_meters: int = Field(default=0, ge=0)
    total_driving_seconds: int = Field(default=0, ge=0)
    total_service_seconds: int = Field(default=0, ge=0)
    total_waiting_seconds: int = Field(default=0, ge=0)
    solver_elapsed_seconds: float = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()
    created_at: datetime | None = None
    optimization_options: OptimizationOptions | None = None
    matrix: MatrixIdentity | None = None
    metrics: PlanMetrics | None = None
    input_fingerprint: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Fingerprint of what was planned, settings excluded (V1.1-M6): two plans with "
            "the same value were made from the same POs, fleet, and travel times, so "
            "comparing them shows only the effect of the settings."
        ),
    )

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None
