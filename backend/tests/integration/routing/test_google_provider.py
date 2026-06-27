"""Google provider tests using mocked HTTP only."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from backend.app.config import Settings
from backend.app.routing import (
    GoogleRoutingProvider,
    RoutingErrorCode,
    RoutingLimits,
    RoutingLocation,
    RoutingOptions,
    RoutingProviderError,
    google_provider_from_settings,
)

TEST_KEY = "unit-test-secret-key"


def run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def locations(count: int = 2) -> tuple[RoutingLocation, ...]:
    return tuple(
        RoutingLocation(
            location_id=f"LOC-{index}",
            formatted_address=f"Location {index}",
            latitude=float(index),
            longitude=float(-index),
            place_id=f"place-{index}",
        )
        for index in range(count)
    )


def route_elements_from_request(request: httpx.Request) -> list[dict[str, Any]]:
    payload: dict[str, Any] = json.loads(request.content)
    origins = payload["origins"]
    destinations = payload["destinations"]
    elements: list[dict[str, Any]] = []
    for origin_index, origin in enumerate(origins):
        origin_value = int(origin["waypoint"]["location"]["latLng"]["latitude"])
        for destination_index, destination in enumerate(destinations):
            destination_value = int(destination["waypoint"]["location"]["latLng"]["latitude"])
            if origin_value == destination_value:
                distance = 0
                duration = "0s"
            else:
                distance = (origin_value + 1) * 1_000 + (destination_value + 1) * 10
                duration = f"{distance / 10:.1f}s"
            elements.append(
                {
                    "originIndex": origin_index,
                    "destinationIndex": destination_index,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "distanceMeters": distance,
                    "duration": duration,
                }
            )
    return elements


def provider_for(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    maximum_attempts: int = 3,
    limits: RoutingLimits | None = None,
    delays: list[float] | None = None,
) -> GoogleRoutingProvider:
    recorded_delays = delays if delays is not None else []

    async def record_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    return GoogleRoutingProvider(
        api_key=TEST_KEY,
        geocoding_url="https://google.test/geocode",
        routes_matrix_url="https://google.test/matrix",
        maximum_attempts=maximum_attempts,
        retry_base_delay_seconds=0.1,
        limits=limits,
        transport=httpx.MockTransport(handler),
        sleep=record_sleep,
        jitter=lambda _start, _end: 0.0,
    )


def test_geocode_deduplicates_addresses_and_preserves_input_order() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geocode"
        assert request.url.params["key"] == TEST_KEY
        address = request.url.params["address"]
        calls.append(address)
        latitude = 43.0 if "Plant" in address else 44.0
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "formatted_address": f"Normalized {address}",
                        "place_id": f"place-{latitude}",
                        "geometry": {"location": {"lat": latitude, "lng": -79.0}},
                    }
                ],
            },
        )

    provider = provider_for(handler)
    result = run(provider.geocode(["Plant Road", "Supplier Road", " plant   road "]))

    assert calls == ["Plant Road", "Supplier Road"]
    assert len(result) == 3
    assert result[0] == result[2]
    assert result[0].formatted_address == "Normalized Plant Road"


def test_matrix_preserves_asymmetry_and_rounds_duration_up() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/matrix"
        assert request.headers["X-Goog-Api-Key"] == TEST_KEY
        assert "distanceMeters" in request.headers["X-Goog-FieldMask"]
        return httpx.Response(200, json=route_elements_from_request(request))

    matrix = run(provider_for(handler).compute_matrix(locations(), RoutingOptions()))

    assert matrix.distance_meters == ((0, 1_020), (2_010, 0))
    assert matrix.duration_seconds == ((0, 102), (201, 0))
    assert matrix.distance_meters[0][1] != matrix.distance_meters[1][0]


def test_matrix_accepts_omitted_zero_distance_only_on_diagonal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        elements = route_elements_from_request(request)
        for element in elements:
            if element["originIndex"] == element["destinationIndex"]:
                element.pop("distanceMeters")
        return httpx.Response(200, json=elements)

    matrix = run(provider_for(handler).compute_matrix(locations(), RoutingOptions()))

    assert matrix.distance_meters == ((0, 1_020), (2_010, 0))
    assert matrix.duration_seconds == ((0, 102), (201, 0))


def test_matrix_rejects_omitted_distance_off_diagonal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        elements = route_elements_from_request(request)
        next(
            element
            for element in elements
            if element["originIndex"] == 0 and element["destinationIndex"] == 1
        ).pop("distanceMeters")
        return httpx.Response(200, json=elements)

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).compute_matrix(locations(), RoutingOptions()))

    assert error.value.code == RoutingErrorCode.INVALID_RESPONSE


def test_batched_matrix_reassembles_global_order() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=route_elements_from_request(request))

    limits = RoutingLimits(maximum_origins=2, maximum_destinations=2, maximum_elements=4)
    matrix = run(
        provider_for(handler, limits=limits).compute_matrix(locations(5), RoutingOptions())
    )

    assert call_count == 9
    assert matrix.distance_meters[0][4] == 1_050
    assert matrix.distance_meters[4][0] == 5_010
    assert matrix.distance_meters[3][3] == 0


@pytest.mark.parametrize("failure_status", [429, 503])
def test_transient_http_failures_retry_then_succeed(failure_status: int) -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(failure_status, json={"error": "temporary"})
        return httpx.Response(200, json=route_elements_from_request(request))

    matrix = run(
        provider_for(handler, delays=delays).compute_matrix(locations(1), RoutingOptions())
    )

    assert matrix.distance_meters == ((0,),)
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_invalid_key_fails_once_without_exposing_key(caplog: pytest.LogCaptureFixture) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(403, text=f"denied key={TEST_KEY}")

    provider = provider_for(handler)
    with caplog.at_level(logging.WARNING), pytest.raises(RoutingProviderError) as error:
        run(provider.compute_matrix(locations(1), RoutingOptions()))

    assert error.value.code == RoutingErrorCode.AUTH_ERROR
    assert attempts == 1
    assert TEST_KEY not in str(error.value)
    assert TEST_KEY not in caplog.text
    assert TEST_KEY not in repr(provider)


def test_geocoding_auth_failure_suppresses_key_bearing_request_context() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).geocode(["Plant Road"]))

    rendered_traceback = "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    assert error.value.code == RoutingErrorCode.AUTH_ERROR
    assert TEST_KEY not in rendered_traceback


def test_timeout_retries_are_bounded() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler, delays=delays).compute_matrix(locations(1), RoutingOptions()))

    assert error.value.code == RoutingErrorCode.TIMEOUT
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_geocoding_api_quota_status_retries_are_bounded() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json={"status": "OVER_QUERY_LIMIT", "results": []})

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).geocode(["Plant Road"]))

    assert error.value.code == RoutingErrorCode.RATE_LIMIT
    assert attempts == 3


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"status": "ZERO_RESULTS", "results": []}, RoutingErrorCode.GEOCODE_NOT_FOUND),
        ({"status": "OK", "results": []}, RoutingErrorCode.INVALID_RESPONSE),
        (
            {"status": "OK", "results": [{"formatted_address": "Missing coordinates"}]},
            RoutingErrorCode.INVALID_RESPONSE,
        ),
    ],
)
def test_geocoding_not_found_and_malformed_results_fail_cleanly(
    payload: dict[str, Any],
    expected_code: RoutingErrorCode,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).geocode(["Plant Road"]))

    assert error.value.code == expected_code


@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    [
        (
            lambda _request: httpx.Response(200, content=b"not-json"),
            RoutingErrorCode.INVALID_RESPONSE,
        ),
        (
            lambda _request: httpx.Response(200, json={"not": "a list"}),
            RoutingErrorCode.INVALID_RESPONSE,
        ),
        (lambda _request: httpx.Response(200, json=[]), RoutingErrorCode.PARTIAL_RESPONSE),
    ],
)
def test_malformed_and_partial_matrix_responses_fail_closed(
    response_factory: Callable[[httpx.Request], httpx.Response],
    expected_code: RoutingErrorCode,
) -> None:
    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(response_factory).compute_matrix(locations(1), RoutingOptions()))

    assert error.value.code == expected_code


def test_unreachable_required_leg_fails_entire_matrix() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "originIndex": 0,
                    "destinationIndex": 0,
                    "status": {"code": 5, "message": "not found"},
                    "condition": "ROUTE_NOT_FOUND",
                }
            ],
        )

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).compute_matrix(locations(1), RoutingOptions()))

    assert error.value.code == RoutingErrorCode.UNREACHABLE_ROUTE


def test_duplicate_and_out_of_range_elements_are_rejected() -> None:
    duplicate = {
        "originIndex": 0,
        "destinationIndex": 0,
        "status": {},
        "condition": "ROUTE_EXISTS",
        "distanceMeters": 0,
        "duration": "0s",
    }

    def duplicate_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[duplicate, duplicate, duplicate, duplicate])

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(duplicate_handler).compute_matrix(locations(2), RoutingOptions()))
    assert error.value.code == RoutingErrorCode.INVALID_RESPONSE


def test_scenario_g_error_codes_are_implemented() -> None:
    from backend.tests.fixtures.canonical import load_json

    fixture = load_json("scenario_g_routing_failures.json")
    expected_codes = {
        case["expected"].get("error_code")
        for case in fixture["cases"]
        if case["expected"].get("error_code")
    }
    implemented_codes = {code.value for code in RoutingErrorCode}

    assert expected_codes <= implemented_codes


def test_provider_factory_requires_key_without_loading_local_env() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(RoutingProviderError) as error:
        google_provider_from_settings(settings)

    assert error.value.code == RoutingErrorCode.CONFIGURATION_ERROR
