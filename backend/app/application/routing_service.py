"""Routing application service with deterministic matrix cache orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.app.domain.models import RoutingMatrix
from backend.app.persistence.matrix_cache import (
    SQLiteMatrixCache,
    build_matrix_cache_key,
)
from backend.app.routing.base import (
    RoutingLocation,
    RoutingOptions,
    RoutingProvider,
)

NowFunction = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class MatrixComputationResult:
    """Matrix plus cache metadata useful to APIs and planner UI."""

    matrix: RoutingMatrix
    cache_hit: bool
    cache_key: str


class RoutingService:
    """Coordinate provider calls and versioned persistent matrix caching."""

    def __init__(
        self,
        provider: RoutingProvider,
        cache: SQLiteMatrixCache,
        *,
        cache_ttl_seconds: int = 86_400,
        departure_bucket_minutes: int = 60,
        now: NowFunction | None = None,
    ) -> None:
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        if departure_bucket_minutes <= 0:
            raise ValueError("departure_bucket_minutes must be positive")
        self._provider = provider
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._departure_bucket_minutes = departure_bucket_minutes
        self._now = now or (lambda: datetime.now(UTC))

    async def geocode(self, addresses: Sequence[str]) -> tuple[RoutingLocation, ...]:
        """Resolve addresses through the selected provider."""
        return await self._provider.geocode(addresses)

    async def compute_matrix(
        self,
        locations: Sequence[RoutingLocation],
        options: RoutingOptions,
        *,
        force_refresh: bool = False,
    ) -> MatrixComputationResult:
        """Return a cached matrix or calculate and persist a complete replacement."""
        cache_key = build_matrix_cache_key(
            provider_name=self._provider.provider_name,
            locations=locations,
            options=options,
            departure_bucket_minutes=self._departure_bucket_minutes,
        )
        now = self._now().astimezone(UTC)
        if not force_refresh:
            cached = self._cache.get(cache_key, now=now)
            if cached is not None:
                return MatrixComputationResult(
                    matrix=cached,
                    cache_hit=True,
                    cache_key=cache_key,
                )

        calculated = await self._provider.compute_matrix(locations, options)
        matrix = calculated.model_copy(
            update={
                "created_at": now,
                "expires_at": now + timedelta(seconds=self._cache_ttl_seconds),
            }
        )
        self._cache.set(cache_key, matrix)
        return MatrixComputationResult(
            matrix=matrix,
            cache_hit=False,
            cache_key=cache_key,
        )
