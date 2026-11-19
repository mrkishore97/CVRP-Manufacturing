"""V1.1-M3 gate: from typed addresses to a current travel-time matrix and a plan.

The real ``frontend/streamlit_app.py`` drives the real backend in-process over HTTP.
The backend's routing provider is the offline fake, configured with answers for the
seven addresses of the address-only sample (V11-A), so no key or network is used.
No coordinate is ever typed: every one comes from address resolution.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain import GeocodeLocationType
from backend.app.domain.models import RoutingMatrix
from backend.app.routing import AddressResolution, FakeRoutingProvider, GeocodeCandidate
from frontend import api_client
from frontend.samples import load_sample_payload
from frontend.state.readiness import LocationReadiness, readiness_by_location
from frontend.state.workspace import Workspace

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
SAMPLE = load_sample_payload("V11A")
COORDINATES = {
    "PLANT": (43.5890, -79.6441),
    "BRAMPTON-SUPPLIER": (43.6853, -79.7594),
    "VAUGHAN-SUPPLIER": (43.8563, -79.5085),
    "HAMILTON-SUPPLIER": (43.2557, -79.8711),
    "TORONTO-CUSTOMER": (43.6534, -79.3841),
    "MARKHAM-CUSTOMER": (43.8561, -79.3370),
    "OAKVILLE-CUSTOMER": (43.4675, -79.6877),
}
REVIEW_ID = "HAMILTON-SUPPLIER"
LOCATION_IDS = tuple(location["location_id"] for location in SAMPLE["locations"])


def _resolution(location: dict[str, Any]) -> AddressResolution:
    latitude, longitude = COORDINATES[location["location_id"]]
    partial = location["location_id"] == REVIEW_ID
    return AddressResolution(
        (
            GeocodeCandidate(
                formatted_address=f"{location['address']}, Canada",
                latitude=latitude,
                longitude=longitude,
                place_id=f"place-{location['location_id']}",
                location_type=GeocodeLocationType.ROOFTOP,
                partial_match=partial,
            ),
        )
    )


def _matrix() -> RoutingMatrix:
    """Road distance about 1.3 times the straight line, driven at 50 km/h."""

    def km(first: str, second: str) -> float:
        (lat_1, lon_1), (lat_2, lon_2) = COORDINATES[first], COORDINATES[second]
        x = math.radians(lon_2 - lon_1) * math.cos(math.radians((lat_1 + lat_2) / 2))
        y = math.radians(lat_2 - lat_1)
        return 6_371 * math.hypot(x, y) * 1.3

    distances = tuple(
        tuple(round(km(origin, destination) * 1_000) for destination in LOCATION_IDS)
        for origin in LOCATION_IDS
    )
    durations = tuple(
        tuple(round(meters / 1_000 / 50 * 3_600) for meters in row) for row in distances
    )
    return RoutingMatrix(
        location_ids=LOCATION_IDS,
        distance_meters=distances,
        duration_seconds=durations,
        source="fake",
    )


@pytest.fixture
def provider() -> FakeRoutingProvider:
    return FakeRoutingProvider(
        matrix=_matrix(),
        resolutions={
            location["address"]: _resolution(location) for location in SAMPLE["locations"]
        },
    )


@pytest.fixture
def app(
    provider: FakeRoutingProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AppTest]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "m3.db",
        "google_maps_api_key": None,
        "_env_file": None,
    }
    backend = create_app(Settings(**values))
    backend.state.routing_provider = provider
    with TestClient(backend) as test_client:
        client = api_client.BackendClient("http://testserver", transport=test_client._transport)
        monkeypatch.setattr(
            api_client.BackendClient, "from_environment", classmethod(lambda cls: client)
        )
        test_app = AppTest.from_file(APP_PATH, default_timeout=60)
        test_app.run()
        _ok(test_app)
        next(box for box in test_app.selectbox if box.label == "Sample").set_value("V11A").run()
        _click(test_app, "Open sample")
        yield test_app


def _ok(app: AppTest) -> None:
    assert not app.exception, app.exception


def _click(app: AppTest, label: str) -> None:
    next(button for button in app.button if button.label == label).click().run()
    _ok(app)


def _go(app: AppTest, page: str) -> None:
    app.button(key=f"nav-{page}").click().run()
    _ok(app)


def _workspace(app: AppTest) -> Workspace:
    workspace = app.session_state["workspace"]
    assert isinstance(workspace, Workspace)
    return workspace


def _readiness(app: AppTest) -> dict[str, LocationReadiness]:
    return readiness_by_location(_workspace(app).scenario, now=datetime.now(UTC))


def _sidebar(app: AppTest) -> str:
    return " | ".join(element.value for element in app.sidebar.markdown)


def _resolve(app: AppTest) -> None:
    next(
        button for button in app.button if str(button.label).startswith("Resolve addresses (")
    ).click().run()
    _ok(app)


def test_typed_addresses_become_a_current_matrix_and_a_feasible_plan(
    app: AppTest, provider: FakeRoutingProvider
) -> None:
    assert "✅ Valid" in _sidebar(app)  # address-only JSON validates on the backend
    _go(app, "locations")
    _resolve(app)

    assert provider.resolve_call_count == 7  # one lookup per unique address
    readiness = _readiness(app)
    assert readiness[REVIEW_ID] is LocationReadiness.NEEDS_REVIEW
    assert sum(value is LocationReadiness.READY for value in readiness.values()) == 6
    assert "✅ Valid" in _sidebar(app)  # resolved fields pass the backend's Location model

    app.button(key=f"confirm-{REVIEW_ID}").click().run()
    _ok(app)
    assert set(_readiness(app).values()) == {LocationReadiness.READY}

    _go(app, "travel_times")
    assert any(m.label == "Billable elements" and m.value == "49" for m in app.metric)
    assert any(m.label == "Backend cache" and m.value == "Not cached" for m in app.metric)
    _click(app, "Calculate travel times")
    assert provider.matrix_call_count == 1
    assert "✅ Travel times current" in _sidebar(app)

    _go(app, "optimize")
    _click(app, "Solve route plan")
    plan = _workspace(app).derived.plan
    assert plan is not None
    assert plan["status"] == "FEASIBLE", plan.get("diagnostics")
    assert sorted(plan["scheduled_task_ids"]) == sorted(task["task_id"] for task in SAMPLE["tasks"])

    for location in _workspace(app).scenario["locations"]:
        assert location["geocode_source_fingerprint"].startswith("v1:ca:")
    calls = (provider.resolve_call_count, provider.matrix_call_count)
    for page in ("scenario", "locations", "fleet", "tasks", "review", "travel_times", "results"):
        _go(app, page)
    app.run()
    assert (provider.resolve_call_count, provider.matrix_call_count) == calls


def test_an_edited_address_is_resolved_alone_and_a_repeat_is_served_from_the_cache(
    app: AppTest, provider: FakeRoutingProvider
) -> None:
    _go(app, "locations")
    _resolve(app)
    original = next(
        location["address"]
        for location in SAMPLE["locations"]
        if location["location_id"] == "OAKVILLE-CUSTOMER"
    )
    app.selectbox(key="locations_edit_id").set_value("OAKVILLE-CUSTOMER").run()
    app.text_input(key="edit-OAKVILLE-CUSTOMER-address").input("1225 Trafalgar Road, Oakville")
    _click(app, "Save location")
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.NOT_RESOLVED
    assert any(str(b.label) == "Resolve addresses (1 pending)" for b in app.button)

    _resolve(app)
    assert provider.resolve_call_count == 8
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.FAILED  # not configured

    app.selectbox(key="locations_edit_id").set_value("OAKVILLE-CUSTOMER").run()
    app.text_input(key="edit-OAKVILLE-CUSTOMER-address").input(original)
    _click(app, "Save location")
    _resolve(app)

    assert provider.resolve_call_count == 8  # answered by the 30-day address cache
    assert _readiness(app)["OAKVILLE-CUSTOMER"] is LocationReadiness.READY
    assert any("from the 30-day cache" in str(s.value) for s in app.success)
