"""Planner options the solver honours (plan §10.1 to §10.4).

Task priority (V1.1-M4, decision D3) changes nothing while every task fits: all tasks
are then mandatory. Only when the fleet cannot carry everything does the partial plan
leave out the set of tasks with the least total weight, so higher priorities are kept
first. Priority never relaxes a hard constraint.

``OptimizationOptions`` (V1.1-M5) is the optional ``optimization_options`` object of a
planning payload. Every field is optional, and the defaults are the Version 1.0
behaviour, so a payload without the object is solved exactly as before. No option
relaxes a hard constraint: capacity, deadlines, shifts, tags, and route limits hold in
every mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.domain.enums import BalanceStrength, ObjectiveMode, SearchEffort

DEFAULT_PRIORITY: Final = 1
PRIORITY_LABELS: Final[Mapping[int, str]] = MappingProxyType(
    {1: "Routine", 2: "Normal", 3: "Important", 4: "High", 5: "Critical"}
)
PRIORITY_WEIGHTS: Final[Mapping[int, int]] = MappingProxyType({1: 1, 2: 2, 3: 4, 4: 8, 5: 16})
"""Omission weights: one Critical task outweighs up to fifteen Routine ones (D3)."""

DEFAULT_EXTRA_TRUCK_COST_KM: Final = 1_000
"""Version 1.0's fixed cost of 1,000,000 cost units (metres) per truck-shift."""
MAX_EXTRA_TRUCK_COST_KM: Final = 100_000
MIN_TRAVEL_TIME_FACTOR: Final = 1.0
MAX_TRAVEL_TIME_FACTOR: Final = 2.0
MAX_TIME_LIMIT_SECONDS: Final = 3_600
"""Absolute ceiling; the server's own ``SOLVER_MAX_TIME_LIMIT_SECONDS`` is usually lower."""


def priority_weight(priority: int) -> int:
    """The omission weight of a priority from 1 (Routine) to 5 (Critical)."""
    try:
        return PRIORITY_WEIGHTS[priority]
    except KeyError:
        raise ValueError(f"priority must be 1 through 5, not {priority!r}") from None


def priority_label(priority: int) -> str:
    return PRIORITY_LABELS.get(priority, str(priority))


class OptimizationOptions(BaseModel):
    """How to optimise: objective, search effort, time limit, and travel-time buffer.

    ``time_limit_seconds`` left empty means the server default. A plan records the
    options it was solved with, with the time limit filled in.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    objective_mode: ObjectiveMode = ObjectiveMode.MINIMIZE_TRUCKS
    search_effort: SearchEffort = SearchEffort.STANDARD
    time_limit_seconds: int | None = Field(default=None, ge=1, le=MAX_TIME_LIMIT_SECONDS)
    travel_time_factor: float = Field(
        default=1.0, ge=MIN_TRAVEL_TIME_FACTOR, le=MAX_TRAVEL_TIME_FACTOR
    )
    extra_truck_cost_km: int = Field(
        default=DEFAULT_EXTRA_TRUCK_COST_KM, ge=0, le=MAX_EXTRA_TRUCK_COST_KM
    )
    balance_strength: BalanceStrength = BalanceStrength.MEDIUM

    @field_validator("travel_time_factor")
    @classmethod
    def two_decimals(cls, value: float) -> float:
        if round(value, 2) != value:
            raise ValueError("travel_time_factor may have at most two decimals, such as 1.25")
        return value

    def with_time_limit(self, seconds: int) -> OptimizationOptions:
        """These options with the time limit the solve actually used."""
        return self.model_copy(update={"time_limit_seconds": seconds})
