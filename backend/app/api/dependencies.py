"""FastAPI dependency declarations."""

from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request

from backend.app.application import LocationService, PlanningService, RoutingService
from backend.app.config import Settings
from backend.app.optimization.solver import OrToolsCapacitySolver, SolverConfig
from backend.app.persistence import (
    SQLiteDatabase,
    SQLiteGeocodeCache,
    SQLiteMatrixCache,
    SQLitePlanRepository,
    SQLiteScenarioRepository,
)
from backend.app.routing import RoutingLimits, RoutingProvider, google_provider_from_settings


def get_app_settings(request: Request) -> Settings:
    """Read settings attached when the FastAPI application was created."""
    return cast(Settings, request.app.state.settings)


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]


def get_request_id(request: Request) -> str:
    """Read the request ID attached by middleware."""
    return str(getattr(request.state, "request_id", "unknown-request"))


RequestIdDependency = Annotated[str, Depends(get_request_id)]


def database_for_app(app: FastAPI, settings: Settings) -> SQLiteDatabase:
    """Return the application's shared SQLite handle, creating it on first use."""
    database = getattr(app.state, "database", None)
    if database is None:
        database = SQLiteDatabase(settings.database_path)
        app.state.database = database
    return cast(SQLiteDatabase, database)


def get_database(request: Request, settings: SettingsDependency) -> SQLiteDatabase:
    """Return a shared local SQLite database handle."""
    return database_for_app(request.app, settings)


DatabaseDependency = Annotated[SQLiteDatabase, Depends(get_database)]


def get_scenario_repository(database: DatabaseDependency) -> SQLiteScenarioRepository:
    """Return the scenario repository for this request."""
    return SQLiteScenarioRepository(database)


ScenarioRepositoryDependency = Annotated[
    SQLiteScenarioRepository,
    Depends(get_scenario_repository),
]


def get_plan_repository(database: DatabaseDependency) -> SQLitePlanRepository:
    """Return the plan repository for this request."""
    return SQLitePlanRepository(database)


PlanRepositoryDependency = Annotated[SQLitePlanRepository, Depends(get_plan_repository)]


def get_routing_provider(request: Request, settings: SettingsDependency) -> RoutingProvider:
    """Return a test-injected provider or the configured Google provider."""
    provider = getattr(request.app.state, "routing_provider", None)
    if provider is not None:
        return cast(RoutingProvider, provider)
    return google_provider_from_settings(settings)


RoutingProviderDependency = Annotated[RoutingProvider, Depends(get_routing_provider)]


def get_matrix_cache(database: DatabaseDependency) -> SQLiteMatrixCache:
    """Return the matrix cache repository."""
    return SQLiteMatrixCache(database)


MatrixCacheDependency = Annotated[SQLiteMatrixCache, Depends(get_matrix_cache)]


def routing_limits_from_settings(settings: Settings) -> RoutingLimits:
    """Matrix batching limits shared by the Google adapter and the estimator."""
    return RoutingLimits(
        maximum_origins=settings.routes_max_origins,
        maximum_destinations=settings.routes_max_destinations,
        maximum_elements=settings.routes_max_elements,
    )


def get_routing_service(
    provider: RoutingProviderDependency,
    cache: MatrixCacheDependency,
    settings: SettingsDependency,
) -> RoutingService:
    """Create the routing application service for this request."""
    return RoutingService(
        provider,
        cache,
        cache_ttl_seconds=settings.matrix_cache_ttl_seconds,
        departure_bucket_minutes=settings.matrix_departure_bucket_minutes,
        limits=routing_limits_from_settings(settings),
    )


RoutingServiceDependency = Annotated[RoutingService, Depends(get_routing_service)]


def get_geocode_cache(
    database: DatabaseDependency, settings: SettingsDependency
) -> SQLiteGeocodeCache:
    """Return the 30-day address-resolution cache."""
    return SQLiteGeocodeCache(database, ttl_seconds=settings.geocode_cache_ttl_seconds)


GeocodeCacheDependency = Annotated[SQLiteGeocodeCache, Depends(get_geocode_cache)]


def get_location_service(
    provider: RoutingProviderDependency,
    cache: GeocodeCacheDependency,
    settings: SettingsDependency,
) -> LocationService:
    """Create the address-resolution service for this request."""
    return LocationService(
        provider,
        cache,
        max_plant_distance_km=settings.geocode_max_plant_distance_km,
        max_concurrency=settings.geocode_max_concurrency,
    )


LocationServiceDependency = Annotated[LocationService, Depends(get_location_service)]


def get_planning_service(request: Request, settings: SettingsDependency) -> PlanningService:
    """Return a test-injected planning service or the configured solver service."""
    service = getattr(request.app.state, "planning_service", None)
    if service is not None:
        return cast(PlanningService, service)
    return PlanningService(
        OrToolsCapacitySolver(SolverConfig(time_limit_seconds=settings.solver_time_limit_seconds))
    )


PlanningServiceDependency = Annotated[PlanningService, Depends(get_planning_service)]
