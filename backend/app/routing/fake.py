"""Deterministic routing provider for offline tests and development."""

from collections.abc import Mapping, Sequence

from backend.app.routing.base import (
    RouteMatrix,
    RoutingLocation,
    RoutingOptions,
    RoutingProviderError,
)


class FakeRoutingProvider:
    """Return configured geocodes and one deterministic matrix without I/O."""

    def __init__(
        self,
        geocodes: Mapping[str, RoutingLocation] | None = None,
        matrix: RouteMatrix | None = None,
    ) -> None:
        self._geocodes = {
            address.strip().casefold(): result for address, result in (geocodes or {}).items()
        }
        self._matrix = matrix
        self.geocode_call_count = 0
        self.matrix_call_count = 0

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
