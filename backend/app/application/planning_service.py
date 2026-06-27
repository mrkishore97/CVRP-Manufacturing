"""Application service boundary for producing optimized manufacturing pickup plans."""

from __future__ import annotations

from backend.app.domain.models import PlanningRequest
from backend.app.domain.results import PlanResult
from backend.app.optimization.solver import OrToolsCapacitySolver


class PlanningService:
    """Thin orchestration layer that keeps API/UI code independent of solver details."""

    def __init__(self, solver: OrToolsCapacitySolver | None = None) -> None:
        self._solver = solver or OrToolsCapacitySolver()

    def optimize(self, request: PlanningRequest) -> PlanResult:
        """Optimize a normalized planning request using the configured backend solver."""
        return self._solver.solve(request)
