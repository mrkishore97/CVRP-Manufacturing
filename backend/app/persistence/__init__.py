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
    PersistedPlan,
    PersistedScenario,
    SQLitePlanRepository,
    SQLiteScenarioRepository,
)

__all__ = [
    "GEOCODE_CACHE_SCHEMA_VERSION",
    "MATRIX_CACHE_SCHEMA_VERSION",
    "CachedResolution",
    "PersistedPlan",
    "PersistedScenario",
    "SQLiteDatabase",
    "SQLiteGeocodeCache",
    "SQLiteMatrixCache",
    "SQLitePlanRepository",
    "SQLiteScenarioRepository",
    "build_geocode_cache_key",
    "build_matrix_cache_key",
]
