"""Resolve planner addresses to classified, provenance-stamped locations.

Steps: normalise and fingerprint each address -> collapse duplicates -> answer from
the 30-day cache -> call the provider for the rest with bounded concurrency ->
classify each match -> map every result back to the caller's location IDs in
request order.

One unmatched address is a row status, not an error. Provider failures (bad key,
quota, network) fail the request with their stable code; answers obtained before the
failure are already cached, so a retry is cheap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.app.domain.enums import GeocodeLocationType, GeocodeReasonCode, GeocodeStatus
from backend.app.domain.geocoding import (
    address_fingerprint,
    normalize_address,
    straight_line_distance_km,
)
from backend.app.persistence.geocode_cache import SQLiteGeocodeCache, build_geocode_cache_key
from backend.app.routing.base import AddressResolution, GeocodeCandidate, RoutingProvider

NowFunction = Callable[[], datetime]
PRECISE_LOCATION_TYPES = frozenset(
    {GeocodeLocationType.ROOFTOP, GeocodeLocationType.RANGE_INTERPOLATED}
)
MAXIMUM_ALTERNATIVES = 5


@dataclass(frozen=True, slots=True)
class AddressRequest:
    """One planner location to resolve.

    ``confirmed_place_id`` is the place the planner already accepted for this
    location; when Google returns the same place again, no new review is needed.
    """

    location_id: str
    address: str
    confirmed_place_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlantCoordinates:
    """Known plant coordinates for the far-from-plant check."""

    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class LocationResolution:
    """Classified resolution for one requested location ID."""

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


@dataclass(frozen=True, slots=True)
class ResolveSummary:
    """Counts the planner sees after a resolve."""

    resolved: int
    needs_review: int
    failed: int
    cache_hits: int
    provider_calls: int
    unique_addresses: int
    plant_distance_checked: bool


@dataclass(frozen=True, slots=True)
class ResolveOutcome:
    """All per-location results in request order, plus the summary."""

    region_code: str | None
    results: tuple[LocationResolution, ...]
    summary: ResolveSummary


@dataclass(frozen=True, slots=True)
class _Lookup:
    resolution: AddressResolution
    fetched_at: datetime
    cache_hit: bool


_REVIEW_MESSAGES = {
    GeocodeReasonCode.PARTIAL_MATCH: (
        "Google matched only part of this address. Check the matched address."
    ),
    GeocodeReasonCode.LOW_PRECISION: (
        "Google matched this address only to an area, not a street address. "
        "Confirm it or add detail such as the street number."
    ),
}


class LocationService:
    """Resolve addresses through the cache and provider and classify the matches."""

    def __init__(
        self,
        provider: RoutingProvider,
        cache: SQLiteGeocodeCache,
        *,
        max_plant_distance_km: float = 500.0,
        max_concurrency: int = 4,
        now: NowFunction | None = None,
    ) -> None:
        if max_plant_distance_km <= 0:
            raise ValueError("max_plant_distance_km must be positive")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._provider = provider
        self._cache = cache
        self._max_plant_distance_km = max_plant_distance_km
        self._max_concurrency = max_concurrency
        self._now = now or (lambda: datetime.now(UTC))

    async def resolve(
        self,
        requests: Sequence[AddressRequest],
        *,
        region_code: str | None,
        plant_location_id: str | None = None,
        plant_coordinates: PlantCoordinates | None = None,
        force_refresh: bool = False,
    ) -> ResolveOutcome:
        """Resolve each request; ``region_code`` is the effective bias (None for none)."""
        location_ids = [request.location_id for request in requests]
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("location IDs must be unique")
        normalized_by_id: dict[str, str] = {}
        first_address: dict[str, str] = {}
        for request in requests:
            normalized = normalize_address(request.address)
            if not normalized:
                raise ValueError(f"address for {request.location_id} cannot be empty")
            normalized_by_id[request.location_id] = normalized
            first_address.setdefault(normalized, request.address.strip())

        lookups: dict[str, _Lookup] = {}
        missing: list[str] = []
        now = self._now().astimezone(UTC)
        for normalized in first_address:
            if not force_refresh:
                cached = self._cache.get(self._cache_key(normalized, region_code), now=now)
                if cached is not None:
                    lookups[normalized] = _Lookup(cached.resolution, cached.fetched_at, True)
                    continue
            missing.append(normalized)
        lookups.update(await self._fetch(missing, first_address, region_code))

        plant = self._plant_reference(
            plant_location_id, normalized_by_id, lookups, plant_coordinates
        )
        place_owners = self._place_owners(requests, normalized_by_id, lookups)
        results = tuple(
            self._classify(
                request,
                lookups[normalized_by_id[request.location_id]],
                region_code=region_code,
                plant=None if request.location_id == plant_location_id else plant,
                place_owners=place_owners,
            )
            for request in requests
        )
        return ResolveOutcome(
            region_code=region_code,
            results=results,
            summary=ResolveSummary(
                resolved=sum(result.status is GeocodeStatus.RESOLVED for result in results),
                needs_review=sum(result.status is GeocodeStatus.NEEDS_REVIEW for result in results),
                failed=sum(result.status is GeocodeStatus.FAILED for result in results),
                cache_hits=sum(lookup.cache_hit for lookup in lookups.values()),
                provider_calls=len(missing),
                unique_addresses=len(first_address),
                plant_distance_checked=plant is not None,
            ),
        )

    def _cache_key(self, normalized: str, region_code: str | None) -> str:
        return build_geocode_cache_key(
            provider_name=self._provider.provider_name,
            region_code=region_code,
            normalized_address=normalized,
        )

    async def _fetch(
        self,
        missing: Sequence[str],
        first_address: dict[str, str],
        region_code: str | None,
    ) -> dict[str, _Lookup]:
        fetched: dict[str, _Lookup] = {}
        if not missing:
            return fetched
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def fetch_one(normalized: str) -> None:
            async with semaphore:
                resolution = await self._provider.resolve_address(
                    first_address[normalized], region_code=region_code
                )
            fetched_at = self._now().astimezone(UTC)
            if resolution.found:
                # Cached as soon as it arrives, so a later failure in the batch
                # does not throw away what was already paid for.
                self._cache.set(
                    self._cache_key(normalized, region_code),
                    resolution,
                    fetched_at=fetched_at,
                )
            fetched[normalized] = _Lookup(resolution, fetched_at, False)

        try:
            async with asyncio.TaskGroup() as group:
                for normalized in missing:
                    group.create_task(fetch_one(normalized))
        except ExceptionGroup as failures:
            raise failures.exceptions[0] from None
        return fetched

    @staticmethod
    def _plant_reference(
        plant_location_id: str | None,
        normalized_by_id: dict[str, str],
        lookups: dict[str, _Lookup],
        plant_coordinates: PlantCoordinates | None,
    ) -> PlantCoordinates | None:
        if plant_location_id is not None and plant_location_id in normalized_by_id:
            best = lookups[normalized_by_id[plant_location_id]].resolution.best
            if best is not None:
                return PlantCoordinates(best.latitude, best.longitude)
        return plant_coordinates

    @staticmethod
    def _place_key(candidate: GeocodeCandidate) -> str:
        if candidate.place_id:
            return f"place:{candidate.place_id}"
        return f"point:{candidate.latitude:.6f},{candidate.longitude:.6f}"

    def _place_owners(
        self,
        requests: Sequence[AddressRequest],
        normalized_by_id: dict[str, str],
        lookups: dict[str, _Lookup],
    ) -> dict[str, list[str]]:
        owners: dict[str, list[str]] = {}
        for request in requests:
            best = lookups[normalized_by_id[request.location_id]].resolution.best
            if best is not None:
                owners.setdefault(self._place_key(best), []).append(request.location_id)
        return owners

    def _classify(
        self,
        request: AddressRequest,
        lookup: _Lookup,
        *,
        region_code: str | None,
        plant: PlantCoordinates | None,
        place_owners: dict[str, list[str]],
    ) -> LocationResolution:
        candidates = lookup.resolution.candidates
        best = lookup.resolution.best
        if best is None:
            return LocationResolution(
                location_id=request.location_id,
                status=GeocodeStatus.FAILED,
                reason_code=GeocodeReasonCode.ADDRESS_NOT_FOUND,
                reason_codes=(GeocodeReasonCode.ADDRESS_NOT_FOUND,),
                message=(
                    "Google found no match for this address. Check the spelling or add "
                    "the city and postal code."
                ),
                formatted_address=None,
                alternatives=(),
                place_id=None,
                latitude=None,
                longitude=None,
                location_type=None,
                partial_match=None,
                geocode_source_fingerprint=None,
                geocoded_at=None,
                geocode_confirmed=False,
                duplicate_of=(),
                distance_from_plant_km=None,
                cache_hit=lookup.cache_hit,
            )

        review: list[GeocodeReasonCode] = []
        messages: list[str] = []
        if best.partial_match:
            review.append(GeocodeReasonCode.PARTIAL_MATCH)
            messages.append(_REVIEW_MESSAGES[GeocodeReasonCode.PARTIAL_MATCH])
        if best.location_type not in PRECISE_LOCATION_TYPES:
            review.append(GeocodeReasonCode.LOW_PRECISION)
            messages.append(_REVIEW_MESSAGES[GeocodeReasonCode.LOW_PRECISION])
        if len(candidates) > 1:
            review.append(GeocodeReasonCode.MULTIPLE_MATCHES)
            messages.append(
                f"Google found {len(candidates)} possible places for this address. Pick one "
                "of the alternatives or make the address more specific."
            )
        distance_km: float | None = None
        if plant is not None:
            distance_km = straight_line_distance_km(
                plant.latitude, plant.longitude, best.latitude, best.longitude
            )
            if distance_km > self._max_plant_distance_km:
                review.append(GeocodeReasonCode.FAR_FROM_PLANT)
                messages.append(
                    f"The match is {distance_km:,.0f} km from the plant, beyond the "
                    f"{self._max_plant_distance_km:,.0f} km check. Make sure it is the "
                    "right city and country."
                )

        duplicates = tuple(
            owner
            for owner in place_owners.get(self._place_key(best), [])
            if owner != request.location_id
        )
        confirmed = bool(review) and (
            request.confirmed_place_id is not None
            and best.place_id is not None
            and request.confirmed_place_id == best.place_id
        )
        if review and not confirmed:
            status = GeocodeStatus.NEEDS_REVIEW
        else:
            status = GeocodeStatus.RESOLVED
            if confirmed:
                messages.insert(0, "Confirmed earlier by the planner.")
            else:
                messages.append("Resolved.")
        reason_codes = list(review)
        if duplicates:
            reason_codes.append(GeocodeReasonCode.DUPLICATE_PLACE)
            messages.append(f"Same place as {', '.join(duplicates)}.")

        return LocationResolution(
            location_id=request.location_id,
            status=status,
            reason_code=reason_codes[0] if reason_codes else None,
            reason_codes=tuple(reason_codes),
            message=" ".join(messages),
            formatted_address=best.formatted_address,
            alternatives=tuple(
                candidate.formatted_address
                for candidate in candidates[1 : 1 + MAXIMUM_ALTERNATIVES]
            ),
            place_id=best.place_id,
            latitude=best.latitude,
            longitude=best.longitude,
            location_type=best.location_type,
            partial_match=best.partial_match,
            geocode_source_fingerprint=address_fingerprint(request.address, region_code),
            geocoded_at=lookup.fetched_at,
            geocode_confirmed=confirmed,
            duplicate_of=duplicates,
            distance_from_plant_km=(round(distance_km, 1) if distance_km is not None else None),
            cache_hit=lookup.cache_hit,
        )
