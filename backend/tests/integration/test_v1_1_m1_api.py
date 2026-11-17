"""V1.1-M1 API tests: address resolution, matrix estimate, and configuration.

Every provider here is the fake provider or the Google adapter over mocked HTTP,
so no key or network is needed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain import GeocodeLocationType
from backend.app.domain.geocoding import normalize_address
from backend.app.domain.models import RoutingMatrix
from backend.app.persistence import (
    SQLiteDatabase,
    SQLiteGeocodeCache,
    build_geocode_cache_key,
)
from backend.app.routing import (
    AddressResolution,
    FakeRoutingProvider,
    GeocodeCandidate,
    GoogleRoutingProvider,
    RoutingErrorCode,
    RoutingLocation,
    RoutingProviderError,
)

PLANT_ADDRESS = "100 Fixture Plant Road, Toronto, ON"
SUPPLIER_ADDRESS = "200 Supplier Avenue, Vaughan, ON"
VAGUE_ADDRESS = "Vaughan, ON"
UNKNOWN_ADDRESS = "999 Nowhere Lane, Atlantis"
SENTINEL_KEY = "m1-sentinel-key-do-not-log"


def _settings(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "api.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    values.update(updates)
    return Settings(**values)


def _candidate(
    formatted: str,
    latitude: float,
    longitude: float,
    place_id: str,
    location_type: GeocodeLocationType = GeocodeLocationType.ROOFTOP,
) -> GeocodeCandidate:
    return GeocodeCandidate(
        formatted_address=formatted,
        latitude=latitude,
        longitude=longitude,
        place_id=place_id,
        location_type=location_type,
    )


RESOLUTIONS = {
    PLANT_ADDRESS: AddressResolution(
        (_candidate("100 Fixture Plant Rd, Toronto, ON, Canada", 43.7, -79.4, "plant-place"),)
    ),
    SUPPLIER_ADDRESS: AddressResolution(
        (_candidate("200 Supplier Ave, Vaughan, ON, Canada", 43.82, -79.5, "supplier-place"),)
    ),
    VAGUE_ADDRESS: AddressResolution(
        (
            _candidate(
                "Vaughan, ON, Canada",
                43.84,
                -79.51,
                "vaughan-place",
                GeocodeLocationType.APPROXIMATE,
            ),
        )
    ),
}


def _matrix() -> RoutingMatrix:
    return RoutingMatrix(
        location_ids=("PLANT", "SUPPLIER_A"),
        distance_meters=((0, 28_000), (27_000, 0)),
        duration_seconds=((0, 1_800), (1_700, 0)),
        source="fake",
    )


def _app(tmp_path: Path, **settings: Any) -> tuple[FastAPI, FakeRoutingProvider]:
    provider = FakeRoutingProvider(
        geocodes={
            PLANT_ADDRESS: RoutingLocation(
                "PLANT", "100 Fixture Plant Rd, Toronto, ON, Canada", 43.7, -79.4, "plant-place"
            )
        },
        matrix=_matrix(),
        resolutions=RESOLUTIONS,
    )
    app = create_app(_settings(tmp_path, **settings))
    app.state.routing_provider = provider
    return app, provider


def _resolve_body(*rows: tuple[str, str], **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "locations": [{"location_id": lid, "address": address} for lid, address in rows],
        "plant_location_id": "PLANT",
    }
    body.update(extra)
    return body


def _address_only_payload() -> dict[str, Any]:
    return {
        "scenario_id": "ADDRESS-ONLY",
        "timezone": "America/Toronto",
        "planning_horizon": {"start": "2026-06-22T07:00:00", "end": "2026-06-22T17:00:00"},
        "plant_location_id": "PLANT",
        "locations": [
            {"location_id": "PLANT", "name": "Plant", "address": PLANT_ADDRESS},
            {"location_id": "SUPPLIER_A", "name": "Supplier A", "address": SUPPLIER_ADDRESS},
        ],
        "vehicles": [{"vehicle_id": "TRUCK-1", "name": "Truck 1", "capacity": 12}],
        "vehicle_shifts": [
            {
                "shift_id": "TRUCK-1-20260622",
                "vehicle_id": "TRUCK-1",
                "start": "2026-06-22T07:00:00",
                "end": "2026-06-22T17:00:00",
            }
        ],
        "tasks": [
            {
                "task_id": "TASK-0001",
                "po_number": "PO-0001",
                "task_type": "PICKUP",
                "origin_location_id": "SUPPLIER_A",
                "destination_location_id": "PLANT",
                "quantity": 4,
                "ready_at": "2026-06-22T07:00:00",
                "due_at": "2026-06-22T12:30:00",
                "due_event": "DELIVERY_COMPLETE",
                "pickup_service_minutes": 15,
                "delivery_service_minutes": 15,
            }
        ],
    }


def _apply_resolution(location: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """What the frontend will do in M3: store the derived fields beside the address."""
    return {
        **location,
        "formatted_address": result["formatted_address"],
        "place_id": result["place_id"],
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "geocode_status": result["status"],
        "geocode_source_fingerprint": result["geocode_source_fingerprint"],
        "geocoded_at": result["geocoded_at"],
        "geocode_location_type": result["location_type"],
        "geocode_partial_match": result["partial_match"],
        "geocode_confirmed": result["geocode_confirmed"],
    }


def _codes(validation: dict[str, Any]) -> list[str]:
    return [issue["code"] for issue in validation["issues"]]


def test_address_only_scenario_resolves_validates_and_solves(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    payload = _address_only_payload()
    with TestClient(app) as client:
        first_validation = client.post("/api/v1/plans/validate", json=payload).json()
        resolved = client.post(
            "/api/v1/locations/resolve",
            json=_resolve_body(
                *((loc["location_id"], loc["address"]) for loc in payload["locations"])
            ),
        )
        results = {row["location_id"]: row for row in resolved.json()["results"]}
        payload["locations"] = [
            _apply_resolution(location, results[location["location_id"]])
            for location in payload["locations"]
        ]
        second_validation = client.post("/api/v1/plans/validate", json=payload).json()
        matrix_locations = [
            {
                "location_id": location["location_id"],
                "formatted_address": location["formatted_address"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "place_id": location["place_id"],
            }
            for location in payload["locations"]
        ]
        estimate_before = client.post(
            "/api/v1/matrices/estimate", json={"locations": matrix_locations}
        ).json()
        matrix = client.post("/api/v1/matrices/compute", json={"locations": matrix_locations})
        estimate_after = client.post(
            "/api/v1/matrices/estimate", json={"locations": matrix_locations}
        ).json()
        payload["routing_matrix"] = matrix.json()["matrix"]
        solved = client.post("/api/v1/plans/solve", json=payload)

    assert first_validation["validation"]["valid"] is True
    assert resolved.status_code == 200
    assert [row["status"] for row in resolved.json()["results"]] == ["RESOLVED", "RESOLVED"]
    assert second_validation["validation"]["valid"] is True
    assert not {"STALE_GEOCODE", "GEOCODE_EXPIRED"} & set(_codes(second_validation["validation"]))
    assert estimate_before["cache_hit"] is False
    assert estimate_before["billable_element_count"] == 4
    assert estimate_after["cache_hit"] is True
    assert estimate_after["billable_element_count"] == 0
    assert solved.status_code == 200, solved.json()
    assert solved.json()["plan"]["status"] == "FEASIBLE"
    assert provider.resolve_call_count == 2
    assert provider.matrix_call_count == 1


def test_resolve_returns_rows_in_request_order_with_a_summary(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/locations/resolve",
            json=_resolve_body(
                ("VAGUE", VAGUE_ADDRESS),
                ("PLANT", PLANT_ADDRESS),
                ("GONE", UNKNOWN_ADDRESS),
                ("SUPPLIER_A", SUPPLIER_ADDRESS),
            ),
            headers={"X-Request-ID": "resolve-1"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["request_id"] == "resolve-1"
    assert body["region_code"] == "ca"
    assert [row["location_id"] for row in body["results"]] == [
        "VAGUE",
        "PLANT",
        "GONE",
        "SUPPLIER_A",
    ]
    assert [row["status"] for row in body["results"]] == [
        "NEEDS_REVIEW",
        "RESOLVED",
        "FAILED",
        "RESOLVED",
    ]
    assert body["results"][0]["reason_code"] == "LOW_PRECISION"
    assert body["results"][2]["reason_code"] == "ADDRESS_NOT_FOUND"
    assert body["results"][3]["geocode_source_fingerprint"].startswith("v1:ca:")
    assert body["results"][3]["geocoded_at"].endswith("Z")
    assert body["summary"] == {
        "resolved": 2,
        "needs_review": 1,
        "failed": 1,
        "cache_hits": 0,
        "provider_calls": 4,
        "unique_addresses": 4,
        "plant_distance_checked": True,
    }


def test_repeat_resolve_is_served_from_cache_unless_forced(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    body = _resolve_body(("PLANT", PLANT_ADDRESS), ("SUPPLIER_A", SUPPLIER_ADDRESS))
    with TestClient(app) as client:
        first = client.post("/api/v1/locations/resolve", json=body).json()
        second = client.post("/api/v1/locations/resolve", json=body).json()
        forced = client.post("/api/v1/locations/resolve", json={**body, "force_refresh": True})

    assert first["summary"]["provider_calls"] == 2
    assert second["summary"]["cache_hits"] == 2
    assert second["summary"]["provider_calls"] == 0
    assert all(row["cache_hit"] for row in second["results"])
    assert second["results"][1]["geocoded_at"] == first["results"][1]["geocoded_at"]
    assert forced.json()["summary"]["provider_calls"] == 2
    assert provider.resolve_call_count == 4


@pytest.mark.parametrize(
    ("region_field", "expected_region"),
    [({}, "ca"), ({"region_code": "US"}, "us"), ({"region_code": ""}, None)],
)
def test_region_bias_defaults_to_settings_and_can_be_overridden(
    tmp_path: Path, region_field: dict[str, Any], expected_region: str | None
) -> None:
    app, provider = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/locations/resolve",
            json=_resolve_body(("SUPPLIER_A", SUPPLIER_ADDRESS), **region_field),
        )

    assert response.status_code == 200
    assert response.json()["region_code"] == expected_region
    assert provider.resolve_requests == [(SUPPLIER_ADDRESS, expected_region)]


@pytest.mark.parametrize(
    "body",
    [
        _resolve_body(("A", SUPPLIER_ADDRESS), ("A", VAGUE_ADDRESS)),
        _resolve_body(("A", "   ")),
        _resolve_body(("A", SUPPLIER_ADDRESS), region_code="1x"),
        _resolve_body(("bad id!", SUPPLIER_ADDRESS)),
        {"locations": []},
    ],
)
def test_invalid_resolve_requests_are_rejected_without_provider_calls(
    tmp_path: Path, body: dict[str, Any]
) -> None:
    app, provider = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/v1/locations/resolve", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
    assert provider.resolve_call_count == 0


def test_resolve_row_limit_is_enforced(tmp_path: Path) -> None:
    app, provider = _app(tmp_path, api_max_geocode_addresses=2)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/locations/resolve",
            json=_resolve_body(
                ("PLANT", PLANT_ADDRESS),
                ("SUPPLIER_A", SUPPLIER_ADDRESS),
                ("VAGUE", VAGUE_ADDRESS),
            ),
        )

    assert response.status_code == 413
    assert response.json()["code"] == "RESOLVE_LIMIT_EXCEEDED"
    assert provider.resolve_call_count == 0


@pytest.mark.parametrize(
    "code",
    [RoutingErrorCode.AUTH_ERROR, RoutingErrorCode.RATE_LIMIT, RoutingErrorCode.TIMEOUT],
)
def test_provider_failure_fails_the_request_with_its_stable_code(
    tmp_path: Path, code: RoutingErrorCode
) -> None:
    provider = FakeRoutingProvider(
        resolve_error=RoutingProviderError(code, "Simulated provider failure.")
    )
    app = create_app(_settings(tmp_path))
    app.state.routing_provider = provider
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/locations/resolve",
            json=_resolve_body(("PLANT", PLANT_ADDRESS)),
            headers={"X-Request-ID": "resolve-fail"},
        )

    assert response.status_code == 502
    assert response.json()["code"] == code.value
    assert response.json()["request_id"] == "resolve-fail"


def test_resolve_without_a_key_reports_configuration_error(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/api/v1/locations/resolve", json=_resolve_body(("PLANT", PLANT_ADDRESS))
        )

    assert response.status_code == 502
    assert response.json()["code"] == RoutingErrorCode.CONFIGURATION_ERROR.value


def test_estimate_requires_confirmation_only_for_large_billable_matrices(tmp_path: Path) -> None:
    app, provider = _app(tmp_path, matrix_confirm_elements=3)
    locations = [
        {
            "location_id": "PLANT",
            "formatted_address": "Plant",
            "latitude": 43.7,
            "longitude": -79.4,
            "place_id": "plant-place",
        },
        {
            "location_id": "SUPPLIER_A",
            "formatted_address": "Supplier",
            "latitude": 43.82,
            "longitude": -79.5,
            "place_id": "supplier-place",
        },
    ]
    with TestClient(app) as client:
        before = client.post("/api/v1/matrices/estimate", json={"locations": locations}).json()
        client.post("/api/v1/matrices/compute", json={"locations": locations})
        after = client.post("/api/v1/matrices/estimate", json={"locations": locations}).json()
        duplicate = client.post(
            "/api/v1/matrices/estimate", json={"locations": [locations[0], locations[0]]}
        )

    assert {
        key: before[key]
        for key in (
            "location_count",
            "element_count",
            "request_count",
            "billable_element_count",
            "billable_request_count",
            "confirmation_threshold_elements",
            "confirmation_required",
            "cache_hit",
        )
    } == {
        "location_count": 2,
        "element_count": 4,
        "request_count": 1,
        "billable_element_count": 4,
        "billable_request_count": 1,
        "confirmation_threshold_elements": 3,
        "confirmation_required": True,
        "cache_hit": False,
    }
    assert after["cache_hit"] is True
    assert after["billable_request_count"] == 0
    assert after["confirmation_required"] is False
    assert after["cache_key"] == before["cache_key"]
    assert duplicate.status_code == 422
    assert provider.matrix_call_count == 1


def test_estimate_splits_large_matrices_into_provider_requests(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    locations = [
        {
            "location_id": f"LOC-{index}",
            "formatted_address": f"Location {index}",
            "latitude": 43.0 + index / 100,
            "longitude": -79.0,
        }
        for index in range(30)
    ]
    with TestClient(app) as client:
        estimate = client.post("/api/v1/matrices/estimate", json={"locations": locations}).json()

    assert estimate["element_count"] == 900
    assert estimate["request_count"] == 4
    assert estimate["confirmation_required"] is True
    assert provider.matrix_call_count == 0


def test_config_reports_settings_without_any_secret(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        without_key = client.get("/api/v1/config")
    with TestClient(
        create_app(_settings(tmp_path, google_maps_api_key=SENTINEL_KEY, geocode_region_code=""))
    ) as client:
        with_key = client.get("/api/v1/config")

    assert without_key.status_code == 200
    assert without_key.json()["google_maps_configured"] is False
    assert without_key.json()["geocode_region_code"] == "ca"
    assert without_key.json()["default_timezone"] == "America/Toronto"
    assert without_key.json()["geocode_cache_ttl_seconds"] == 2_592_000
    assert without_key.json()["matrix_confirm_elements"] == 400
    assert without_key.json()["limits"]["max_resolve_addresses"] == 100
    assert with_key.json()["google_maps_configured"] is True
    assert with_key.json()["geocode_region_code"] is None
    assert SENTINEL_KEY not in with_key.text


def test_no_key_or_address_in_responses_logs_or_cache_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        address = request.url.params["address"]
        if address == UNKNOWN_ADDRESS:
            return httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
        if address.startswith("DENY"):
            return httpx.Response(200, json={"status": "REQUEST_DENIED", "results": []})
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "200 Supplier Ave, Vaughan, ON, Canada",
                        "place_id": "supplier-place",
                        "geometry": {
                            "location": {"lat": 43.82, "lng": -79.5},
                            "location_type": "ROOFTOP",
                        },
                    }
                ],
            },
        )

    settings = _settings(tmp_path, google_maps_api_key=SENTINEL_KEY)
    app = create_app(settings)
    app.state.routing_provider = GoogleRoutingProvider(
        api_key=SENTINEL_KEY,
        geocoding_url="https://google.test/geocode",
        maximum_attempts=1,
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        responses = [
            client.get("/api/v1/config"),
            client.post(
                "/api/v1/locations/resolve",
                json=_resolve_body(("SUPPLIER_A", SUPPLIER_ADDRESS), ("GONE", UNKNOWN_ADDRESS)),
            ),
            client.post(
                "/api/v1/locations/resolve",
                json=_resolve_body(("DENIED", "DENY 1 Secret Street")),
            ),
            client.post("/api/v1/locations/geocode", json={"addresses": [SUPPLIER_ADDRESS]}),
        ]

    assert [response.status_code for response in responses] == [200, 200, 502, 200]
    assert responses[2].json()["code"] == RoutingErrorCode.AUTH_ERROR.value
    for response in responses:
        assert SENTINEL_KEY not in response.text
    assert SENTINEL_KEY not in caplog.text
    for address in (SUPPLIER_ADDRESS, UNKNOWN_ADDRESS, "Secret Street"):
        assert address not in caplog.text
    database_bytes = settings.database_path.read_bytes()
    assert SENTINEL_KEY.encode() not in database_bytes
    assert SUPPLIER_ADDRESS.encode() not in database_bytes
    assert normalize_address(SUPPLIER_ADDRESS).encode() not in database_bytes


def test_legacy_geocode_endpoint_is_unchanged(tmp_path: Path) -> None:
    app, provider = _app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        found = client.post("/api/v1/locations/geocode", json={"addresses": [PLANT_ADDRESS]})
        missing = client.post("/api/v1/locations/geocode", json={"addresses": [UNKNOWN_ADDRESS]})

    assert found.status_code == 200
    assert set(found.json()) == {"request_id", "locations"}
    assert found.json()["locations"] == [
        {
            "location_id": "PLANT",
            "formatted_address": "100 Fixture Plant Rd, Toronto, ON, Canada",
            "latitude": 43.7,
            "longitude": -79.4,
            "place_id": "plant-place",
        }
    ]
    assert missing.status_code == 502
    assert missing.json()["code"] == "FAKE_GEOCODE_NOT_FOUND"
    assert provider.resolve_call_count == 0
    assert provider.geocode_call_count == 2


def test_openapi_schema_lists_the_new_endpoints(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/openapi.json")

    paths = response.json()["paths"]
    assert response.status_code == 200
    for path in ("/api/v1/locations/resolve", "/api/v1/matrices/estimate", "/api/v1/config"):
        assert path in paths
    assert "/api/v1/locations/geocode" in paths


def test_backend_start_purges_expired_geocodes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    old = datetime.now(UTC) - timedelta(days=31)
    cache = SQLiteGeocodeCache(SQLiteDatabase(settings.database_path), now=lambda: old)
    for address, fetched_at in ((PLANT_ADDRESS, old), (SUPPLIER_ADDRESS, datetime.now(UTC))):
        cache.set(
            build_geocode_cache_key(
                provider_name="fake",
                region_code="ca",
                normalized_address=normalize_address(address),
            ),
            RESOLUTIONS[address],
            fetched_at=fetched_at,
        )

    with TestClient(create_app(settings)):
        pass

    with SQLiteDatabase(settings.database_path).connect() as connection:
        remaining = connection.execute("SELECT COUNT(*) FROM geocode_cache").fetchone()[0]
    assert remaining == 1
