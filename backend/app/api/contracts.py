"""Versioned API request and response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.enums import RoutingPreference, TravelMode
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
