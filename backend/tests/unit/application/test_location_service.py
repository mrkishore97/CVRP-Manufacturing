"""V1.1-M1 location service: deduplication, caching, and every classification rule."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.app.application import (
    AddressRequest,
    LocationService,
    PlantCoordinates,
    ResolveOutcome,
)
from backend.app.domain import GeocodeLocationType, GeocodeReasonCode, GeocodeStatus
from backend.app.domain.geocoding import address_fingerprint
from backend.app.persistence import SQLiteDatabase, SQLiteGeocodeCache
from backend.app.routing import (
    AddressResolution,
    FakeRoutingProvider,
    GeocodeCandidate,
    RoutingErrorCode,
    RoutingProviderError,
)

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)

PLANT = "100 Fixture Plant Road, Toronto, ON"
EXACT = "200 Supplier Avenue, Vaughan, ON"
INTERPOLATED = "250 Supplier Avenue, Vaughan, ON"
PARTIAL = "300 Supplier Avenue Unit 9, Vaughan, ON"
VAGUE = "Vaughan, ON"
STREET_ONLY = "Supplier Avenue, Vaughan, ON"
AMBIGUOUS = "100 Main Street"
WRONG_CITY = "200 Supplier Avenue, Vancouver"
UNKNOWN = "999 Nowhere Lane, Atlantis"


def candidate(
    name: str,
    latitude: float,
    longitude: float,
    *,
    location_type: GeocodeLocationType | None = GeocodeLocationType.ROOFTOP,
    partial_match: bool = False,
    place_id: str | None = None,
) -> GeocodeCandidate:
    return GeocodeCandidate(
        formatted_address=f"{name}, Canada",
        latitude=latitude,
        longitude=longitude,
        place_id=place_id if place_id is not None else f"place-{name}",
        location_type=location_type,
        partial_match=partial_match,
    )


def one(match: GeocodeCandidate) -> AddressResolution:
    return AddressResolution(candidates=(match,))


RESOLUTIONS: Mapping[str, AddressResolution] = {
    PLANT: one(candidate("100 Fixture Plant Rd", 43.70, -79.40)),
    EXACT: one(candidate("200 Supplier Ave", 43.82, -79.50)),
    INTERPOLATED: one(
        candidate(
            "250 Supplier Ave",
            43.821,
            -79.501,
            location_type=GeocodeLocationType.RANGE_INTERPOLATED,
        )
    ),
    PARTIAL: one(candidate("300 Supplier Ave", 43.822, -79.502, partial_match=True)),
    VAGUE: one(
        candidate("Vaughan, ON", 43.84, -79.51, location_type=GeocodeLocationType.APPROXIMATE)
    ),
    STREET_ONLY: one(
        candidate(
            "Supplier Ave, Vaughan",
            43.83,
            -79.50,
            location_type=GeocodeLocationType.GEOMETRIC_CENTER,
        )
    ),
    AMBIGUOUS: AddressResolution(
        candidates=(
            candidate("100 Main St, Toronto", 43.68, -79.30),
            candidate("100 Main St, Markham", 43.87, -79.26),
            candidate("100 Main St, Brampton", 43.69, -79.76),
        )
    ),
    WRONG_CITY: one(candidate("200 Supplier Ave, Vancouver, BC", 49.28, -123.12)),
}


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def build(
    tmp_path: Path,
    provider: FakeRoutingProvider | None = None,
    *,
    now: datetime = NOW,
) -> tuple[LocationService, FakeRoutingProvider, SQLiteGeocodeCache]:
    fake = provider or FakeRoutingProvider(resolutions=RESOLUTIONS)
    cache = SQLiteGeocodeCache(SQLiteDatabase(tmp_path / "geocode.db"), now=lambda: now)
    service = LocationService(fake, cache, max_plant_distance_km=500.0, now=lambda: now)
    return service, fake, cache


def resolve(
    service: LocationService,
    rows: list[tuple[str, str]] | list[AddressRequest],
    **kwargs: Any,
) -> ResolveOutcome:
    requests = [
        row if isinstance(row, AddressRequest) else AddressRequest(row[0], row[1]) for row in rows
    ]
    kwargs.setdefault("region_code", "ca")
    kwargs.setdefault("plant_location_id", "PLANT")
    return run(service.resolve(requests, **kwargs))


def by_id(outcome: ResolveOutcome) -> dict[str, Any]:
    return {result.location_id: result for result in outcome.results}


def test_results_keep_the_callers_ids_and_request_order(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)
    rows = [("SUPPLIER-B", INTERPOLATED), ("PLANT", PLANT), ("SUPPLIER-A", EXACT)]

    outcome = resolve(service, rows)

    assert [result.location_id for result in outcome.results] == [
        "SUPPLIER-B",
        "PLANT",
        "SUPPLIER-A",
    ]
    assert outcome.results[0].formatted_address == "250 Supplier Ave, Canada"


def test_exact_and_interpolated_matches_resolve(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    results = by_id(resolve(service, [("PLANT", PLANT), ("A", EXACT), ("B", INTERPOLATED)]))

    for location_id in ("PLANT", "A", "B"):
        assert results[location_id].status is GeocodeStatus.RESOLVED
        assert results[location_id].reason_code is None
        assert results[location_id].reason_codes == ()
    assert results["A"].geocode_source_fingerprint == address_fingerprint(EXACT, "ca")
    assert results["A"].geocoded_at == NOW
    assert results["A"].location_type is GeocodeLocationType.ROOFTOP
    assert results["A"].partial_match is False
    assert results["A"].distance_from_plant_km == pytest.approx(15.6, abs=0.5)
    assert results["PLANT"].distance_from_plant_km is None


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        (PARTIAL, GeocodeReasonCode.PARTIAL_MATCH),
        (VAGUE, GeocodeReasonCode.LOW_PRECISION),
        (STREET_ONLY, GeocodeReasonCode.LOW_PRECISION),
        (AMBIGUOUS, GeocodeReasonCode.MULTIPLE_MATCHES),
        (WRONG_CITY, GeocodeReasonCode.FAR_FROM_PLANT),
    ],
)
def test_doubtful_matches_need_review(
    tmp_path: Path, address: str, reason: GeocodeReasonCode
) -> None:
    service, _, _ = build(tmp_path)

    result = by_id(resolve(service, [("PLANT", PLANT), ("X", address)]))["X"]

    assert result.status is GeocodeStatus.NEEDS_REVIEW
    assert result.reason_code is reason
    assert result.reason_codes == (reason,)
    assert result.latitude is not None
    assert result.geocode_source_fingerprint is not None
    assert result.geocode_confirmed is False


def test_multiple_matches_list_the_alternatives(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    result = by_id(resolve(service, [("PLANT", PLANT), ("X", AMBIGUOUS)]))["X"]

    assert result.formatted_address == "100 Main St, Toronto, Canada"
    assert result.alternatives == ("100 Main St, Markham, Canada", "100 Main St, Brampton, Canada")
    assert "3 possible places" in result.message


def test_far_from_plant_reports_the_distance(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    result = by_id(resolve(service, [("PLANT", PLANT), ("X", WRONG_CITY)]))["X"]

    assert result.distance_from_plant_km is not None
    assert result.distance_from_plant_km > 3_000
    assert "km from the plant" in result.message


def test_supplied_plant_coordinates_enable_the_distance_check(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    outcome = resolve(
        service,
        [("X", WRONG_CITY)],
        plant_coordinates=PlantCoordinates(43.70, -79.40),
    )

    assert outcome.summary.plant_distance_checked is True
    assert outcome.results[0].reason_code is GeocodeReasonCode.FAR_FROM_PLANT


def test_without_a_plant_the_distance_check_is_skipped_and_reported(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    outcome = resolve(service, [("X", WRONG_CITY)])

    assert outcome.summary.plant_distance_checked is False
    assert outcome.results[0].status is GeocodeStatus.RESOLVED
    assert outcome.results[0].distance_from_plant_km is None


def test_unknown_address_fails_only_its_own_row(tmp_path: Path) -> None:
    service, _, cache = build(tmp_path)

    outcome = resolve(service, [("PLANT", PLANT), ("GONE", UNKNOWN), ("A", EXACT)])
    results = by_id(outcome)

    assert results["GONE"].status is GeocodeStatus.FAILED
    assert results["GONE"].reason_code is GeocodeReasonCode.ADDRESS_NOT_FOUND
    assert results["GONE"].latitude is None
    assert results["GONE"].geocode_source_fingerprint is None
    assert results["A"].status is GeocodeStatus.RESOLVED
    assert (outcome.summary.resolved, outcome.summary.failed) == (2, 1)


def test_two_ids_at_one_place_are_resolved_with_a_note(tmp_path: Path) -> None:
    resolutions = dict(RESOLUTIONS)
    resolutions["200 Supplier Avenue Dock 2, Vaughan"] = RESOLUTIONS[EXACT]
    service, _, _ = build(tmp_path, FakeRoutingProvider(resolutions=resolutions))

    results = by_id(
        resolve(
            service,
            [("PLANT", PLANT), ("A", EXACT), ("A-DOCK", "200 Supplier Avenue Dock 2, Vaughan")],
        )
    )

    for location_id, other in (("A", "A-DOCK"), ("A-DOCK", "A")):
        assert results[location_id].status is GeocodeStatus.RESOLVED
        assert results[location_id].reason_code is GeocodeReasonCode.DUPLICATE_PLACE
        assert results[location_id].duplicate_of == (other,)
        assert f"Same place as {other}" in results[location_id].message
    assert results["PLANT"].duplicate_of == ()


def test_duplicate_note_is_added_after_review_reasons(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    results = by_id(resolve(service, [("PLANT", PLANT), ("V1", VAGUE), ("V2", " vaughan,  on ")]))

    assert results["V1"].status is GeocodeStatus.NEEDS_REVIEW
    assert results["V1"].reason_codes == (
        GeocodeReasonCode.LOW_PRECISION,
        GeocodeReasonCode.DUPLICATE_PLACE,
    )


def test_duplicate_addresses_cause_one_provider_call(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)

    outcome = resolve(
        service,
        [("PLANT", PLANT), ("A", EXACT), ("A2", "  200 supplier avenue,  VAUGHAN, on")],
    )

    assert provider.resolve_call_count == 2
    assert outcome.summary.unique_addresses == 2
    assert outcome.summary.provider_calls == 2
    assert by_id(outcome)["A2"].formatted_address == by_id(outcome)["A"].formatted_address


def test_region_bias_is_passed_to_the_provider(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)

    resolve(service, [("A", EXACT)], region_code="ca")
    resolve(service, [("B", INTERPOLATED)], region_code=None)

    assert provider.resolve_requests == [(EXACT, "ca"), (INTERPOLATED, None)]


def test_second_resolve_is_served_from_the_cache(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)
    rows = [("PLANT", PLANT), ("A", EXACT), ("GONE", UNKNOWN)]

    first = resolve(service, rows)
    second = resolve(service, rows)

    assert first.summary.cache_hits == 0
    assert second.summary.cache_hits == 2
    assert second.summary.provider_calls == 1  # the unknown address is never cached
    assert provider.resolve_call_count == 4
    assert by_id(second)["A"].cache_hit is True
    assert by_id(second)["GONE"].cache_hit is False


def test_cache_hit_keeps_the_original_geocoded_at(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)
    resolve(service, [("A", EXACT)])

    later_service, _, _ = build(tmp_path, provider, now=NOW + timedelta(days=10))
    result = resolve(later_service, [("A", EXACT)]).results[0]

    assert result.cache_hit is True
    assert result.geocoded_at == NOW


def test_expired_cache_entry_calls_the_provider_again(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)
    resolve(service, [("A", EXACT)])

    later_service, _, _ = build(tmp_path, provider, now=NOW + timedelta(days=30))
    result = resolve(later_service, [("A", EXACT)]).results[0]

    assert result.cache_hit is False
    assert result.geocoded_at == NOW + timedelta(days=30)
    assert provider.resolve_call_count == 2


def test_cache_is_kept_per_region(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)

    resolve(service, [("A", EXACT)], region_code="ca")
    outcome = resolve(service, [("A", EXACT)], region_code="us")

    assert outcome.summary.cache_hits == 0
    assert provider.resolve_call_count == 2
    assert outcome.results[0].geocode_source_fingerprint == address_fingerprint(EXACT, "us")


def test_force_refresh_bypasses_the_cache(tmp_path: Path) -> None:
    service, provider, _ = build(tmp_path)
    resolve(service, [("A", EXACT)])

    outcome = resolve(service, [("A", EXACT)], force_refresh=True)

    assert outcome.summary.cache_hits == 0
    assert outcome.results[0].cache_hit is False
    assert provider.resolve_call_count == 2


@pytest.mark.parametrize(
    "code",
    [RoutingErrorCode.AUTH_ERROR, RoutingErrorCode.RATE_LIMIT, RoutingErrorCode.NETWORK_ERROR],
)
def test_provider_failure_fails_the_batch_with_its_code(
    tmp_path: Path, code: RoutingErrorCode
) -> None:
    provider = FakeRoutingProvider(
        resolutions=RESOLUTIONS,
        resolve_errors={EXACT: RoutingProviderError(code, "simulated failure")},
    )
    service, _, _ = build(tmp_path, provider)

    with pytest.raises(RoutingProviderError) as raised:
        resolve(service, [("PLANT", PLANT), ("A", EXACT), ("B", INTERPOLATED)])

    assert raised.value.code == code


def test_answers_obtained_before_a_failure_are_cached(tmp_path: Path) -> None:
    failing = FakeRoutingProvider(
        resolutions=RESOLUTIONS,
        resolve_errors={EXACT: RoutingProviderError(RoutingErrorCode.RATE_LIMIT, "quota")},
    )
    service, _, cache = build(tmp_path, failing)
    with pytest.raises(RoutingProviderError):
        resolve(service, [("PLANT", PLANT), ("A", EXACT)])

    retry_provider = FakeRoutingProvider(resolutions=RESOLUTIONS)
    retry, _, _ = build(tmp_path, retry_provider)
    outcome = resolve(retry, [("PLANT", PLANT), ("A", EXACT)])

    assert by_id(outcome)["PLANT"].cache_hit is True
    assert retry_provider.resolve_requests == [(EXACT, "ca")]


def test_confirmed_place_is_not_reviewed_again(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)
    vague_place = RESOLUTIONS[VAGUE].candidates[0].place_id

    outcome = resolve(
        service,
        [
            AddressRequest("PLANT", PLANT),
            AddressRequest("OK", VAGUE, confirmed_place_id=vague_place),
            AddressRequest("MOVED", STREET_ONLY, confirmed_place_id="some-other-place"),
        ],
    )
    results = by_id(outcome)

    assert results["OK"].status is GeocodeStatus.RESOLVED
    assert results["OK"].geocode_confirmed is True
    assert results["OK"].reason_codes == (GeocodeReasonCode.LOW_PRECISION,)
    assert results["OK"].message.startswith("Confirmed earlier by the planner.")
    assert results["MOVED"].status is GeocodeStatus.NEEDS_REVIEW
    assert results["MOVED"].geocode_confirmed is False


def test_unknown_precision_is_treated_as_low_precision(tmp_path: Path) -> None:
    provider = FakeRoutingProvider(
        resolutions={EXACT: one(candidate("200 Supplier Ave", 43.82, -79.5, location_type=None))}
    )
    service, _, _ = build(tmp_path, provider)

    result = resolve(service, [("A", EXACT)]).results[0]

    assert result.reason_code is GeocodeReasonCode.LOW_PRECISION


def test_duplicate_location_ids_are_rejected(tmp_path: Path) -> None:
    service, _, _ = build(tmp_path)

    with pytest.raises(ValueError, match="unique"):
        resolve(service, [("A", EXACT), ("A", INTERPOLATED)])
