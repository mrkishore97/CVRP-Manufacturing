"""Planner options the solver honours.

V1.1-M4 adds task priority (plan §10.4, decision D3). Priority changes nothing while
every task fits: all tasks are then mandatory. Only when the fleet cannot carry
everything does the partial plan leave out the set of tasks with the least total
weight, so higher priorities are kept first. Priority never relaxes a hard constraint.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

DEFAULT_PRIORITY: Final = 1
PRIORITY_LABELS: Final[Mapping[int, str]] = MappingProxyType(
    {1: "Routine", 2: "Normal", 3: "Important", 4: "High", 5: "Critical"}
)
PRIORITY_WEIGHTS: Final[Mapping[int, int]] = MappingProxyType({1: 1, 2: 2, 3: 4, 4: 8, 5: 16})
"""Omission weights: one Critical task outweighs up to fifteen Routine ones (D3)."""


def priority_weight(priority: int) -> int:
    """The omission weight of a priority from 1 (Routine) to 5 (Critical)."""
    try:
        return PRIORITY_WEIGHTS[priority]
    except KeyError:
        raise ValueError(f"priority must be 1 through 5, not {priority!r}") from None


def priority_label(priority: int) -> str:
    return PRIORITY_LABELS.get(priority, str(priority))
