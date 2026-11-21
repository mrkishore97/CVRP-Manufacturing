"""V1.1-M4 gate: a complete scenario is built and solved without opening JSON.

The real ``frontend/streamlit_app.py`` drives the real backend in-process over HTTP,
starting from an empty scenario. Every input goes through a form: scenario details and
plant, locations by address, trucks (one refrigerated), shifts from the generator, and
all three task movements. The backend validates the result, travel times come from
the offline fake provider, and the solver returns a feasible plan that honours the
truck tags. The Advanced JSON page is never visited.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import date, time
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
from frontend.tests.form_driver import (
    add_task,
    add_truck,
    click,
    click_starting,
    generate_shifts,
    ok,
    scenario,
    workspace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
MONDAY = date(2026, 12, 7)
TUESDAY = date(2026, 12, 8)
PLACES = {
    # location ID: (name, address, latitude, longitude)
    "PLANT": ("Main plant", "300 City Centre Dr, Mississauga, ON L5B 3C1", 43.5890, -79.6441),
    "BRAMPTON-SUPPLIER": (
        "Brampton supplier",
        "2 Wellington St W, Brampton, ON L6Y 4R2",
        43.6853,
        -79.7594,
    ),
    "VAUGHAN-SUPPLIER": (
        "Vaughan supplier",
        "2141 Major Mackenzie Dr, Vaughan, ON L6A 1T1",
        43.8563,
        -79.5085,
    ),
    "TORONTO-CUSTOMER": (
        "Toronto customer",
        "100 Queen St W, Toronto, ON M5H 2N2",
        43.6534,
        -79.3841,
    ),
    "MARKHAM-CUSTOMER": (
        "Markham customer",
        "101 Town Centre Blvd, Markham, ON L3R 9W3",
        43.8561,
        -79.3370,
    ),
}
LOCATION_IDS = tuple(PLACES)


def _matrix() -> RoutingMatrix:
    """Road distance about 1.3 times the straight line, driven at 50 km/h."""

    def km(first: str, second: str) -> float:
        _, _, lat_1, lon_1 = PLACES[first]
        _, _, lat_2, lon_2 = PLACES[second]
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
            address: AddressResolution(
                (
                    GeocodeCandidate(
                        formatted_address=f"{address}, Canada",
                        latitude=latitude,
                        longitude=longitude,
                        place_id=f"place-{location_id}",
                        location_type=GeocodeLocationType.ROOFTOP,
                    ),
                )
            )
            for location_id, (_, address, latitude, longitude) in PLACES.items()
        },
    )


@pytest.fixture
def app(
    provider: FakeRoutingProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[AppTest]:
    values: dict[str, Any] = {
        "app_environment": "test",
        "database_path": tmp_path / "m4.db",
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
        ok(test_app)
        yield test_app


VISITED: list[str] = []


def _go(app: AppTest, page: str) -> None:
    VISITED.append(page)
    app.button(key=f"nav-{page}").click().run()
    ok(app)


def _text(app: AppTest, label: str, value: str, key_part: str | None = None) -> None:
    widget = next(
        widget
        for widget in app.text_input
        if widget.label == label and (key_part is None or key_part in str(widget.key))
    )
    widget.input(value)


def _validation(app: AppTest) -> dict[str, Any]:
    validation = workspace(app).derived.validation
    assert isinstance(validation, dict)
    return validation


def test_a_complete_scenario_is_built_and_solved_without_opening_json(
    app: AppTest, provider: FakeRoutingProvider
) -> None:
    VISITED.clear()
    # Scenario page: a new empty scenario, its name, and the plant.
    click(app, "Start a new empty scenario")
    _text(app, "Scenario name", "Week 50 forms")
    click(app, "Save details")
    name, address, _, _ = PLACES["PLANT"]
    _text(app, "Plant name", name)
    _text(app, "Plant address", address)
    click(app, "Save plant")

    # Locations: name and address only, then one resolve.
    _go(app, "locations")
    for location_id in LOCATION_IDS[1:]:
        name, address, _, _ = PLACES[location_id]
        _text(app, "Name", name, "add_location")
        _text(app, "Address", address, "add_location")
        click(app, "Add location")
    assert [row["location_id"] for row in scenario(app)["locations"]] == list(LOCATION_IDS)
    click_starting(app, "Resolve addresses (")
    assert provider.resolve_call_count == len(LOCATION_IDS)

    # Fleet: two trucks and two days of generated shifts.
    _go(app, "fleet")
    add_truck(app, name="Truck 1", capacity=12)
    add_truck(app, name="Reefer 1", capacity=8, tags="refrigerated", max_km=400)
    generate_shifts(
        app, trucks=["TRUCK-1", "REEFER-1"], first=MONDAY, last=TUESDAY, weekdays=(0, 1)
    )
    assert len(scenario(app)["vehicle_shifts"]) == 4

    # Tasks: all three movements, one needing the refrigerated truck.
    _go(app, "tasks")
    add_task(
        app,
        movement="PICKUP",
        po="PO-5001",
        origin="BRAMPTON-SUPPLIER",
        quantity=6,
        day=MONDAY,
        ready=time(8, 0),
        due=time(13, 0),
        priority=3,
    )
    add_task(
        app,
        movement="DROP",
        po="PO-5002",
        destination="TORONTO-CUSTOMER",
        quantity=4,
        day=MONDAY,
        ready=time(7, 0),
        due=time(12, 0),
        tags=["REFRIGERATED"],
    )
    add_task(
        app,
        movement="PICKUP_DROP",
        po="PO-5003",
        origin="VAUGHAN-SUPPLIER",
        destination="MARKHAM-CUSTOMER",
        quantity=5,
        day=TUESDAY,
        ready=time(9, 0),
        due=time(15, 0),
    )
    assert [task["task_id"] for task in scenario(app)["tasks"]] == [
        "TASK-0001",
        "TASK-0002",
        "TASK-0003",
    ]

    # Review: the backend accepts every form-built row.
    _go(app, "review")
    validation = _validation(app)
    assert validation["valid"] is True, validation["issues"]
    assert [issue for issue in validation["issues"] if issue["severity"] == "ERROR"] == []

    # Travel times and the plan.
    _go(app, "travel_times")
    click(app, "Calculate travel times")
    assert provider.matrix_call_count == 1
    _go(app, "optimize")
    click(app, "Solve route plan")
    plan = workspace(app).derived.plan
    assert plan is not None
    assert plan["status"] == "FEASIBLE", plan.get("diagnostics")
    assert sorted(plan["scheduled_task_ids"]) == ["TASK-0001", "TASK-0002", "TASK-0003"]
    cold_route = next(
        route
        for route in plan["routes"]
        if any(stop.get("task_id") == "TASK-0002" for stop in route["stops"])
    )
    assert cold_route["vehicle_id"] == "REEFER-1"

    assert "json" not in VISITED
