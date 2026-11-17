"""Deterministic routing provider for offline tests and development."""

from collections.abc import Mapping, Sequence

from backend.app.domain.enums import GeocodeLocationType
from backend.app.domain.geocoding import normalize_address
from backend.app.routing.base import (
    AddressResolution,
    GeocodeCandidate,
    RouteMatrix,
    RoutingLocation,
    RoutingOptions,
    RoutingProviderError,
)


class FakeRoutingProvider:
    """Return configured geocodes and one deterministic matrix without I/O.

    ``resolutions`` configures ``resolve_address`` answers per address, so partial,
    vague, ambiguous, and unknown addresses can all be simulated. Addresses that are
    only in ``geocodes`` resolve to one rooftop match; anything else is not found.
    ``resolve_error`` fails every resolution and ``resolve_errors`` fails chosen
    addresses, to simulate key, quota, or network failures.
    """

    def __init__(
        self,
        geocodes: Mapping[str, RoutingLocation] | None = None,
        matrix: RouteMatrix | None = None,
        *,
        resolutions: Mapping[str, AddressResolution] | None = None,
        resolve_error: RoutingProviderError | None = None,
        resolve_errors: Mapping[str, RoutingProviderError] | None = None,
    ) -> None:
        self._geocodes = {
            address.strip().casefold(): result for address, result in (geocodes or {}).items()
        }
        self._matrix = matrix
        self._resolutions = {
            normalize_address(address): resolution
            for address, resolution in (resolutions or {}).items()
        }
        self._resolve_error = resolve_error
        self._resolve_errors = {
            normalize_address(address): error for address, error in (resolve_errors or {}).items()
        }
        self.geocode_call_count = 0
        self.matrix_call_count = 0
        self.resolve_call_count = 0
        self.resolve_requests: list[tuple[str, str | None]] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    async def geocode(self, addresses: Sequence[str]) -> tuple[RoutingLocation, ...]:
        """Return configured locations in request order or a controlled error."""
        self.geocode_call_count += 1
        results: list[RoutingLocation] = []
        for address in addresses:
            normalized = address.strip().casefold()
            if not normalized or normalized not in self._geocodes:
                raise RoutingProviderError(
                    code="FAKE_GEOCODE_NOT_FOUND",
                    message=f"No fake geocode configured for address: {address!r}",
                )
            results.append(self._geocodes[normalized])
        return tuple(results)

    async def resolve_address(
        self,
        address: str,
        *,
        region_code: str | None = None,
    ) -> AddressResolution:
        """Return the configured resolution, a legacy geocode, or no match."""
        self.resolve_call_count += 1
        self.resolve_requests.append((address, region_code))
        normalized = normalize_address(address)
        if self._resolve_error is not None:
            raise self._resolve_error
        if normalized in self._resolve_errors:
            raise self._resolve_errors[normalized]
        if normalized in self._resolutions:
            return self._resolutions[normalized]
        legacy = self._geocodes.get(address.strip().casefold())
        if legacy is not None:
            return AddressResolution(
                candidates=(
                    GeocodeCandidate(
                        formatted_address=legacy.formatted_address,
                        latitude=legacy.latitude,
                        longitude=legacy.longitude,
                        place_id=legacy.place_id,
                        location_type=GeocodeLocationType.ROOFTOP,
                    ),
                )
            )
        return AddressResolution()

    async def compute_matrix(
        self,
        locations: Sequence[RoutingLocation],
        options: RoutingOptions,
    ) -> RouteMatrix:
        """Return the configured matrix when ordered location IDs match."""
        del options
        self.matrix_call_count += 1
        if self._matrix is None:
            raise RoutingProviderError(
                code="FAKE_MATRIX_NOT_CONFIGURED",
                message="No fake route matrix has been configured",
            )
        requested_ids = tuple(location.location_id for location in locations)
        if requested_ids != self._matrix.location_ids:
            raise RoutingProviderError(
                code="FAKE_MATRIX_LOCATION_MISMATCH",
                message="Requested location order does not match the configured fake matrix",
            )
        return self._matrix
