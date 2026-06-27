"""Stable enumerations shared by domain request and result contracts."""

from enum import StrEnum


class TaskType(StrEnum):
    """Business movement represented by one task row."""

    PICKUP = "PICKUP"
    DROP = "DROP"
    PICKUP_DROP = "PICKUP_DROP"


class DueEvent(StrEnum):
    """Task event that must be completed by the hard due datetime."""

    PICKUP_COMPLETE = "PICKUP_COMPLETE"
    DELIVERY_COMPLETE = "DELIVERY_COMPLETE"


class GeocodeStatus(StrEnum):
    """Address-resolution state for a location."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class TravelMode(StrEnum):
    """Supported provider-neutral travel modes."""

    DRIVE = "DRIVE"


class RoutingPreference(StrEnum):
    """Provider-neutral route-duration preference."""

    TRAFFIC_UNAWARE = "TRAFFIC_UNAWARE"
    TRAFFIC_AWARE = "TRAFFIC_AWARE"
    TRAFFIC_AWARE_OPTIMAL = "TRAFFIC_AWARE_OPTIMAL"


class PlanStatus(StrEnum):
    """Overall outcome returned by planning services."""

    FEASIBLE = "FEASIBLE"
    PARTIALLY_FEASIBLE = "PARTIALLY_FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    INVALID_INPUT = "INVALID_INPUT"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class StopKind(StrEnum):
    """Operational meaning of an internal route node."""

    DEPOT_START = "DEPOT_START"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"
    DEPOT_END = "DEPOT_END"


class ValidationSeverity(StrEnum):
    """Whether a validation issue blocks planning."""

    ERROR = "ERROR"
    WARNING = "WARNING"


class ValidationCode(StrEnum):
    """Stable row/field validation codes used by API and frontend layers."""

    INVALID_VALUE = "INVALID_VALUE"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
    DUPLICATE_COLUMN = "DUPLICATE_COLUMN"
    DUPLICATE_LOCATION_ID = "DUPLICATE_LOCATION_ID"
    DUPLICATE_VEHICLE_ID = "DUPLICATE_VEHICLE_ID"
    DUPLICATE_SHIFT_ID = "DUPLICATE_SHIFT_ID"
    DUPLICATE_TASK_ID = "DUPLICATE_TASK_ID"
    DUPLICATE_PO_NUMBER = "DUPLICATE_PO_NUMBER"
    UNKNOWN_LOCATION = "UNKNOWN_LOCATION"
    UNKNOWN_VEHICLE = "UNKNOWN_VEHICLE"
    TASK_TYPE_LOCATION_MISMATCH = "TASK_TYPE_LOCATION_MISMATCH"
    READY_AFTER_DUE = "READY_AFTER_DUE"
    OUTSIDE_PLANNING_HORIZON = "OUTSIDE_PLANNING_HORIZON"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
    INVALID_TIMEZONE = "INVALID_TIMEZONE"
    INVALID_DATETIME = "INVALID_DATETIME"
    AMBIGUOUS_LOCAL_TIME = "AMBIGUOUS_LOCAL_TIME"
    NONEXISTENT_LOCAL_TIME = "NONEXISTENT_LOCAL_TIME"
    DATE_ONLY_REQUIRES_SHIFT = "DATE_ONLY_REQUIRES_SHIFT"
    DATE_ONLY_READY_NORMALIZED = "DATE_ONLY_READY_NORMALIZED"
    DATE_ONLY_DEADLINE_NORMALIZED = "DATE_ONLY_DEADLINE_NORMALIZED"
    SHIFT_OVERLAP = "SHIFT_OVERLAP"
    MATRIX_LOCATION_MISMATCH = "MATRIX_LOCATION_MISMATCH"
