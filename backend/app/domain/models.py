"""Core Pydantic contracts for planning inputs and routing matrices."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.app.domain.enums import (
    DueEvent,
    GeocodeStatus,
    RoutingPreference,
    TaskType,
    TravelMode,
)

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]


def ensure_aware_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalize aware values to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value.astimezone(UTC)


def validate_load_precision(value: Decimal) -> Decimal:
    """Allow positive quantities and capacities with at most three decimal places."""
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("load values must be finite numbers")
    decimal_places = max(0, -exponent)
    if decimal_places > 3:
        raise ValueError("load values support at most three decimal places")
    return value


class DomainModel(BaseModel):
    """Strict immutable base for public domain contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class Location(DomainModel):
    """A plant, supplier, customer, or hub location."""

    location_id: Identifier
    name: NonEmptyText
    address: NonEmptyText
    formatted_address: str | None = None
    place_id: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geocode_status: GeocodeStatus = GeocodeStatus.PENDING
    geocode_warning: str | None = None

    @model_validator(mode="after")
    def coordinates_are_paired(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.geocode_status is GeocodeStatus.RESOLVED and self.latitude is None:
            raise ValueError("resolved location requires latitude and longitude")
        return self


class Vehicle(DomainModel):
    """Physical truck and its stable capability data."""

    vehicle_id: Identifier
    name: NonEmptyText
    capacity: PositiveDecimal
    tags: frozenset[str] = frozenset()
    enabled: bool = True
    maximum_route_distance_meters: int | None = Field(default=None, gt=0)
    maximum_route_duration_seconds: int | None = Field(default=None, gt=0)

    @field_validator("capacity")
    @classmethod
    def capacity_precision(cls, value: Decimal) -> Decimal:
        return validate_load_precision(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple | set | frozenset):
            return frozenset(str(tag).strip().upper() for tag in value if str(tag).strip())
        return value


class VehicleShift(DomainModel):
    """One dated operating interval for a physical vehicle."""

    shift_id: Identifier
    vehicle_id: Identifier
    start: datetime
    end: datetime
    start_location_id: Identifier = "PLANT"
    end_location_id: Identifier = "PLANT"
    maximum_route_duration_seconds: int | None = Field(default=None, gt=0)

    @field_validator("start", "end")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @model_validator(mode="after")
    def start_precedes_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("shift start must precede shift end")
        return self


class PlanningHorizon(DomainModel):
    """Inclusive planning interval and display timezone."""

    start: datetime
    end: datetime
    timezone: str = "America/Toronto"

    @field_validator("start", "end")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def start_precedes_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("planning horizon start must precede end")
        return self


class Task(DomainModel):
    """One user-facing PO movement with positive quantity."""

    task_id: Identifier
    po_number: NonEmptyText
    task_type: TaskType
    origin_location_id: Identifier
    destination_location_id: Identifier
    quantity: PositiveDecimal
    ready_at: datetime
    due_at: datetime
    due_event: DueEvent
    pickup_service_minutes: int = Field(default=0, ge=0, le=1_440)
    delivery_service_minutes: int = Field(default=0, ge=0, le=1_440)
    priority: int = Field(default=1, ge=1, le=5)
    required_vehicle_tags: frozenset[str] = frozenset()
    notes: str | None = None

    @field_validator("ready_at", "due_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime) -> datetime:
        return ensure_aware_utc(value)

    @field_validator("quantity")
    @classmethod
    def quantity_precision(cls, value: Decimal) -> Decimal:
        return validate_load_precision(value)

    @field_validator("required_vehicle_tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple | set | frozenset):
            return frozenset(str(tag).strip().upper() for tag in value if str(tag).strip())
        return value

    @model_validator(mode="after")
    def validate_route_and_time(self) -> Self:
        if self.origin_location_id == self.destination_location_id:
            raise ValueError("task origin and destination must differ")
        if self.ready_at > self.due_at:
            raise ValueError("ready_at must not be after due_at")
        return self


class MatrixElementIssue(DomainModel):
    """A route-matrix element that could not be calculated."""

    origin_location_id: Identifier
    destination_location_id: Identifier
    error_code: NonEmptyText
    message: NonEmptyText


class RoutingMatrix(DomainModel):
    """Provider-neutral asymmetric distance and duration matrix."""

    location_ids: tuple[Identifier, ...]
    distance_meters: tuple[tuple[NonNegativeInt, ...], ...]
    duration_seconds: tuple[tuple[NonNegativeInt, ...], ...]
    source: NonEmptyText
    travel_mode: TravelMode = TravelMode.DRIVE
    routing_preference: RoutingPreference = RoutingPreference.TRAFFIC_UNAWARE
    departure_time: datetime | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    element_issues: tuple[MatrixElementIssue, ...] = ()

    @field_validator("departure_time", "created_at", "expires_at")
    @classmethod
    def normalize_optional_datetimes(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        size = len(self.location_ids)
        if size == 0:
            raise ValueError("route matrix must contain at least one location")
        if len(set(self.location_ids)) != size:
            raise ValueError("route matrix location IDs must be unique")
        for name, matrix in (
            ("distance_meters", self.distance_meters),
            ("duration_seconds", self.duration_seconds),
        ):
            if len(matrix) != size or any(len(row) != size for row in matrix):
                raise ValueError(f"{name} must be a square matrix matching location IDs")
            if any(matrix[index][index] != 0 for index in range(size)):
                raise ValueError(f"{name} diagonal must be zero")
        if self.created_at and self.expires_at and self.expires_at <= self.created_at:
            raise ValueError("matrix expires_at must be after created_at")
        known_ids = set(self.location_ids)
        for issue in self.element_issues:
            if (
                issue.origin_location_id not in known_ids
                or issue.destination_location_id not in known_ids
            ):
                raise ValueError("matrix element issue references an unknown location")
        return self


class PlanningRequest(DomainModel):
    """Fully normalized input accepted by planning application services."""

    scenario_id: Identifier
    horizon: PlanningHorizon
    plant_location_id: Identifier
    locations: tuple[Location, ...]
    vehicles: tuple[Vehicle, ...]
    vehicle_shifts: tuple[VehicleShift, ...]
    tasks: tuple[Task, ...]
    routing_matrix: RoutingMatrix | None = None

    @model_validator(mode="after")
    def validate_references_and_business_rules(self) -> Self:
        location_ids = [location.location_id for location in self.locations]
        vehicle_ids = [vehicle.vehicle_id for vehicle in self.vehicles]
        shift_ids = [shift.shift_id for shift in self.vehicle_shifts]
        task_ids = [task.task_id for task in self.tasks]

        for label, values in (
            ("location", location_ids),
            ("vehicle", vehicle_ids),
            ("shift", shift_ids),
            ("task", task_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} ID")

        known_locations = set(location_ids)
        known_vehicles = set(vehicle_ids)
        if self.plant_location_id not in known_locations:
            raise ValueError("plant_location_id references an unknown location")
        if not any(vehicle.enabled for vehicle in self.vehicles):
            raise ValueError("at least one vehicle must be enabled")

        intervals_by_vehicle: dict[str, list[tuple[datetime, datetime]]] = {}
        for shift in self.vehicle_shifts:
            if shift.vehicle_id not in known_vehicles:
                raise ValueError(f"shift {shift.shift_id} references an unknown vehicle")
            if (
                shift.start_location_id not in known_locations
                or shift.end_location_id not in known_locations
            ):
                raise ValueError(f"shift {shift.shift_id} references an unknown depot location")
            if not (self.horizon.start <= shift.start < shift.end <= self.horizon.end):
                raise ValueError(f"shift {shift.shift_id} is outside the planning horizon")
            intervals_by_vehicle.setdefault(shift.vehicle_id, []).append((shift.start, shift.end))

        for vehicle_id, intervals in intervals_by_vehicle.items():
            for previous, current in pairwise(sorted(intervals)):
                if previous[1] > current[0]:
                    raise ValueError(f"vehicle {vehicle_id} has overlapping shifts")

        for task in self.tasks:
            if task.origin_location_id not in known_locations:
                raise ValueError(f"task {task.task_id} references an unknown origin")
            if task.destination_location_id not in known_locations:
                raise ValueError(f"task {task.task_id} references an unknown destination")
            if task.task_type is TaskType.PICKUP and (
                task.origin_location_id == self.plant_location_id
                or task.destination_location_id != self.plant_location_id
            ):
                raise ValueError(f"pickup task {task.task_id} must end at the plant")
            if task.task_type is TaskType.DROP and (
                task.origin_location_id != self.plant_location_id
                or task.destination_location_id == self.plant_location_id
            ):
                raise ValueError(f"drop task {task.task_id} must start at the plant")
            if task.task_type is TaskType.PICKUP_DROP and (
                task.origin_location_id == self.plant_location_id
                or task.destination_location_id == self.plant_location_id
            ):
                raise ValueError(f"pickup-drop task {task.task_id} must use non-plant endpoints")
            if not (self.horizon.start <= task.ready_at <= task.due_at <= self.horizon.end):
                raise ValueError(f"task {task.task_id} is outside the planning horizon")

        if (
            self.routing_matrix is not None
            and set(self.routing_matrix.location_ids) != known_locations
        ):
            raise ValueError("routing matrix locations must exactly match request locations")
        return self
