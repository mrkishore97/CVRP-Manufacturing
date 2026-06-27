"""SQLite repositories for saved planning scenarios and plans."""

from __future__ import annotations

import json
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

    def save(self, scenario_id: str, plan: PlanResult) -> PersistedPlan:
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
        return PersistedPlan(
            plan_id=plan.plan_id,
            scenario_id=scenario_id,
            plan=plan,
            created_at=now,
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
