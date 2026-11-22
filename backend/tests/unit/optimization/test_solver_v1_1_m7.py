"""V1.1-M7: a search stopped by its time limit is never reported as a fleet shortage.

Measured in M7 on a 1,000-task week (100 locations, 100 truck-shifts): with a 30 s limit
the strict search used all 30 s without a first plan, and OR-Tools reported a plain
failure (status 3) rather than a timeout. Version 1.0's check took that as "not everything
fits" and returned a partial plan of 108 POs on 10 of 100 truck-shifts, blaming fleet
time for the other 892. Now such a search counts as out of time, and a partial plan whose
search was cut short by the limit says that more POs may fit.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from backend.app.application.planning_service import PlanningService
from backend.app.domain import PlanStatus, validate_planning_payload
from backend.app.domain.models import PlanningRequest
from backend.app.domain.options import OptimizationOptions
from backend.app.optimization import validate_plan_result
from backend.app.optimization.objective import solve_settings
from backend.app.optimization.solver import (
    TIME_LIMIT_REACHED_CODE,
    OrToolsCapacitySolver,
    _ran_out_of_time,
)
from backend.tests.fixtures.canonical import planning_payload
from backend.tests.fixtures.size_scenario import (
    MAX_REQUEST_TASKS,
    form_built_scenario,
    road_matrix,
    task_rows,
)


def _request(payload: dict[str, Any]) -> PlanningRequest:
    result = validate_planning_payload(payload, max_time_limit_seconds=600)
    assert result.valid, result.issues
    assert result.normalized_request is not None
    return result.normalized_request


@pytest.mark.parametrize(
    ("status", "found", "searched", "expected"),
    [
        (4, False, 0.2, True),  # ROUTING_FAIL_TIMEOUT
        (3, False, 9.8, True),  # plain failure after the whole limit: out of time
        (3, False, 0.3, False),  # plain failure early: nothing fits, as in Version 1.0
        (6, False, 9.9, False),  # ROUTING_INFEASIBLE is a proof, whatever the time
        (2, True, 10.0, False),  # a plan was found
    ],
)
def test_a_search_that_used_its_whole_limit_without_a_plan_ran_out_of_time(
    status: int, found: bool, searched: float, expected: bool
) -> None:
    assert (
        _ran_out_of_time(status, found=found, searched_seconds=searched, time_limit_seconds=10)
        is expected
    )


def test_a_week_too_large_for_its_time_limit_is_a_timeout_not_a_shortage() -> None:
    scenario, coordinates = form_built_scenario(tasks=0)
    payload = {
        **scenario,
        "tasks": task_rows(scenario, MAX_REQUEST_TASKS),
        "routing_matrix": road_matrix(coordinates).model_dump(mode="json"),
    }
    request = _request(payload)
    options = OptimizationOptions(time_limit_seconds=1)

    plan = OrToolsCapacitySolver().solve(request, solve_settings(options, 1))

    assert plan.status is PlanStatus.TIMEOUT
    assert plan.routes == ()
    assert {diagnostic.code for diagnostic in plan.diagnostics} == {"SOLVER_TIMEOUT"}
    assert "INSUFFICIENT_COMBINED_FLEET_TIME" not in {d.code for d in plan.diagnostics}


def test_a_partial_plan_cut_short_by_the_time_limit_says_more_may_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = planning_payload("D")
    unpatched = PlanningService().optimize(_request(payload))
    original = OrToolsCapacitySolver._solve_model

    def cut_short(self: OrToolsCapacitySolver, *args: Any, **kwargs: Any) -> Any:
        attempt = original(self, *args, **kwargs)
        stopped = bool(kwargs["allow_dropping"]) and attempt.assignment is not None
        return replace(attempt, cut_short=stopped)

    monkeypatch.setattr(OrToolsCapacitySolver, "_solve_model", cut_short)
    plan = PlanningService().optimize(_request(payload))

    assert plan.status is PlanStatus.PARTIALLY_FEASIBLE
    note, *per_po = plan.diagnostics
    assert (note.code, note.task_id) == (TIME_LIMIT_REACHED_CODE, "REQUEST")
    assert "longer time limit" in note.message
    # The POs and their reasons are the same as without the note.
    assert per_po == list(unpatched.diagnostics)
    assert plan.scheduled_task_ids == unpatched.scheduled_task_ids
    assert validate_plan_result(_request(payload), plan).valid


def test_a_partial_plan_that_settled_within_its_limit_has_no_such_note() -> None:
    plan = PlanningService().optimize(_request(planning_payload("D")))

    assert plan.status is PlanStatus.PARTIALLY_FEASIBLE
    assert TIME_LIMIT_REACHED_CODE not in {diagnostic.code for diagnostic in plan.diagnostics}
