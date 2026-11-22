"""SQLite repositories for saved planning scenarios, their drafts, and plans.

Schema changes are additive only (plan §11.3). ``schema_meta`` records the schema
version for future migrations: 1 is Version 1.0's tables, 2 adds the Version 1.1
``scenario_drafts`` table and the plan-history index.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.results import PlanResult
from backend.app.persistence.database import SQLiteDatabase

JsonObject = dict[str, Any]

SCHEMA_VERSION = 2


def record_schema_version(database: SQLiteDatabase, version: int = SCHEMA_VERSION) -> int:
    """Create ``schema_meta`` if needed and raise its version to ``version``; returns it."""
    with database.connect() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        current = int(row[0]) if row is not None and str(row[0]).isdigit() else 0
        if current < version:
            connection.execute(
                """
                INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(version),),
            )
            current = version
    return current


class ScenarioExistsError(RuntimeError):
    """Saving would replace a scenario the caller asked not to overwrite."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        super().__init__(f"A saved scenario with ID {scenario_id} already exists.")


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

    def save(
        self, scenario_id: str, payload: JsonObject, *, overwrite: bool = True
    ) -> PersistedScenario:
        """Store a scenario; with ``overwrite=False`` an existing ID raises instead."""
        now = _utc_now()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._database.connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM scenarios WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            if existing and not overwrite:
                raise ScenarioExistsError(scenario_id)
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

    def delete(self, scenario_id: str) -> bool:
        """Remove a saved scenario; ``False`` when there was none."""
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM scenarios WHERE scenario_id = ?", (scenario_id,)
            )
            return cursor.rowcount > 0

    def rewrite_payloads(self, transform: Callable[[JsonObject], JsonObject | None]) -> int:
        """Apply ``transform`` to every stored payload; returns how many changed.

        ``transform`` returns the replacement payload, or ``None`` to leave the row
        alone. ``updated_at`` is kept: a retention sweep is not a planner's save.
        """
        return _rewrite_payloads(self._database, "scenarios", transform)

    def replace_payload(self, scenario_id: str, payload: JsonObject) -> None:
        """Replace one stored payload, keeping its timestamps (retention on load)."""
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE scenarios SET payload_json = ? WHERE scenario_id = ?",
                (json.dumps(payload, sort_keys=True, separators=(",", ":")), scenario_id),
            )


_PAYLOAD_TABLES = frozenset({"scenarios", "scenario_drafts"})


def _rewrite_payloads(
    database: SQLiteDatabase, table: str, transform: Callable[[JsonObject], JsonObject | None]
) -> int:
    if table not in _PAYLOAD_TABLES:  # the table name is never caller input
        raise ValueError(f"Unknown payload table: {table}")
    with database.connect() as connection:
        rows = connection.execute(f"SELECT scenario_id, payload_json FROM {table}").fetchall()
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
                f"UPDATE {table} SET payload_json = ? WHERE scenario_id = ?",
                (
                    json.dumps(replacement, sort_keys=True, separators=(",", ":")),
                    scenario_id,
                ),
            )
            changed += 1
    return changed


@dataclass(frozen=True, slots=True)
class PersistedDraft:
    """The working copy of a scenario, written after each change (plan §11.3).

    ``meta`` is small app-owned context (for example the matrix identity and the plan
    shown), never a Google matrix.
    """

    scenario_id: str
    payload: JsonObject
    meta: JsonObject
    updated_at: datetime


class SQLiteDraftRepository:
    """One refresh-safe draft per scenario ID; a save never reads it."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        with self._database.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scenario_drafts (
                    scenario_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def put(self, scenario_id: str, payload: JsonObject, meta: JsonObject) -> PersistedDraft:
        now = _utc_now()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO scenario_drafts (scenario_id, payload_json, meta_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scenario_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    meta_json = excluded.meta_json,
                    updated_at = excluded.updated_at
                """,
                (scenario_id, payload_json, meta_json, now.isoformat()),
            )
        return PersistedDraft(
            scenario_id=scenario_id,
            payload=json.loads(payload_json),
            meta=json.loads(meta_json),
            updated_at=now,
        )

    def get(self, scenario_id: str) -> PersistedDraft | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT scenario_id, payload_json, meta_json, updated_at
                FROM scenario_drafts WHERE scenario_id = ?
                """,
                (scenario_id,),
            ).fetchone()
        if row is None:
            return None
        meta = json.loads(row[2])
        return PersistedDraft(
            scenario_id=row[0],
            payload=json.loads(row[1]),
            meta=meta if isinstance(meta, dict) else {},
            updated_at=_parse_datetime(row[3]),
        )

    def delete(self, scenario_id: str) -> bool:
        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM scenario_drafts WHERE scenario_id = ?", (scenario_id,)
            )
            return cursor.rowcount > 0

    def replace_payload(self, scenario_id: str, payload: JsonObject) -> None:
        """Replace one draft's payload, keeping its time (retention on load)."""
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE scenario_drafts SET payload_json = ? WHERE scenario_id = ?",
                (json.dumps(payload, sort_keys=True, separators=(",", ":")), scenario_id),
            )

    def rewrite_payloads(self, transform: Callable[[JsonObject], JsonObject | None]) -> int:
        """Apply ``transform`` to every draft; returns how many changed."""
        return _rewrite_payloads(self._database, "scenario_drafts", transform)


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
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS plans_by_scenario
                ON plans (scenario_id, created_at)
                """
            )

    def delete_for_scenario(self, scenario_id: str) -> int:
        """Remove every stored plan of a scenario; returns how many."""
        with self._database.connect() as connection:
            cursor = connection.execute("DELETE FROM plans WHERE scenario_id = ?", (scenario_id,))
            return int(cursor.rowcount)

    def counts_by_scenario(self) -> dict[str, int]:
        """How many plans each scenario has stored."""
        with self._database.connect() as connection:
            found = connection.execute(
                "SELECT scenario_id, COUNT(*) FROM plans GROUP BY scenario_id"
            ).fetchall()
        return {str(scenario_id): int(count) for scenario_id, count in found}

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
