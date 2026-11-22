"""A scenario at the documented size limits, built the way the forms build it (V1.1-M7).

The documented sizes (``docs/troubleshooting.md`` → "Scenario size"):

- **Travel times:** up to 100 locations in one calculation (the API's limit).
- **Planning:** 100 locations, 20 trucks on weekday shifts for a week (100 truck-shifts),
  and 300 POs plan completely at the default 10 s time limit.
- **Requests:** up to 1,000 tasks and 200 locations per request (``API_MAX_TASKS``,
  ``API_MAX_LOCATIONS``), within ``API_MAX_REQUEST_BYTES``.

Every row goes through the same state functions the Scenario, Locations, Fleet, and Tasks
forms call, so the test exercises the forms' rules at size. Coordinates are seeded and
spread over about 90 km by 80 km around a Mississauga plant; the travel times are road
distance at 1.3 times the straight line, driven at 50 km/h.
"""

from __future__ import annotations

import math
import random
from datetime import date, time, timedelta
from typing import Any

from backend.app.domain import GeocodeLocationType
from backend.app.domain.models import RoutingMatrix
from backend.app.routing import AddressResolution, FakeRoutingProvider, GeocodeCandidate
from frontend.state.fleet import add_vehicle, apply_generated_shifts, generate_shifts
from frontend.state.locations import add_location
from frontend.state.scenario_state import new_scenario
from frontend.state.settings import set_plant
from frontend.state.tasks import DROP, PICKUP, PICKUP_DROP, TaskFields, add_task

MAX_MATRIX_LOCATIONS = 100
DOCUMENTED_TRUCKS = 20
DOCUMENTED_POS = 300
MAX_REQUEST_TASKS = 1_000
MONDAY = date(2026, 12, 7)
WEEKDAYS = 5
PLANT = (43.5890, -79.6441)
MOVEMENTS = (PICKUP, DROP, PICKUP, DROP, PICKUP_DROP)

Coordinates = dict[str, tuple[float, float]]


def form_built_scenario(
    *,
    locations: int = MAX_MATRIX_LOCATIONS,
    trucks: int = DOCUMENTED_TRUCKS,
    tasks: int = DOCUMENTED_POS,
    seed: int = 7,
) -> tuple[dict[str, Any], Coordinates]:
    """The scenario and the coordinates its addresses resolve to."""
    rng = random.Random(seed)
    scenario = new_scenario(
        scenario_id="SIZE-CHECK", name="Size check", start_day=MONDAY, days=WEEKDAYS
    )
    scenario = set_plant(scenario, name="Main plant", address="1 Plant Rd, Mississauga, ON")
    for index in range(1, locations):
        kind = "Supplier" if index % 2 else "Customer"
        scenario = add_location(
            scenario, name=f"{kind} {index}", address=f"{index} Size Test St, Ontario"
        )
    coordinates: Coordinates = {}
    for row in scenario["locations"]:
        location_id = str(row["location_id"])
        coordinates[location_id] = (
            PLANT
            if location_id == scenario["plant_location_id"]
            else (PLANT[0] + rng.uniform(-0.4, 0.4), PLANT[1] + rng.uniform(-0.5, 0.5))
        )

    truck_ids: list[str] = []
    for index in range(1, trucks + 1):
        scenario, vehicle_id = add_vehicle(scenario, name=f"Truck {index}", capacity=26)
        truck_ids.append(vehicle_id)
    preview = generate_shifts(
        scenario,
        vehicle_ids=truck_ids,
        first_day=MONDAY,
        last_day=MONDAY + timedelta(days=WEEKDAYS - 1),
        weekdays=range(WEEKDAYS),
        start=time(6, 0),
        end=time(18, 0),
    )
    scenario = apply_generated_shifts(scenario, preview).scenario

    for index, fields in enumerate(_task_fields(scenario, tasks, rng)):
        scenario = add_task(scenario, fields, task_id=f"TASK-{index + 1:04d}").scenario
    return scenario, coordinates


def task_rows(scenario: dict[str, Any], count: int, *, seed: int = 11) -> list[dict[str, Any]]:
    """Task rows in the shape the task form writes, without the form's per-row checks.

    For request-limit tests only: adding 1,000 tasks one by one through the form
    functions is slow, and these tests are about the request, not the forms.
    """
    rows: list[dict[str, Any]] = []
    for index, fields in enumerate(_task_fields(scenario, count, random.Random(seed))):
        origin = fields.origin or scenario["plant_location_id"]
        destination = fields.destination or scenario["plant_location_id"]
        rows.append(
            {
                "task_id": f"TASK-{index + 1:04d}",
                "po_number": fields.po_number,
                "task_type": fields.movement,
                "origin_location_id": origin,
                "destination_location_id": destination,
                "quantity": fields.quantity,
                "ready_at": f"{fields.ready_day.isoformat()}T06:00:00",
                "due_at": f"{fields.due_day.isoformat()}T17:00:00",
                "due_event": "DELIVERY_COMPLETE",
                "pickup_service_minutes": fields.pickup_service_minutes,
                "delivery_service_minutes": fields.delivery_service_minutes,
                "priority": fields.priority,
            }
        )
    return rows


def _task_fields(scenario: dict[str, Any], count: int, rng: random.Random) -> list[TaskFields]:
    names = {str(row["location_id"]): str(row["name"]) for row in scenario["locations"]}
    suppliers = [key for key, name in names.items() if name.startswith("Supplier")]
    customers = [key for key, name in names.items() if name.startswith("Customer")]
    fields: list[TaskFields] = []
    for index in range(count):
        day = MONDAY + timedelta(days=index % WEEKDAYS)
        movement = MOVEMENTS[index % len(MOVEMENTS)]
        fields.append(
            TaskFields(
                po_number=f"PO-{index + 1:05d}",
                movement=movement,
                origin=rng.choice(suppliers) if movement != DROP else None,
                destination=rng.choice(customers) if movement != PICKUP else None,
                quantity=rng.choice((2, 4, 6, 8)),
                ready_day=day,
                ready_time=time(6, 0),
                due_day=day,
                due_time=time(17, 0),
                pickup_service_minutes=10,
                delivery_service_minutes=10,
                priority=rng.randint(1, 5),
            )
        )
    return fields


def road_matrix(coordinates: Coordinates) -> RoutingMatrix:
    """Road distance about 1.3 times the straight line, driven at 50 km/h."""
    ids = tuple(coordinates)

    def km(first: str, second: str) -> float:
        (lat_1, lon_1), (lat_2, lon_2) = coordinates[first], coordinates[second]
        x = math.radians(lon_2 - lon_1) * math.cos(math.radians((lat_1 + lat_2) / 2))
        return 6_371 * math.hypot(x, math.radians(lat_2 - lat_1)) * 1.3

    distances = tuple(tuple(round(km(a, b) * 1_000) for b in ids) for a in ids)
    durations = tuple(tuple(round(m / 1_000 / 50 * 3_600) for m in row) for row in distances)
    return RoutingMatrix(
        location_ids=ids, distance_meters=distances, duration_seconds=durations, source="fake"
    )


def fake_provider(scenario: dict[str, Any], coordinates: Coordinates) -> FakeRoutingProvider:
    """Answers every address with one rooftop match, and serves the road matrix."""
    return FakeRoutingProvider(
        matrix=road_matrix(coordinates),
        resolutions={
            str(row["address"]): AddressResolution(
                (
                    GeocodeCandidate(
                        formatted_address=f"{row['address']}, Canada",
                        latitude=coordinates[str(row["location_id"])][0],
                        longitude=coordinates[str(row["location_id"])][1],
                        place_id=f"place-{row['location_id']}",
                        location_type=GeocodeLocationType.ROOFTOP,
                    ),
                )
            )
            for row in scenario["locations"]
        },
    )


def with_coordinates(scenario: dict[str, Any], coordinates: Coordinates) -> dict[str, Any]:
    """The scenario with coordinates supplied in JSON, as an integration would send it."""
    located = dict(scenario)
    located["locations"] = [
        {
            **row,
            "latitude": coordinates[str(row["location_id"])][0],
            "longitude": coordinates[str(row["location_id"])][1],
        }
        for row in scenario["locations"]
    ]
    return located
