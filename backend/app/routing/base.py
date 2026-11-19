"""Provider-neutral routing contracts used by application services."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from backend.app.domain.enums import GeocodeLocationType, RoutingPreference, TravelMode
from backend.app.domain.models import RoutingMatrix


@dataclass(frozen=True, slots=True)
class RoutingLocation:
    """A provider-resolved location used for matrix requests."""

    location_id: str
    formatted_address: str
    latitude: float
    longitude: float
    place_id: str | None = None


@dataclass(frozen=True, slots=True)
class RoutingOptions:
    """Provider-independent matrix options available in the M1 contract."""

    travel_mode: TravelMode = TravelMode.DRIVE
    routing_preference: RoutingPreference = RoutingPreference.TRAFFIC_UNAWARE
    departure_time: datetime | None = None

    def __post_init__(self) -> None:
        if self.departure_time is not None and (
            self.departure_time.tzinfo is None or self.departure_time.utcoffset() is None
        ):
            raise ValueError("Routing departure_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class GeocodeCandidate:
    """One place the provider matched an address to, with its match quality."""

    formatted_address: str
    latitude: float
    longitude: float
    place_id: str | None = None
    location_type: GeocodeLocationType | None = None
    partial_match: bool = False


@dataclass(frozen=True, slots=True)
class AddressResolution:
    """Every candidate the provider returned for one address, best first.

    No candidates means the address was not found. That is a row-level outcome, not
    an error: provider failures (bad key, quota, network) raise instead.
    """

    candidates: tuple[GeocodeCandidate, ...] = ()

    @property
    def found(self) -> bool:
        return bool(self.candidates)

    @property
    def best(self) -> GeocodeCandidate | None:
        return self.candidates[0] if self.candidates else None


RouteMatrix = RoutingMatrix


class RoutingProviderError(RuntimeError):
    """A stable provider error that is safe for application-level handling."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class RoutingProvider(Protocol):
    """Interface implemented by fake and external routing providers."""

    async def geocode(self, addresses: Sequence[str]) -> tuple[RoutingLocation, ...]:
        """Resolve addresses while preserving request order (Version 1.0 contract)."""
        ...

    async def resolve_address(
        self,
        address: str,
        *,
        region_code: str | None = None,
    ) -> AddressResolution:
        """Return every candidate for one address, biased towards ``region_code``."""
        ...

    async def compute_matrix(
        self,
        locations: Sequence[RoutingLocation],
        options: RoutingOptions,
    ) -> RouteMatrix:
        """Return distance and duration matrices for ordered locations."""
        ...

    @property
    def provider_name(self) -> str:
        """Stable provider identifier used in cache keys and metadata."""
        ...

    @property
    def matrix_storage_allowed(self) -> bool:
        """Whether this provider's matrices may be kept beyond one request.

        Decision D6: Google travel-time matrices are not stored (no matrix cache, no
        saved copies); deterministic offline matrices may be.
        """
        ...
