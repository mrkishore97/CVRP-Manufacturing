"""Optimization options in the scenario, and the solve timeout (V1.1-M5)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from frontend.api_client import BackendClient
from frontend.state.optimization import (
    current_options,
    effective_time_limit,
    options_summary,
    plan_figures,
    set_options,
    solve_timeout_seconds,
)
from frontend.state.scenario_state import ScenarioEditError, new_scenario


def _set(scenario: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "objective_mode": "MINIMIZE_TRUCKS",
        "search_effort": "STANDARD",
        "time_limit_seconds": 10,
        "buffer_percent": 0,
        "extra_truck_cost_km": 1_000,
        "balance_strength": "MEDIUM",
        "default_time_limit": 10,
        "max_time_limit": 120,
        **overrides,
    }
    return set_options(scenario, **values)


def test_all_default_settings_leave_the_version_1_0_shape() -> None:
    scenario = new_scenario(scenario_id="S")
    scenario["optimization_options"] = {"objective_mode": "MINIMIZE_TRAVEL"}

    updated = _set(scenario)

    assert "optimization_options" not in updated


def test_only_changed_settings_are_stored() -> None:
    updated = _set(
        new_scenario(scenario_id="S"),
        objective_mode="BALANCE_WORKLOAD",
        search_effort="THOROUGH",
        time_limit_seconds=30,
        buffer_percent=15,
        balance_strength="STRONG",
    )

    assert updated["optimization_options"] == {
        "objective_mode": "BALANCE_WORKLOAD",
        "search_effort": "THOROUGH",
        "time_limit_seconds": 30,
        "travel_time_factor": 1.15,
        "balance_strength": "STRONG",
    }
    options = current_options(updated, default_time_limit=10)
    assert options["extra_truck_cost_km"] == 1_000
    assert effective_time_limit(updated, default_time_limit=10, max_time_limit=20) == 20


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"objective_mode": "CHEAPEST"}, "objective"),
        ({"time_limit_seconds": 121}, "time limit"),
        ({"buffer_percent": 101}, "buffer"),
        ({"extra_truck_cost_km": -1}, "extra truck"),
        ({"balance_strength": "EXTREME"}, "balance"),
    ],
)
def test_settings_are_bounded(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ScenarioEditError, match=message):
        _set(new_scenario(scenario_id="S"), **overrides)


def test_summary_and_figures_describe_a_plan() -> None:
    assert options_summary(None) == "Fewest trucks, standard search (Version 1.0 settings)."
    assert options_summary(
        {
            "objective_mode": "BALANCE_WORKLOAD",
            "search_effort": "THOROUGH",
            "time_limit_seconds": 20,
            "travel_time_factor": 1.2,
            "balance_strength": "LIGHT",
        }
    ) == (
        "Balanced workload, thorough search, time limit 20 s, travel-time buffer 20 %, "
        "light balance."
    )
    figures = plan_figures(
        {
            "total_distance_meters": 254_000,
            "routes": [{}, {}, {}],
            "metrics": {
                "truck_shifts_used": 3,
                "truck_shifts_available": 3,
                "longest_route_seconds": 14_796,
                "longest_working_seconds": 12_204,
            },
        }
    )
    assert figures == {
        "Truck-shifts used": "3 of 3",
        "Total distance": "254.0 km",
        "Longest route": "4:07",
        "Longest working time": "3:23",
    }


@pytest.mark.parametrize(("limit", "expected"), [(10, 60.0), (30, 80.0), (120, 260.0)])
def test_the_client_waits_twice_the_time_limit_plus_20_seconds(limit: int, expected: float) -> None:
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(float(request.extensions["timeout"]["read"]))
        return httpx.Response(
            200, json={"validation": {"valid": True, "issues": []}, "plan": {"plan_id": "P"}}
        )

    client = BackendClient("http://test", transport=httpx.MockTransport(handler))
    client.solve_plan({}, time_limit_seconds=limit)

    assert seen == [expected]
    assert solve_timeout_seconds(limit) == 2 * limit + 20


def test_summary_fills_missing_options_with_the_defaults() -> None:
    assert options_summary({"search_effort": "THOROUGH"}) == (
        "Fewest trucks, thorough search, no travel-time buffer."
    )
