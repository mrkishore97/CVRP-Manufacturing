"""Frontend API-client behavior tests."""

import json
from collections.abc import Callable

import httpx
import pytest

from frontend.api_client import (
    BackendApiError,
    BackendClient,
    BackendResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
    OperationTimeouts,
)

# A response body every client method accepts, so timeout tests can call any operation.
_ANY_OPERATION_RESPONSE = {
    "status": "ok",
    "service": "backend",
    "version": "1.0.0",
    "environment": "test",
    "validation": {"valid": True, "issues": []},
    "plan": {"plan_id": "PLAN-1", "status": "FEASIBLE"},
    "default_timezone": "America/Toronto",
    "google_maps_configured": True,
    "geocode_region_code": "ca",
    "geocode_cache_ttl_seconds": 2_592_000,
    "geocode_max_plant_distance_km": 500.0,
    "matrix_confirm_elements": 400,
    "solver_time_limit_seconds": 10,
    "limits": {"max_locations": 200},
}

_OPERATIONS: dict[str, Callable[[BackendClient], object]] = {
    "health": lambda client: client.get_health(),
    "validate": lambda client: client.validate_plan({"scenario_id": "S"}),
    "geocode": lambda client: client.geocode(["100 Plant Road"]),
    "matrix": lambda client: client.compute_matrix([{"location_id": "PLANT"}]),
    "solve": lambda client: client.solve_plan({"scenario_id": "S"}),
    "get_plan": lambda client: client.get_plan("PLAN-1"),
    "export_plan": lambda client: client.export_plan("PLAN-1"),
    "save_scenario": lambda client: client.save_scenario({"scenario_id": "S"}),
    "load_scenario": lambda client: client.load_scenario("S"),
    "resolve": lambda client: client.resolve_locations([{"location_id": "P", "address": "x"}]),
    "estimate": lambda client: client.estimate_matrix([{"location_id": "PLANT"}]),
    "config": lambda client: client.get_config(),
}


def _timeout_seen_by(
    operation: Callable[[BackendClient], object],
    timeouts: OperationTimeouts | None = None,
) -> dict[str, float | None]:
    seen: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json=_ANY_OPERATION_RESPONSE, request=request)

    operation(
        BackendClient(
            "http://backend.test", transport=httpx.MockTransport(handler), timeouts=timeouts
        )
    )
    assert len(seen) == 1
    return seen[0]


@pytest.mark.parametrize(
    ("operation_name", "expected_seconds"),
    [
        ("health", 3.0),
        ("validate", 15.0),
        ("geocode", 60.0),
        ("matrix", 120.0),
        ("solve", 60.0),
        ("get_plan", 15.0),
        ("export_plan", 15.0),
        ("save_scenario", 15.0),
        ("load_scenario", 15.0),
        ("resolve", 60.0),
        ("estimate", 15.0),
        ("config", 15.0),
    ],
)
def test_each_operation_uses_its_own_timeout(operation_name: str, expected_seconds: float) -> None:
    timeout = _timeout_seen_by(_OPERATIONS[operation_name])

    assert timeout["read"] == expected_seconds
    assert timeout["write"] == expected_seconds
    assert timeout["pool"] == expected_seconds
    # A stopped backend is still reported quickly, whatever the operation.
    assert timeout["connect"] == min(expected_seconds, 5.0)


def test_only_the_health_check_keeps_the_short_timeout() -> None:
    """Regression for F8: every call used to time out after 3 seconds."""
    short = {
        name
        for name, operation in _OPERATIONS.items()
        if (_timeout_seen_by(operation)["read"] or 0.0) <= 3.0
    }

    assert short == {"health"}


def test_custom_timeouts_are_applied() -> None:
    timeouts = OperationTimeouts(solve=200.0, connect=2.0)

    timeout = _timeout_seen_by(_OPERATIONS["solve"], timeouts)

    assert timeout["read"] == 200.0
    assert timeout["connect"] == 2.0


@pytest.mark.parametrize("field", ["health", "validate", "geocode", "matrix", "solve", "connect"])
def test_non_positive_timeouts_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field} timeout must be positive"):
        OperationTimeouts(**{field: 0.0})


def test_health_client_parses_valid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "backend",
                "version": "0.1.0",
                "environment": "test",
            },
        )

    health = BackendClient(
        "http://backend.test",
        transport=httpx.MockTransport(handler),
    ).get_health()

    assert health.status == "ok"
    assert health.version == "0.1.0"


def test_health_client_reports_backend_unavailable_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = BackendClient("http://backend.test", transport=httpx.MockTransport(handler))

    with pytest.raises(BackendUnavailableError, match="backend is unavailable"):
        client.get_health()


def test_health_client_reports_http_failure_without_traceback_details() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    client = BackendClient("http://backend.test", transport=transport)

    with pytest.raises(BackendResponseError, match="HTTP 503"):
        client.get_health()


def test_client_reports_timeout_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = BackendClient("http://backend.test", transport=httpx.MockTransport(handler))

    with pytest.raises(BackendTimeoutError, match="timed out"):
        client.get_health()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"status": "ok"}),
        httpx.Response(
            200,
            json={
                "status": "down",
                "service": "backend",
                "version": "0.1.0",
                "environment": "test",
            },
        ),
    ],
)
def test_health_client_rejects_invalid_contract(response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    client = BackendClient("http://backend.test", transport=transport)

    with pytest.raises(BackendResponseError):
        client.get_health()


def test_validation_client_parses_success_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/plans/validate"
        assert json.loads(request.content.decode())["scenario_id"] == "SCENARIO-1"
        return httpx.Response(
            200,
            json={
                "request_id": "req-validate",
                "validation": {
                    "valid": True,
                    "issues": [],
                    "normalized_request": {"scenario_id": "SCENARIO-1", "tasks": []},
                },
            },
            headers={"X-Request-ID": "req-validate"},
            request=request,
        )

    response = BackendClient(
        "http://backend.test",
        transport=httpx.MockTransport(handler),
    ).validate_plan({"scenario_id": "SCENARIO-1"})

    assert response.request_id == "req-validate"
    assert response.validation is not None
    assert response.validation.valid
    assert response.validation.normalized_request == {"scenario_id": "SCENARIO-1", "tasks": []}


def test_matrix_client_sends_locations_and_force_refresh() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/matrices/compute"
        body = json.loads(request.content.decode())
        assert body["force_refresh"] is True
        assert body["locations"][0]["location_id"] == "PLANT"
        return httpx.Response(
            200,
            json={
                "request_id": "req-matrix",
                "matrix": {
                    "location_ids": ["PLANT"],
                    "distance_meters": [[0]],
                    "duration_seconds": [[0]],
                    "source": "fake",
                },
                "cache_hit": False,
                "cache_key": "cache-key",
            },
            request=request,
        )

    response = BackendClient(
        "http://backend.test",
        transport=httpx.MockTransport(handler),
    ).compute_matrix(
        [
            {
                "location_id": "PLANT",
                "formatted_address": "100 Plant Road",
                "latitude": 43.7,
                "longitude": -79.4,
            }
        ],
        force_refresh=True,
    )

    assert response.payload["matrix"]["source"] == "fake"
    assert response.payload["cache_key"] == "cache-key"


def test_solve_client_exposes_structured_validation_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/plans/solve"
        return httpx.Response(
            422,
            json={
                "request_id": "req-error",
                "code": "PLANNING_VALIDATION_FAILED",
                "message": "Planning payload did not pass domain validation.",
                "details": [
                    {
                        "code": "INVALID_VALUE",
                        "message": "due_at must be after ready_at.",
                        "field": "tasks.due_at",
                        "row_number": 2,
                        "task_id": "TASK-1",
                    }
                ],
            },
            headers={"X-Request-ID": "req-error"},
            request=request,
        )

    client = BackendClient("http://backend.test", transport=httpx.MockTransport(handler))

    with pytest.raises(BackendApiError) as error:
        client.solve_plan({"scenario_id": "SCENARIO-1"})

    assert error.value.status_code == 422
    assert error.value.code == "PLANNING_VALIDATION_FAILED"
    assert error.value.request_id == "req-error"
    assert error.value.details[0].field == "tasks.due_at"
    assert error.value.details[0].row_number == 2


def test_scenario_save_and_load_round_trip_client_payload() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    scenario_payload = {"scenario_id": "SCENARIO-ROUNDTRIP", "tasks": [{"task_id": "TASK-1"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == "POST":
            assert request.url.path == "/api/v1/scenarios"
            assert body == scenario_payload
            return httpx.Response(
                201,
                json={
                    "request_id": "req-save",
                    "scenario_id": "SCENARIO-ROUNDTRIP",
                    "payload": scenario_payload,
                    "created_at": "2026-06-22T10:00:00Z",
                    "updated_at": "2026-06-22T10:00:00Z",
                },
                request=request,
            )
        assert request.url.path == "/api/v1/scenarios/SCENARIO-ROUNDTRIP"
        return httpx.Response(
            200,
            json={
                "request_id": "req-load",
                "scenario_id": "SCENARIO-ROUNDTRIP",
                "payload": scenario_payload,
                "created_at": "2026-06-22T10:00:00Z",
                "updated_at": "2026-06-22T10:00:00Z",
            },
            request=request,
        )

    client = BackendClient("http://backend.test", transport=httpx.MockTransport(handler))

    save_response = client.save_scenario(scenario_payload)
    load_response = client.load_scenario("SCENARIO-ROUNDTRIP")

    assert save_response.payload["payload"] == scenario_payload
    assert load_response.payload["payload"] == scenario_payload
    assert calls == [
        ("POST", "/api/v1/scenarios", scenario_payload),
        ("GET", "/api/v1/scenarios/SCENARIO-ROUNDTRIP", None),
    ]


def _recording_client(
    response_body: dict[str, object],
) -> tuple[BackendClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=response_body, request=request)

    return BackendClient("http://backend.test", transport=httpx.MockTransport(handler)), seen


def test_resolve_client_sends_only_the_fields_given() -> None:
    client, seen = _recording_client({"request_id": "r", "results": [], "summary": {}})

    client.resolve_locations([{"location_id": "PLANT", "address": "100 Plant Road"}])
    client.resolve_locations(
        [{"location_id": "ACME", "address": "1 Acme Way", "confirmed_place_id": "p-1"}],
        plant_location_id="PLANT",
        plant_coordinates={"latitude": 43.7, "longitude": -79.4},
        region_code="",
        force_refresh=True,
    )

    assert seen[0].url.path == "/api/v1/locations/resolve"
    assert json.loads(seen[0].content) == {
        "locations": [{"location_id": "PLANT", "address": "100 Plant Road"}],
        "force_refresh": False,
    }
    assert json.loads(seen[1].content) == {
        "locations": [
            {"location_id": "ACME", "address": "1 Acme Way", "confirmed_place_id": "p-1"}
        ],
        "force_refresh": True,
        "plant_location_id": "PLANT",
        "plant_coordinates": {"latitude": 43.7, "longitude": -79.4},
        "region_code": "",
    }


def test_estimate_and_compute_send_routing_options_only_when_given() -> None:
    client, seen = _recording_client({"matrix": {}, "cache_hit": False})
    locations = [{"location_id": "PLANT"}]
    options = {"routing_preference": "TRAFFIC_AWARE"}

    client.estimate_matrix(locations)
    client.estimate_matrix(locations, options=options)
    client.compute_matrix(locations)
    client.compute_matrix(locations, options=options)

    assert [request.url.path for request in seen] == [
        "/api/v1/matrices/estimate",
        "/api/v1/matrices/estimate",
        "/api/v1/matrices/compute",
        "/api/v1/matrices/compute",
    ]
    bodies = [json.loads(request.content) for request in seen]
    assert bodies[0] == {"locations": locations}
    assert bodies[1] == {"locations": locations, "options": options}
    assert bodies[2] == {"locations": locations, "force_refresh": False}
    assert bodies[3] == {"locations": locations, "force_refresh": False, "options": options}


def test_config_client_parses_the_non_secret_settings() -> None:
    client, seen = _recording_client(_ANY_OPERATION_RESPONSE)

    config = client.get_config()

    assert seen[0].method == "GET"
    assert seen[0].url.path == "/api/v1/config"
    assert config.google_maps_configured is True
    assert config.geocode_region_code == "ca"
    assert config.matrix_confirm_elements == 400
    assert config.limits == {"max_locations": 200}


def test_config_client_rejects_an_incomplete_response() -> None:
    client, _ = _recording_client({"default_timezone": "America/Toronto"})

    with pytest.raises(BackendResponseError, match="config response"):
        client.get_config()
