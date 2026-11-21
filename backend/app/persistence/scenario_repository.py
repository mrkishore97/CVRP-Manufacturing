"""SQLite repositories for saved planning scenarios and plans."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.results import PlanResult
from backend.app.persistence.database import SQLiteDatabase

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedScenario:
    """Scenario payload as stored in SQLite."""

    scenario_id: str
    payload: JsonObject
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    """One saved scenario as listed: identity, timestamps, and row counts."""

    scenario_id: str
    name: str | None
    created_at: datetime
    updated_at: datetime
    location_count: int
    vehicle_count: int
    shift_count: int
    task_count: int


def _count(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    return len(value) if isinstance(value, list) else 0


@dataclass(frozen=True, slots=True)
class PersistedPlan:
    """Plan result as stored in SQLite."""

    plan_id: str
    scenario_id: str
    plan: PlanResult
    created_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


class SQLiteScenarioRepository:
    """Persist and retrieve scenario JSON payloads."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    scenario_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, scenario_id: str, payload: JsonObject) -> PersistedScenario:
        now = _utc_now()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM scenarios WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            created_at = _parse_datetime(existing[0]) if existing else now
            connection.execute(
                """
                INSERT INTO scenarios (
                    scenario_id, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(scenario_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    scenario_id,
                    payload_json,
                    created_at.isoformat(),
                    now.isoformat(),
                ),
            )
        return PersistedScenario(
            scenario_id=scenario_id,
            payload=json.loads(payload_json),
            created_at=created_at,
            updated_at=now,
        )

    def get(self, scenario_id: str) -> PersistedScenario | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT scenario_id, payload_json, created_at, updated_at
                FROM scenarios
                WHERE scenario_id = ?
                """,
                (scenario_id,),
            ).fetchone()
        if row is None:
            return None
        return PersistedScenario(
            scenario_id=row[0],
            payload=json.loads(row[1]),
            created_at=_parse_datetime(row[2]),
            updated_at=_parse_datetime(row[3]),
        )

    def list_summaries(self) -> tuple[ScenarioSummary, ...]:
        """Every saved scenario, most recently updated first."""
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT scenario_id, payload_json, created_at, updated_at
                FROM scenarios
                ORDER BY updated_at DESC, scenario_id
                """
            ).fetchall()
        summaries: list[ScenarioSummary] = []
        for scenario_id, payload_json, created_at, updated_at in rows:
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            name = payload.get("name")
            summaries.append(
                ScenarioSummary(
                    scenario_id=scenario_id,
                    name=str(name) if isinstance(name, str) and name.strip() else None,
                    created_at=_parse_datetime(created_at),
                    updated_at=_parse_datetime(updated_at),
                    location_count=_count(payload, "locations"),
                    vehicle_count=_count(payload, "vehicles"),
                    shift_count=_count(payload, "vehicle_shifts"),
                    task_count=_count(payload, "tasks"),
                )
            )
        return tuple(summaries)

    def rewrite_payloads(self, transform: Callable[[JsonObject], JsonObject | None]) -> int:
        """Apply ``transform`` to every stored payload; returns how many changed.

        ``transform`` returns the replacement payload, or ``None`` to leave the row
        alone. ``updated_at`` is kept: a retention sweep is not a planner's save.
        """
        with self._database.connect() as connection:
            rows = connection.execute("SELECT scenario_id, payload_json FROM scenarios").fetchall()
            changed = 0
            for scenario_id, payload_json in rows:
                try:
                    payload = json.loads(payload_json)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                replacement = transform(payload)
                if replacement is None:
                    continue
                connection.execute(
                    "UPDATE scenarios SET payload_json = ? WHERE scenario_id = ?",
                    (
                        json.dumps(replacement, sort_keys=True, separators=(",", ":")),
                        scenario_id,
                    ),
                )
                changed += 1
        return changed


class SQLitePlanRepository:
    """Persist and retrieve optimized plan results."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._initialize()

    def _initialize(self) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save(
        self, scenario_id: str, plan: PlanResult, *, history_limit: int | None = None
    ) -> PersistedPlan:
        """Store a plan; with ``history_limit``, keep only that many newest per scenario."""
        now = _utc_now()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO plans (
                    plan_id, scenario_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(plan_id) DO UPDATE SET
                    scenario_id = excluded.scenario_id,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    plan.plan_id,
                    scenario_id,
                    plan.model_dump_json(),
                    now.isoformat(),
                ),
            )
            if history_limit is not None:
                connection.execute(
                    """
                    DELETE FROM plans
                    WHERE scenario_id = ?
                      AND plan_id NOT IN (
                        SELECT plan_id FROM plans
                        WHERE scenario_id = ?
                        ORDER BY created_at DESC, rowid DESC
                        LIMIT ?
                      )
                    """,
                    (scenario_id, scenario_id, history_limit),
                )
        return PersistedPlan(
            plan_id=plan.plan_id,
            scenario_id=scenario_id,
            plan=plan,
            created_at=now,
        )

    def list_for_scenario(self, scenario_id: str) -> tuple[PersistedPlan, ...]:
        """The scenario's stored plans, newest first."""
        with self._database.connect() as connection:
            found = connection.execute(
                """
                SELECT plan_id, scenario_id, payload_json, created_at
                FROM plans
                WHERE scenario_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (scenario_id,),
            ).fetchall()
        return tuple(
            PersistedPlan(
                plan_id=row[0],
                scenario_id=row[1],
                plan=PlanResult.model_validate_json(row[2]),
                created_at=_parse_datetime(row[3]),
            )
            for row in found
        )

    def get(self, plan_id: str) -> PersistedPlan | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT plan_id, scenario_id, payload_json, created_at
                FROM plans
                WHERE plan_id = ?
                """,
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return PersistedPlan(
            plan_id=row[0],
            scenario_id=row[1],
            plan=PlanResult.model_validate_json(row[2]),
            created_at=_parse_datetime(row[3]),
        )
