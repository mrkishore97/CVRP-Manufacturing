"""V1.1-M7: Google's own reason for a rejection reaches the planner, safely.

Version 1.0 reported only "rejected the request with HTTP 400", which left a real Routes
rejection undiagnosable. The reason from Google's error body is now added to the error
message, with the key removed, on one line, and bounded. It is never logged. A departure
time in the past, which Google rejects for driving, is refused before anything is sent.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.app.routing import (
    GoogleRoutingProvider,
    RoutingErrorCode,
    RoutingOptions,
    RoutingProviderError,
)
from backend.app.routing.google import MAX_PROVIDER_REASON_LENGTH, provider_reason
from backend.tests.integration.routing.test_google_provider import (
    TEST_KEY,
    locations,
    provider_for,
    route_elements_from_request,
    run,
)

FAKE_GOOGLE_KEY = "AIza" + "Q" * 35
NOW = datetime(2026, 12, 7, 12, 0, tzinfo=UTC)


def _error(status_code: int, message: str, status: str) -> httpx.Response:
    body = {"error": {"code": status_code, "message": message, "status": status}}
    return httpx.Response(status_code, json=body)


def test_a_routes_rejection_carries_googles_reason(caplog: pytest.LogCaptureFixture) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return _error(400, "Timestamp must be set to a future time.", "INVALID_ARGUMENT")

    with caplog.at_level(logging.DEBUG), pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).compute_matrix(locations(2), RoutingOptions()))

    assert error.value.code == RoutingErrorCode.INVALID_REQUEST
    assert attempts == 1  # a 400 is not retried
    assert str(error.value) == (
        "Google route matrix rejected the request with HTTP 400. "
        "Google says: Timestamp must be set to a future time."
    )
    assert "future time" not in caplog.text  # the reason is shown, never logged


def test_an_auth_rejection_reason_names_the_cause_but_never_the_key() -> None:
    message = (
        f"API key {FAKE_GOOGLE_KEY} (also sent as {TEST_KEY}) is not authorized.\n"
        "Request received from IP address 203.0.113.7."
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return _error(403, message, "PERMISSION_DENIED")

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).compute_matrix(locations(2), RoutingOptions()))

    text = str(error.value)
    assert error.value.code == RoutingErrorCode.AUTH_ERROR
    assert "203.0.113.7" in text  # the IP restriction to fix
    assert TEST_KEY not in text
    assert FAKE_GOOGLE_KEY not in text
    assert "\n" not in text


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(
                400, json=[{"error": {"code": 400, "message": "Bad origins.", "status": "X"}}]
            ),
            "Google says: Bad origins.",
        ),
        (httpx.Response(400, text="<html>Bad Request</html>"), None),
        (httpx.Response(400, json={"error": "unexpected shape"}), None),
    ],
)
def test_the_reason_is_read_from_googles_error_shapes(
    response: httpx.Response, expected: str | None
) -> None:
    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(lambda _r: response).compute_matrix(locations(2), RoutingOptions()))

    text = str(error.value)
    assert text.startswith("Google route matrix rejected the request with HTTP 400.")
    if expected is None:
        assert "Google says" not in text
    else:
        assert text.endswith(expected)


def test_a_long_reason_is_cut_to_one_bounded_line() -> None:
    reason = provider_reason("word  " * 200 + "\n" + "tail", secret=TEST_KEY)
    assert reason is not None
    assert len(reason) == MAX_PROVIDER_REASON_LENGTH
    assert reason.endswith("…")
    assert "\n" not in reason and "  " not in reason
    assert provider_reason("   ", secret=TEST_KEY) is None
    assert provider_reason(None, secret=TEST_KEY) is None


def test_a_geocoding_denial_carries_googles_error_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "REQUEST_DENIED",
                "error_message": f"This IP is not authorized to use this API key {TEST_KEY}.",
                "results": [],
            },
        )

    with pytest.raises(RoutingProviderError) as error:
        run(provider_for(handler).resolve_address("300 City Centre Dr, Mississauga"))

    text = str(error.value)
    assert error.value.code == RoutingErrorCode.AUTH_ERROR
    assert "Google says: This IP is not authorized" in text
    assert TEST_KEY not in text


def _provider_at_noon(handler: Any) -> GoogleRoutingProvider:
    return GoogleRoutingProvider(
        api_key=TEST_KEY,
        geocoding_url="https://google.test/geocode",
        routes_matrix_url="https://google.test/matrix",
        transport=httpx.MockTransport(handler),
        now=lambda: NOW,
    )


def test_a_past_departure_time_is_refused_before_anything_is_sent() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=route_elements_from_request(request))

    past = RoutingOptions(departure_time=NOW - timedelta(minutes=1))
    with pytest.raises(RoutingProviderError) as error:
        run(_provider_at_noon(handler).compute_matrix(locations(2), past))

    assert error.value.code == RoutingErrorCode.INVALID_REQUEST
    assert "in the past" in str(error.value)
    assert "Travel times > Advanced" in str(error.value)
    assert sent == []

    future = RoutingOptions(departure_time=NOW + timedelta(hours=1))
    run(_provider_at_noon(handler).compute_matrix(locations(2), future))
    assert json.loads(sent[0].content)["departureTime"] == "2026-12-07T13:00:00Z"
