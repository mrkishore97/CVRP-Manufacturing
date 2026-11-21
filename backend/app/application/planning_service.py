"""Planning service: options, travel-time buffer, and plan identity (plan §10.6, §10.8).

The service turns the planner's ``optimization_options`` into solver settings, applies
the travel-time buffer once to a copy of the matrix (so the solver, its pre-checks, and
the independent validator all see the same times), runs one solve at a time, and gives
each plan a unique ID with the options, matrix identity, and figures it was made with.
The stored or cached matrix is never changed, so changing the buffer costs no Google call.

OR-Tools keeps Python's global interpreter lock for the whole search, so a solve in a
worker thread would still freeze the API. The backend therefore solves in one separate
worker process, shared by the whole backend, which also makes solves run one at a time
(finding F17). Tests and tools may solve in-process instead.
"""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from backend.app.domain.models import PlanningRequest, RoutingMatrix
from backend.app.domain.options import OptimizationOptions
from backend.app.domain.results import MatrixIdentity, PlanResult
from backend.app.optimization.objective import SolveSettings, solve_settings
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig

_SOLVE_LOCK = threading.Lock()
"""One in-process solve at a time: each uses a full CPU core for its time limit."""
_POOL_LOCK = threading.Lock()
_POOL: ProcessPoolExecutor | None = None


def exit_when_parent_exits() -> None:
    """Runs in the worker at start: leave as soon as the backend process is gone.

    A backend stopped with Ctrl+C shuts its worker down, but a backend that is killed
    (as ``run_app.ps1`` does on exit) cannot, and the worker would otherwise stay idle
    forever. A solve in progress finishes first, because it holds the interpreter lock.
    """
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch() -> None:
        parent.join()
        os._exit(0)

    threading.Thread(target=watch, name="solver-parent-watch", daemon=True).start()


def solver_process_pool() -> ProcessPoolExecutor:
    """The backend's one solver worker process, started on first use."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=exit_when_parent_exits,
            )
        return _POOL


def _discard_process_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


def solve_in_worker(request_json: str, config: SolverConfig, settings: SolveSettings) -> str:
    """Runs in the worker process: JSON in and out keeps the hand-over simple."""
    request = PlanningRequest.model_validate_json(request_json)
    return OrToolsCapacitySolver(config).solve(request, settings).model_dump_json()


def new_plan_id(scenario_id: str, created_at: datetime) -> str:
    """``PLAN-<UTC timestamp>-<short hash>``: unique, and short whatever the scenario ID."""
    stamp = created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    seed = f"{scenario_id}|{created_at.isoformat()}|{uuid.uuid4().hex}"
    return f"PLAN-{stamp}-{hashlib.sha256(seed.encode()).hexdigest()[:8]}"


def apply_travel_time_factor(request: PlanningRequest, factor: float) -> PlanningRequest:
    """A copy of the request whose travel times are scaled by ``factor`` (rounded)."""
    matrix = request.routing_matrix
    if matrix is None or factor == 1.0:
        return request
    scale = Decimal(str(factor))
    durations = tuple(
        tuple(int((Decimal(value) * scale).to_integral_value(ROUND_HALF_UP)) for value in row)
        for row in matrix.duration_seconds
    )
    return request.model_copy(
        update={"routing_matrix": matrix.model_copy(update={"duration_seconds": durations})}
    )


def matrix_identity(matrix: RoutingMatrix | None, factor: float) -> MatrixIdentity | None:
    if matrix is None:
        return None
    return MatrixIdentity(
        source=matrix.source,
        routing_preference=matrix.routing_preference,
        created_at=matrix.created_at,
        location_count=len(matrix.location_ids),
        travel_time_factor=factor,
    )


class PlanningService:
    """Thin orchestration layer that keeps API/UI code independent of solver details."""

    def __init__(
        self,
        solver: OrToolsCapacitySolver | None = None,
        *,
        default_time_limit_seconds: int | None = None,
        max_time_limit_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
        in_worker_process: bool = False,
    ) -> None:
        self._solver = solver or OrToolsCapacitySolver()
        self._in_worker_process = in_worker_process
        self._default_time_limit_seconds = (
            default_time_limit_seconds or self._solver.default_settings().time_limit_seconds
        )
        self._max_time_limit_seconds = max_time_limit_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def effective_time_limit(self, options: OptimizationOptions) -> int:
        """The requested time limit, else the server default, never above the server cap."""
        limit = options.time_limit_seconds or self._default_time_limit_seconds
        if self._max_time_limit_seconds is not None:
            limit = min(limit, self._max_time_limit_seconds)
        return limit

    def optimize(self, request: PlanningRequest) -> PlanResult:
        """Solve with the request's options; the result carries a new, unique plan ID."""
        options = request.optimization_options
        time_limit = self.effective_time_limit(options)
        solved_request = apply_travel_time_factor(request, options.travel_time_factor)
        settings = solve_settings(options, time_limit)
        if self._in_worker_process:
            result = self._solve_in_worker_process(solved_request, settings)
        else:
            with _SOLVE_LOCK:
                result = self._solver.solve(solved_request, settings)
        created_at = self._clock().astimezone(UTC)
        return result.model_copy(
            update={
                "plan_id": new_plan_id(request.scenario_id, created_at),
                "created_at": created_at,
                "optimization_options": options.with_time_limit(time_limit),
                "matrix": matrix_identity(request.routing_matrix, options.travel_time_factor),
            }
        )

    def _solve_in_worker_process(
        self, request: PlanningRequest, settings: SolveSettings
    ) -> PlanResult:
        future = solver_process_pool().submit(
            solve_in_worker, request.model_dump_json(), self._solver.config, settings
        )
        try:
            return PlanResult.model_validate_json(future.result())
        except BrokenProcessPool:
            _discard_process_pool()  # the next solve starts a fresh worker
            raise
