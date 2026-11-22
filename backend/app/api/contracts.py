"""Versioned API request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.application.location_service import LocationResolution
from backend.app.domain.enums import (
    DueEvent,
    GeocodeLocationType,
    GeocodeReasonCode,
    GeocodeStatus,
    RoutingPreference,
    TaskType,
    TravelMode,
)
from backend.app.domain.geocoding import normalize_region_code
from backend.app.domain.location_import import ImportedLocation
from backend.app.domain.models import RoutingMatrix, ensure_aware_utc
from backend.app.domain.results import PlanResult, ValidationIssue, ValidationResult
from backend.app.domain.task_import import ImportedTask, ImportTemplate
from backend.app.persistence.scenario_repository import ScenarioSummary
from backend.app.routing.base import RoutingLocation, RoutingOptions

JsonObject = dict[str, Any]


class ApiErrorDetail(BaseModel):
    """Optional structured detail attached to an API error."""

    model_config = ConfigDict(extra="allow")

    code: str | None = None
    message: str | None = None
    field: str | None = None
    row_number: int | None = None
    task_id: str | None = None
    severity: str | None = Field(
        default=None,
        description="ERROR or WARNING for validation details (added in V1.1-M4).",
    )
    section: str | None = None
    item_id: str | None = None


class ApiErrorResponse(BaseModel):
    """Stable error response returned by all non-health API failures."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    code: str
    message: str
    details: tuple[ApiErrorDetail, ...] = ()


class ApiRequestError(RuntimeError):
    """Controlled API failure with an explicit status code and stable error code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: tuple[ApiErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details


class RoutingLocationPayload(BaseModel):
    """JSON representation of a provider-resolved location."""

    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(min_length=1, max_length=120)
    formatted_address: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    place_id: str | None = None

    @classmethod
    def from_domain(cls, location: RoutingLocation) -> RoutingLocationPayload:
        return cls(
            location_id=location.location_id,
            formatted_address=location.formatted_address,
            latitude=location.latitude,
            longitude=location.longitude,
            place_id=location.place_id,
        )

    def to_domain(self) -> RoutingLocation:
        return RoutingLocation(
            location_id=self.location_id,
            formatted_address=self.formatted_address,
            latitude=self.latitude,
            longitude=self.longitude,
            place_id=self.place_id,
        )


class RoutingOptionsPayload(BaseModel):
    """Provider-neutral route-matrix options."""

    model_config = ConfigDict(extra="forbid")

    travel_mode: TravelMode = TravelMode.DRIVE
    routing_preference: RoutingPreference = RoutingPreference.TRAFFIC_UNAWARE
    departure_time: datetime | None = None

    @field_validator("departure_time")
    @classmethod
    def normalize_departure_time(cls, value: datetime | None) -> datetime | None:
        return ensure_aware_utc(value) if value is not None else None

    def to_domain(self) -> RoutingOptions:
        return RoutingOptions(
            travel_mode=self.travel_mode,
            routing_preference=self.routing_preference,
            departure_time=self.departure_time,
        )


class GeocodeRequest(BaseModel):
    """Request body for batch address geocoding."""

    model_config = ConfigDict(extra="forbid")

    addresses: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("addresses")
    @classmethod
    def addresses_are_not_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not address.strip() for address in value):
            raise ValueError("addresses must not contain blank values")
        return value


class GeocodeResponse(BaseModel):
    """Geocoding response with request tracking metadata."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    locations: tuple[RoutingLocationPayload, ...]


class MatrixComputeRequest(BaseModel):
    """Request body for calculating or retrieving a route matrix."""

    model_config = ConfigDict(extra="forbid")

    locations: tuple[RoutingLocationPayload, ...] = Field(min_length=1, max_length=100)
    options: RoutingOptionsPayload = Field(default_factory=RoutingOptionsPayload)
    force_refresh: bool = False


class MatrixComputeResponse(BaseModel):
    """Route matrix plus cache metadata."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    matrix: RoutingMatrix
    cache_hit: bool
    cache_key: str
    cache_enabled: bool = Field(
        default=True,
        description=(
            "False when the provider's terms do not allow storing its matrices "
            "(Google, decision D6): every calculation is billable and nothing is cached."
        ),
    )


class MatrixEstimateRequest(BaseModel):
    """Request body for estimating a route matrix before any billable call."""

    model_config = ConfigDict(extra="forbid")

    locations: tuple[RoutingLocationPayload, ...] = Field(min_length=1, max_length=100)
    options: RoutingOptionsPayload = Field(default_factory=RoutingOptionsPayload)

    @field_validator("locations")
    @classmethod
    def location_ids_are_unique(
        cls, value: tuple[RoutingLocationPayload, ...]
    ) -> tuple[RoutingLocationPayload, ...]:
        if len({location.location_id for location in value}) != len(value):
            raise ValueError("location IDs must be unique")
        return value


class MatrixEstimateResponse(BaseModel):
    """Billable size of a matrix and whether the cache already holds it."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    location_count: int
    element_count: int
    request_count: int
    maximum_elements_per_request: int
    cache_hit: bool
    cache_key: str
    billable_element_count: int
    billable_request_count: int
    confirmation_threshold_elements: int
    confirmation_required: bool
    cache_enabled: bool = True


class AddressToResolvePayload(BaseModel):
    """One planner location to resolve."""

    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    address: str = Field(min_length=1, max_length=500)
    confirmed_place_id: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("address")
    @classmethod
    def address_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("address must not be blank")
        return value


class PlantCoordinatesPayload(BaseModel):
    """Known plant coordinates, used only for the far-from-plant check."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class LocationResolveRequest(BaseModel):
    """Request body for resolving addresses by location ID."""

    model_config = ConfigDict(extra="forbid")

    locations: tuple[AddressToResolvePayload, ...] = Field(min_length=1, max_length=5_000)
    plant_location_id: str | None = Field(default=None, min_length=1, max_length=120)
    plant_coordinates: PlantCoordinatesPayload | None = None
    region_code: str | None = Field(
        default=None,
        max_length=2,
        description=(
            "Two-letter region bias. Omit to use the server default; send an empty "
            "string for no bias."
        ),
    )
    force_refresh: bool = False

    @field_validator("locations")
    @classmethod
    def location_ids_are_unique(
        cls, value: tuple[AddressToResolvePayload, ...]
    ) -> tuple[AddressToResolvePayload, ...]:
        if len({location.location_id for location in value}) != len(value):
            raise ValueError("location IDs must be unique")
        return value

    @field_validator("region_code")
    @classmethod
    def region_code_is_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_region_code(value) or ""


class LocationResolutionPayload(BaseModel):
    """Classified resolution for one location ID."""

    model_config = ConfigDict(extra="forbid")

    location_id: str
    status: GeocodeStatus
    reason_code: GeocodeReasonCode | None
    reason_codes: tuple[GeocodeReasonCode, ...]
    message: str
    formatted_address: str | None
    alternatives: tuple[str, ...]
    place_id: str | None
    latitude: float | None
    longitude: float | None
    location_type: GeocodeLocationType | None
    partial_match: bool | None
    geocode_source_fingerprint: str | None
    geocoded_at: datetime | None
    geocode_confirmed: bool
    duplicate_of: tuple[str, ...]
    distance_from_plant_km: float | None
    cache_hit: bool

    @classmethod
    def from_domain(cls, result: LocationResolution) -> LocationResolutionPayload:
        return cls(
            location_id=result.location_id,
            status=result.status,
            reason_code=result.reason_code,
            reason_codes=result.reason_codes,
            message=result.message,
            formatted_address=result.formatted_address,
            alternatives=result.alternatives,
            place_id=result.place_id,
            latitude=result.latitude,
            longitude=result.longitude,
            location_type=result.location_type,
            partial_match=result.partial_match,
            geocode_source_fingerprint=result.geocode_source_fingerprint,
            geocoded_at=result.geocoded_at,
            geocode_confirmed=result.geocode_confirmed,
            duplicate_of=result.duplicate_of,
            distance_from_plant_km=result.distance_from_plant_km,
            cache_hit=result.cache_hit,
        )


class ResolveSummaryPayload(BaseModel):
    """Counts for one resolve request."""

    model_config = ConfigDict(extra="forbid")

    resolved: int
    needs_review: int
    failed: int
    cache_hits: int
    provider_calls: int
    unique_addresses: int
    plant_distance_checked: bool


class LocationResolveResponse(BaseModel):
    """Per-location results in request order, plus a summary."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    region_code: str | None
    results: tuple[LocationResolutionPayload, ...]
    summary: ResolveSummaryPayload


class ConfigLimitsPayload(BaseModel):
    """Request limits the UI should respect before sending."""

    model_config = ConfigDict(extra="forbid")

    max_request_bytes: int
    max_locations: int
    max_tasks: int
    max_resolve_addresses: int
    max_matrix_locations: int


class ConfigResponse(BaseModel):
    """Non-secret settings the UI needs; never includes credentials."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    default_timezone: str
    google_maps_configured: bool
    geocode_region_code: str | None
    geocode_cache_ttl_seconds: int
    geocode_max_plant_distance_km: float
    matrix_confirm_elements: int
    solver_time_limit_seconds: int
    solver_max_time_limit_seconds: int = Field(
        default=120, description="The longest time limit a planner may choose (V1.1-M5)."
    )
    plan_history_limit: int = Field(default=20, description="Plans kept per scenario.")
    limits: ConfigLimitsPayload


class PlanValidationResponse(BaseModel):
    """Normalized planning validation result."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    validation: ValidationResult


class PlanSolveResponse(BaseModel):
    """Planning validation plus optimization result."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    validation: ValidationResult
    plan: PlanResult


class ScenarioResponse(BaseModel):
    """Stored scenario payload response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenario_id: str
    payload: JsonObject
    created_at: datetime
    updated_at: datetime
    routing_matrix_dropped: bool = Field(
        default=False,
        description="True when an embedded Google matrix was not stored (decision D6).",
    )
    expired_coordinates_removed: int = Field(
        default=0,
        ge=0,
        description=(
            "Locations whose coordinates were older than the 30-day limit and were removed "
            "when the scenario was loaded (V1.1-M6)."
        ),
    )


class ScenarioDeleteResponse(BaseModel):
    """What deleting a saved scenario removed (V1.1-M6)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenario_id: str
    plans_removed: int
    draft_removed: bool


class DraftRequest(BaseModel):
    """The working copy to keep: the scenario document plus small app context.

    ``payload`` is a planning payload whose ``scenario_id`` matches the path. An
    embedded Google matrix is dropped (decision D6); ``meta`` may describe it instead.
    """

    model_config = ConfigDict(extra="forbid")

    payload: JsonObject
    meta: JsonObject = Field(default_factory=dict)


class DraftResponse(BaseModel):
    """A stored draft (V1.1-M6)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenario_id: str
    payload: JsonObject
    meta: JsonObject
    updated_at: datetime
    routing_matrix_dropped: bool = False
    expired_coordinates_removed: int = 0


class DraftDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenario_id: str
    deleted: bool


class ScenarioSummaryPayload(BaseModel):
    """One saved scenario in a list."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str | None
    created_at: datetime
    updated_at: datetime
    location_count: int
    vehicle_count: int
    shift_count: int
    task_count: int
    plan_count: int = Field(default=0, description="Stored plans (V1.1-M6).")

    @classmethod
    def from_domain(
        cls, summary: ScenarioSummary, *, plan_count: int = 0
    ) -> ScenarioSummaryPayload:
        return cls(
            scenario_id=summary.scenario_id,
            name=summary.name,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            location_count=summary.location_count,
            vehicle_count=summary.vehicle_count,
            shift_count=summary.shift_count,
            task_count=summary.task_count,
            plan_count=plan_count,
        )


class ScenarioListResponse(BaseModel):
    """Saved scenarios, most recently updated first."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenarios: tuple[ScenarioSummaryPayload, ...]


class LocationImportPreviewRequest(BaseModel):
    """Rows read from a location spreadsheet, keyed by the file's own headers."""

    model_config = ConfigDict(extra="forbid")

    rows: tuple[dict[str, str | int | float | bool | None], ...] = Field(
        min_length=1, max_length=5_000
    )


class ImportedLocationPayload(BaseModel):
    """One canonical location row; it has no coordinates until it is resolved."""

    model_config = ConfigDict(extra="forbid")

    row_number: int
    name: str
    address: str
    location_id: str | None

    @classmethod
    def from_domain(cls, row: ImportedLocation) -> ImportedLocationPayload:
        return cls(
            row_number=row.row_number,
            name=row.name,
            address=row.address,
            location_id=row.location_id,
        )


class LocationImportPreviewResponse(BaseModel):
    """Mapped rows and issues; the import is applied only if ``valid``."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    valid: bool
    rows: tuple[ImportedLocationPayload, ...]
    issues: tuple[ValidationIssue, ...]
    column_mapping: dict[str, str]
    unknown_columns: tuple[str, ...]


class ImportLocationRefPayload(BaseModel):
    """A scenario location a spreadsheet cell may name, by ID or by exact name."""

    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=500)


class TaskImportPreviewRequest(BaseModel):
    """Rows read from a task spreadsheet, keyed by the file's own headers.

    The scenario's locations let cells name a location by ID or exact name; the plant
    fills the empty plant end of a pickup or drop. ``timezone`` lets local times be
    checked for daylight-saving gaps; the defaults fill empty service-minute cells.
    """

    model_config = ConfigDict(extra="forbid")

    rows: tuple[dict[str, str | int | float | bool | None], ...] = Field(
        min_length=1, max_length=5_000
    )
    locations: tuple[ImportLocationRefPayload, ...] = Field(default=(), max_length=5_000)
    plant_location_id: str = Field(min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    default_pickup_service_minutes: int = Field(default=0, ge=0, le=1_440)
    default_delivery_service_minutes: int = Field(default=0, ge=0, le=1_440)


class ImportedTaskPayload(BaseModel):
    """One canonical task row, in the planning-payload shape plus its row number."""

    model_config = ConfigDict(extra="forbid")

    row_number: int
    task_id: str | None
    po_number: str
    task_type: TaskType
    origin_location_id: str
    destination_location_id: str
    quantity: int | float
    ready_at: str
    due_at: str
    due_event: DueEvent
    pickup_service_minutes: int
    delivery_service_minutes: int
    priority: int
    required_vehicle_tags: tuple[str, ...]
    notes: str | None

    @classmethod
    def from_domain(cls, row: ImportedTask) -> ImportedTaskPayload:
        quantity = (
            int(row.quantity)
            if row.quantity == row.quantity.to_integral_value()
            else float(row.quantity)
        )
        return cls(
            row_number=row.row_number,
            task_id=row.task_id,
            po_number=row.po_number,
            task_type=row.task_type,
            origin_location_id=row.origin_location_id,
            destination_location_id=row.destination_location_id,
            quantity=quantity,
            ready_at=row.ready_at,
            due_at=row.due_at,
            due_event=row.due_event,
            pickup_service_minutes=row.pickup_service_minutes,
            delivery_service_minutes=row.delivery_service_minutes,
            priority=row.priority,
            required_vehicle_tags=row.required_vehicle_tags,
            notes=row.notes,
        )


class TaskImportPreviewResponse(BaseModel):
    """Mapped rows and issues; the app applies the import only if ``valid``."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    valid: bool
    rows: tuple[ImportedTaskPayload, ...]
    issues: tuple[ValidationIssue, ...]
    column_mapping: dict[str, str]
    unknown_columns: tuple[str, ...]


class ImportColumnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    required: bool
    aliases: tuple[str, ...]
    description: str


class ImportTemplateResponse(BaseModel):
    """Columns and an example row for a downloadable import template."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    kind: str
    columns: tuple[ImportColumnPayload, ...]
    example_rows: tuple[dict[str, str | int], ...]

    @classmethod
    def from_domain(cls, template: ImportTemplate, request_id: str) -> ImportTemplateResponse:
        return cls(
            request_id=request_id,
            kind=template.kind,
            columns=tuple(
                ImportColumnPayload(
                    name=column.name,
                    required=column.required,
                    aliases=column.aliases,
                    description=column.description,
                )
                for column in template.columns
            ),
            example_rows=tuple(dict(row) for row in template.example_rows),
        )


class PlanResponse(BaseModel):
    """Stored plan response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    plan: PlanResult
    scenario_id: str
    created_at: datetime


class PlanSummaryPayload(BaseModel):
    """One stored plan in a scenario's history, with the figures to compare plans."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    created_at: datetime
    status: str
    objective_mode: str | None
    search_effort: str | None
    travel_time_factor: float | None
    truck_shifts_used: int
    total_distance_meters: int
    longest_route_seconds: int | None
    scheduled_count: int
    unscheduled_count: int
    # Added in V1.1-M6 for plan comparison.
    time_limit_seconds: int | None = None
    balance_strength: str | None = None
    extra_truck_cost_km: int | None = None
    truck_shifts_available: int | None = None
    longest_working_seconds: int | None = None
    total_driving_seconds: int = 0
    input_fingerprint: str | None = None

    @classmethod
    def from_plan(cls, plan: PlanResult, stored_at: datetime) -> PlanSummaryPayload:
        options = plan.optimization_options
        metrics = plan.metrics
        return cls(
            plan_id=plan.plan_id,
            created_at=plan.created_at or stored_at,
            status=plan.status.value,
            objective_mode=options.objective_mode.value if options else None,
            search_effort=options.search_effort.value if options else None,
            travel_time_factor=options.travel_time_factor if options else None,
            truck_shifts_used=len(plan.routes),
            total_distance_meters=plan.total_distance_meters,
            longest_route_seconds=metrics.longest_route_seconds if metrics else None,
            scheduled_count=len(plan.scheduled_task_ids),
            unscheduled_count=len(plan.unscheduled_task_ids),
            time_limit_seconds=options.time_limit_seconds if options else None,
            balance_strength=options.balance_strength.value if options else None,
            extra_truck_cost_km=options.extra_truck_cost_km if options else None,
            truck_shifts_available=metrics.truck_shifts_available if metrics else None,
            longest_working_seconds=metrics.longest_working_seconds if metrics else None,
            total_driving_seconds=plan.total_driving_seconds,
            input_fingerprint=plan.input_fingerprint,
        )


class PlanHistoryResponse(BaseModel):
    """A scenario's stored plans, newest first (V1.1-M5)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    scenario_id: str
    plans: tuple[PlanSummaryPayload, ...]


class PlanExportResponse(BaseModel):
    """Simple JSON export payload for route and diagnostic tables."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    plan_id: str
    format: str = "json"
    route_rows: tuple[JsonObject, ...]
    diagnostic_rows: tuple[JsonObject, ...]
