"""Versioned API request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.application.location_service import LocationResolution
from backend.app.domain.enums import (
    GeocodeLocationType,
    GeocodeReasonCode,
    GeocodeStatus,
    RoutingPreference,
    TravelMode,
)
from backend.app.domain.geocoding import normalize_region_code
from backend.app.domain.models import RoutingMatrix, ensure_aware_utc
from backend.app.domain.results import PlanResult, ValidationResult
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


class PlanResponse(BaseModel):
    """Stored plan response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    plan: PlanResult
    scenario_id: str
    created_at: datetime


class PlanExportResponse(BaseModel):
    """Simple JSON export payload for route and diagnostic tables."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    plan_id: str
    format: str = "json"
    route_rows: tuple[JsonObject, ...]
    diagnostic_rows: tuple[JsonObject, ...]
