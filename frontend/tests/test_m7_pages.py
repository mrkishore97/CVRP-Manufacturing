"""V1.1-M7 hardening on the Locations and Travel times pages, through ``AppTest``.

- Addresses are resolved in requests no larger than the backend allows, plant first;
  a failure part-way keeps what was already resolved.
- A calculation the backend would refuse is explained before anything is sent: more
  locations than one calculation allows, or a departure time in the past (Google rejects
  it with HTTP 400, the error a planner met in M5 without a reason).
- The routing-options form refuses a departure time in the past.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend import api_client
from frontend.samples import load_sample_payload
from frontend.state.locations import merge_summaries, resolve_batches, result_coordinates
from frontend.tests.fake_backend import FakeBackend, coordinates_for, install
from frontend.tests.form_driver import click, go, ok, scenario

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = str(PROJECT_ROOT / "frontend" / "streamlit_app.py")
SAMPLE = load_sample_payload("V11A")
PLANT = str(SAMPLE["plant_location_id"])


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    return install(monkeypatch)


def _start(page: str, *, scenario_param: str | None = None) -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=30)
    app.query_params["page"] = page
    if scenario_param is not None:
        app.query_params["scenario"] = scenario_param
    app.run()
    ok(app)
    return app


def _open_address_sample(app: AppTest) -> None:
    next(box for box in app.selectbox if box.label == "Sample").set_value("V11A").run()
    click(app, "Open sample")
    assert scenario(app)["scenario_id"] == SAMPLE["scenario_id"]


def _texts(app: AppTest) -> str:
    groups = (app.caption, app.markdown, app.success, app.info, app.warning, app.error)
    return " | ".join(str(element.value) for group in groups for element in group)


def _saved_with_coordinates(backend: FakeBackend, **fields: Any) -> str:
    """V11-A saved with coordinates supplied in JSON, so it is ready for travel times."""
    payload = deepcopy(SAMPLE)
    for location in payload["locations"]:
        location["latitude"], location["longitude"] = coordinates_for(location["address"])
    payload.update(fields)
    backend.saved[str(payload["scenario_id"])] = payload
    return str(payload["scenario_id"])


# --- resolving in batches ----------------------------------------------------------


def test_batches_put_the_plant_first_and_respect_the_limit() -> None:
    assert resolve_batches(["A", "B", "PLANT", "C"], plant="PLANT", size=3) == [
        ["PLANT", "A", "B"],
        ["C"],
    ]
    assert resolve_batches(["A"], plant="PLANT", size=100) == [["A"]]
    with pytest.raises(ValueError, match="at least 1"):
        resolve_batches(["A"], plant="PLANT", size=0)
    results = [{"location_id": "PLANT", "latitude": 43.5, "longitude": -79.6}]
    assert result_coordinates(results, "PLANT") == {"latitude": 43.5, "longitude": -79.6}
    assert result_coordinates(results, "OTHER") is None
    assert merge_summaries([{"resolved": 2, "failed": 1}, None, {"resolved": 1}]) == {
        "resolved": 3,
        "needs_review": 0,
        "failed": 1,
        "provider_calls": 0,
        "cache_hits": 0,
    }


def test_addresses_are_resolved_in_requests_the_backend_accepts(backend: FakeBackend) -> None:
    backend.limits = {"max_resolve_addresses": 3}
    app = _start("scenario")
    _open_address_sample(app)
    go(app, "locations")
    click(app, f"Resolve addresses ({len(SAMPLE['locations'])} pending)")

    sizes = [len(call) for call in backend.resolve_calls]
    assert sizes == [3, 3, 1]
    assert backend.resolve_calls[0][0]["location_id"] == PLANT
    plant_address = next(
        row["address"] for row in SAMPLE["locations"] if row["location_id"] == PLANT
    )
    latitude, longitude = coordinates_for(plant_address)
    assert backend.resolve_requests[0]["plant_coordinates"] is None  # the plant is in it
    for later in backend.resolve_requests[1:]:
        assert later["plant_coordinates"] == {"latitude": latitude, "longitude": longitude}
    statuses = {row["location_id"]: row.get("geocode_status") for row in scenario(app)["locations"]}
    assert set(statuses.values()) == {"RESOLVED"}
    assert f"{len(SAMPLE['locations'])} resolved" in _texts(app)


def test_a_failure_part_way_keeps_what_was_already_resolved(backend: FakeBackend) -> None:
    backend.limits = {"max_resolve_addresses": 3}
    backend.resolve_failures = {
        2: api_client.BackendApiError(
            status_code=502,
            code="ROUTING_RATE_LIMIT",
            message="Google geocoding quota was reached after bounded retries.",
            request_id="req-2",
        )
    }
    app = _start("scenario")
    _open_address_sample(app)
    go(app, "locations")
    click(app, f"Resolve addresses ({len(SAMPLE['locations'])} pending)")

    resolved = [
        row["location_id"]
        for row in scenario(app)["locations"]
        if row.get("geocode_status") == "RESOLVED"
    ]
    assert resolved and len(resolved) == 3
    assert PLANT in resolved
    texts = _texts(app)
    assert "Kept the 3 address(es) resolved before the error." in texts
    assert "quota was reached" in texts


# --- travel times: refused before sending -------------------------------------------


def test_more_locations_than_one_calculation_allows_is_explained(backend: FakeBackend) -> None:
    backend.limits = {"max_matrix_locations": 5}
    scenario_id = _saved_with_coordinates(backend)
    app = _start("travel_times", scenario_param=scenario_id)

    texts = _texts(app)
    assert (
        f"at most 5 locations at a time, and this scenario has {len(SAMPLE['locations'])}" in texts
    )
    assert backend.estimate_calls == []  # nothing is sent, not even the free estimate
    calculate = [button for button in app.button if button.label == "Calculate travel times"]
    assert calculate and all(button.disabled for button in calculate)


def test_a_past_departure_time_blocks_calculation_with_a_reason(backend: FakeBackend) -> None:
    scenario_id = _saved_with_coordinates(
        backend,
        routing_options={
            "routing_preference": "TRAFFIC_AWARE",
            "departure_time": "2020-01-06T07:00:00-05:00",
        },
    )
    app = _start("travel_times", scenario_param=scenario_id)

    texts = _texts(app)
    assert "The departure time under Advanced (2020-01-06 07:00 EST) is in the past" in texts
    assert backend.estimate_calls == []
    assert backend.matrix_calls == []


def test_the_routing_form_refuses_a_departure_time_in_the_past(backend: FakeBackend) -> None:
    scenario_id = _saved_with_coordinates(backend)
    app = _start("travel_times", scenario_param=scenario_id)
    next(box for box in app.checkbox if str(box.label).startswith("Set a departure time")).check()
    next(box for box in app.date_input if box.label == "Departure date").set_value(date(2020, 1, 6))
    click(app, "Save routing options")

    assert "Choose a departure time in the future" in _texts(app)
    assert "routing_options" not in scenario(app)
