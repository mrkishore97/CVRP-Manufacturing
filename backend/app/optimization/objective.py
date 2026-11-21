"""Every objective weight and search setting in one place (plan §10.2, §10.3).

The solver's cost unit is the metre. ``MINIMIZE_TRUCKS`` adds a fixed cost per
truck-shift used, expressed in kilometres: the Version 1.0 constant of 1,000,000 is
"a truck is worth dispatching only if it saves 1,000 km". ``MINIMIZE_TRAVEL`` drops the
fixed cost. ``BALANCE_WORKLOAD`` drops it too and adds a cost on the longest route's
working time (driving plus service), so work is spread without sending out empty trucks.

Balance presets were tuned in V1.1-M5 against fixture V11-E and are frozen by
regression tests: changing one changes plans.

``STANDARD`` search is Version 1.0's: the first good plan, improved until no simple move
helps. ``THOROUGH`` adds guided local search, which keeps improving until the time limit,
so the time limit really buys a better plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from backend.app.domain.enums import BalanceStrength, ObjectiveMode, SearchEffort
from backend.app.domain.options import OptimizationOptions

METERS_PER_KM: Final = 1_000
DEFAULT_TIME_LIMIT_SECONDS: Final = 10
VERSION_1_0_VEHICLE_FIXED_COST: Final = 1_000_000
BALANCE_SPAN_COEFFICIENTS: Final[Mapping[BalanceStrength, int]] = MappingProxyType(
    {
        BalanceStrength.LIGHT: 5,
        BalanceStrength.MEDIUM: 10,
        BalanceStrength.STRONG: 20,
    }
)
"""Cost per second of the longest route's working time, in metres.

Shortening the longest route's working time by one hour is worth 18 km of extra driving
at LIGHT, 36 km at MEDIUM, and 72 km at STRONG. Tuned on Scenario A's shape (V11-E),
where standard search gives a longest working time of 4.1, 3.4, and 3.1 hours against
7.3 hours for fewest trucks, for 229, 254, and 288 km against 216 km.
"""


@dataclass(frozen=True, slots=True)
class SolveSettings:
    """What one solve optimises and how long it searches."""

    objective_mode: ObjectiveMode = ObjectiveMode.MINIMIZE_TRUCKS
    search_effort: SearchEffort = SearchEffort.STANDARD
    time_limit_seconds: int = DEFAULT_TIME_LIMIT_SECONDS
    vehicle_fixed_cost: int = VERSION_1_0_VEHICLE_FIXED_COST
    span_cost_coefficient: int = 0

    def __post_init__(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.vehicle_fixed_cost < 0 or self.span_cost_coefficient < 0:
            raise ValueError("objective weights must be non-negative")


def solve_settings(options: OptimizationOptions, time_limit_seconds: int) -> SolveSettings:
    """The solver settings for planner options and the effective time limit."""
    mode = options.objective_mode
    fixed_cost = (
        options.extra_truck_cost_km * METERS_PER_KM if mode is ObjectiveMode.MINIMIZE_TRUCKS else 0
    )
    span = (
        BALANCE_SPAN_COEFFICIENTS[options.balance_strength]
        if mode is ObjectiveMode.BALANCE_WORKLOAD
        else 0
    )
    return SolveSettings(
        objective_mode=mode,
        search_effort=options.search_effort,
        time_limit_seconds=time_limit_seconds,
        vehicle_fixed_cost=fixed_cost,
        span_cost_coefficient=span,
    )


def search_parameters(settings: SolveSettings) -> pywrapcp.DefaultRoutingSearchParameters:
    """OR-Tools search parameters; ``STANDARD`` is exactly Version 1.0's."""
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    if settings.search_effort is SearchEffort.THOROUGH:
        parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
    parameters.time_limit.FromSeconds(settings.time_limit_seconds)
    parameters.log_search = False
    return parameters
