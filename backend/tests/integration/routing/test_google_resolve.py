"""V1.1-M1 Google resolve_address tests using mocked HTTP only."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from backend.app.domain import GeocodeLocationType
from backend.app.routing import (
    AddressResolution,
    GoogleRoutingProvider,
    RoutingErrorCode,
    RoutingProviderError,
)

TEST_KEY = "unit-test-secret-key-m1"


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def provider_for(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    maximum_attempts: int = 3,
) -> GoogleRoutingProvider:
    async def no_sleep(_delay: float) -> None:
        return None

    return GoogleRoutingProvider(
        api_key=TEST_KEY,
        geocoding_url="https://google.test/geocode",
        routes_matrix_url="https://google.test/matrix",
        maximum_attempts=maximum_attempts,
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
        jitter=lambda _start, _end: 0.0,
    )


def result(
    formatted_address: str,
    latitude: float,
    *,
    location_type: str | None = "ROOFTOP",
    partial_match: bool | None = None,
) -> dict[str, Any]:
    geometry: dict[str, Any] = {"location": {"lat": latitude, "lng": -79.5}}
    if location_type is not None:
        geometry["location_type"] = location_type
    value: dict[str, Any] = {
        "formatted_address": formatted_address,
        "place_id": f"place-{latitude}",
        "geometry": geometry,
    }
    if partial_match is not None:
        value["partial_match"] = partial_match
    return value


def test_resolve_sends_the_region_bias_and_parses_match_quality() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    result(
                        "200 Supplier Ave, Vaughan",
                        43.82,
                        location_type="RANGE_INTERPOLATED",
                        partial_match=True,
                    ),
                    result("200 Supplier Ave W, Vaughan", 43.83, location_type="APPROXIMATE"),
                ],
            },
        )

    resolution = run(
        provider_for(handler).resolve_address(" 200 Supplier Avenue, Vaughan ", region_code="CA")
    )

    assert seen[0].url.params["region"] == "ca"
    assert seen[0].url.params["address"] == "200 Supplier Avenue, Vaughan"
    assert resolution.found
    assert len(resolution.candidates) == 2
    best = resolution.best
    assert best is not None
    assert best.location_type is GeocodeLocationType.RANGE_INTERPOLATED
    assert best.partial_match is True
    assert best.place_id == "place-43.82"
    assert resolution.candidates[1].location_type is GeocodeLocationType.APPROXIMATE
    assert resolution.candidates[1].partial_match is False


def test_resolve_without_region_sends_no_region_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "OK", "results": [result("Plant", 43.7)]})

    run(provider_for(handler).resolve_address("100 Plant Road", region_code=None))

    assert "region" not in seen[0].url.params


def test_legacy_geocode_still_sends_no_region_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "OK", "results": [result("Plant", 43.7)]})

    (location,) = run(provider_for(handler).geocode(["100 Plant Road"]))

    assert set(seen[0].url.params) == {"address", "key"}
    assert location.location_id.startswith("GEO-")
    assert location.formatted_address == "Plant"


def test_zero_results_is_an_empty_resolution_not_an_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

    resolution = run(provider_for(handler).resolve_address("999 Nowhere Lane"))

    assert resolution == AddressResolution()
    assert not resolution.found
    assert resolution.best is None


def test_legacy_geocode_still_fails_on_zero_results() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})

    with pytest.raises(RoutingProviderError) as raised:
        run(provider_for(handler).geocode(["999 Nowhere Lane"]))

    assert raised.value.code == RoutingErrorCode.GEOCODE_NOT_FOUND


def test_unknown_precision_and_malformed_alternatives_are_tolerated() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    result("Plant", 43.7, location_type="SOMETHING_NEW"),
                    {"formatted_address": "No geometry"},
                    "not an object",
                    result("Plant annex", 43.71),
                ],
            },
        )

    resolution = run(provider_for(handler).resolve_address("100 Plant Road"))

    assert [candidate.formatted_address for candidate in resolution.candidates] == [
        "Plant",
        "Plant annex",
    ]
    assert resolution.candidates[0].location_type is None


def test_malformed_first_result_is_still_an_invalid_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "results": [{"geometry": {}}]})

    with pytest.raises(RoutingProviderError) as raised:
        run(provider_for(handler).resolve_address("100 Plant Road"))

    assert raised.value.code == RoutingErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("google_status", "expected"),
    [
        ("REQUEST_DENIED", RoutingErrorCode.AUTH_ERROR),
        ("OVER_QUERY_LIMIT", RoutingErrorCode.RATE_LIMIT),
        ("OVER_DAILY_LIMIT", RoutingErrorCode.RATE_LIMIT),
        ("UNKNOWN_ERROR", RoutingErrorCode.SERVER_ERROR),
    ],
)
def test_key_and_quota_failures_raise_stable_codes(
    google_status: str, expected: RoutingErrorCode
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": google_status, "results": []})

    with pytest.raises(RoutingProviderError) as raised:
        run(provider_for(handler, maximum_attempts=2).resolve_address("100 Plant Road"))

    assert raised.value.code == expected
    assert TEST_KEY not in str(raised.value)


def test_http_403_is_an_auth_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error_message": "API key not valid"})

    with pytest.raises(RoutingProviderError) as raised:
        run(provider_for(handler).resolve_address("100 Plant Road"))

    assert raised.value.code == RoutingErrorCode.AUTH_ERROR


@pytest.mark.parametrize(("address", "region"), [("   ", "ca"), ("100 Plant Road", "canada")])
def test_invalid_input_is_rejected_before_any_call(address: str, region: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "OK", "results": [result("Plant", 43.7)]})

    with pytest.raises(RoutingProviderError) as raised:
        run(provider_for(handler).resolve_address(address, region_code=region))

    assert raised.value.code == RoutingErrorCode.INVALID_REQUEST
    assert calls == []


def test_resolve_logs_never_contain_the_key_or_address(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["address"].startswith("999"):
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
        return httpx.Response(429)

    provider = provider_for(handler, maximum_attempts=2)
    with caplog.at_level(logging.DEBUG):
        run(provider.resolve_address("999 Nowhere Lane"))
        with pytest.raises(RoutingProviderError):
            run(provider.resolve_address("100 Plant Road"))

    assert caplog.records
    assert TEST_KEY not in caplog.text
    assert "Nowhere" not in caplog.text
    assert "Plant Road" not in caplog.text
