"""Persistence adapters and repository implementations."""

from backend.app.persistence.database import SQLiteDatabase
from backend.app.persistence.geocode_cache import (
    GEOCODE_CACHE_SCHEMA_VERSION,
    CachedResolution,
    SQLiteGeocodeCache,
    build_geocode_cache_key,
)
from backend.app.persistence.matrix_cache import (
    MATRIX_CACHE_SCHEMA_VERSION,
    SQLiteMatrixCache,
    build_matrix_cache_key,
)
from backend.app.persistence.scenario_repository import (
    SCHEMA_VERSION,
    PersistedDraft,
    PersistedPlan,
    PersistedScenario,
    ScenarioExistsError,
    ScenarioSummary,
    SQLiteDraftRepository,
    SQLitePlanRepository,
    SQLiteScenarioRepository,
    record_schema_version,
)

__all__ = [
    "GEOCODE_CACHE_SCHEMA_VERSION",
    "MATRIX_CACHE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "CachedResolution",
    "PersistedDraft",
    "PersistedPlan",
    "PersistedScenario",
    "SQLiteDatabase",
    "SQLiteDraftRepository",
    "SQLiteGeocodeCache",
    "SQLiteMatrixCache",
    "SQLitePlanRepository",
    "SQLiteScenarioRepository",
    "ScenarioExistsError",
    "ScenarioSummary",
    "build_geocode_cache_key",
    "build_matrix_cache_key",
    "record_schema_version",
]
