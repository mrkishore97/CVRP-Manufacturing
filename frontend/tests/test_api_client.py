"""Frontend API-client behavior tests."""

import json

import httpx
import pytest

from frontend.api_client import (
    BackendApiError,
    BackendClient,
    BackendResponseError,
    BackendTimeoutError,
    BackendUnavailableError,
)


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
