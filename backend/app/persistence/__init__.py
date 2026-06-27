"""Persistence adapters and repository implementations."""

from backend.app.persistence.database import SQLiteDatabase
from backend.app.persistence.matrix_cache import (
    MATRIX_CACHE_SCHEMA_VERSION,
    SQLiteMatrixCache,
    build_matrix_cache_key,
)
from backend.app.persistence.scenario_repository import (
    PersistedPlan,
    PersistedScenario,
    SQLitePlanRepository,
    SQLiteScenarioRepository,
)

__all__ = [
    "MATRIX_CACHE_SCHEMA_VERSION",
    "PersistedPlan",
    "PersistedScenario",
    "SQLiteDatabase",
    "SQLiteMatrixCache",
    "SQLitePlanRepository",
    "SQLiteScenarioRepository",
    "build_matrix_cache_key",
]
