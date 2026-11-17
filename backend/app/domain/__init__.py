"""Business-domain contracts and validation rules."""

from backend.app.domain.enums import (
    DueEvent,
    GeocodeLocationType,
    GeocodeReasonCode,
    GeocodeStatus,
    PlanStatus,
    RoutingPreference,
    StopKind,
    TaskType,
    TravelMode,
    ValidationCode,
    ValidationSeverity,
)
from backend.app.domain.models import (
    Location,
    MatrixElementIssue,
    PlanningHorizon,
    PlanningRequest,
    RoutingMatrix,
    Task,
    Vehicle,
    VehicleShift,
)
from backend.app.domain.results import (
    PlanResult,
    PlanRoute,
    PlanStop,
    TaskDiagnostic,
    ValidationIssue,
    ValidationResult,
)
from backend.app.domain.validation import (
    normalized_payload_for_display,
    validate_planning_payload,
)

__all__ = [
    "DueEvent",
    "GeocodeLocationType",
    "GeocodeReasonCode",
    "GeocodeStatus",
    "Location",
    "MatrixElementIssue",
    "PlanResult",
    "PlanRoute",
    "PlanStatus",
    "PlanStop",
    "PlanningHorizon",
    "PlanningRequest",
    "RoutingMatrix",
    "RoutingPreference",
    "StopKind",
    "Task",
    "TaskDiagnostic",
    "TaskType",
    "TravelMode",
    "ValidationCode",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "Vehicle",
    "VehicleShift",
    "normalized_payload_for_display",
    "validate_planning_payload",
]
