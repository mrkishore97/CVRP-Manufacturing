"""FastAPI application factory and ASGI application."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import __version__
from backend.app.api.dependencies import database_for_app
from backend.app.api.error_handlers import register_error_handlers
from backend.app.api.middleware import request_context_middleware
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.imports import router as imports_router
from backend.app.api.routes.locations import router as locations_router
from backend.app.api.routes.plans import router as plans_router
from backend.app.api.routes.routing import router as routing_router
from backend.app.api.routes.scenarios import router as scenarios_router
from backend.app.api.routes.system import router as system_router
from backend.app.application.retention import RetentionSweep, sweep_unstorable_matrices
from backend.app.config import Settings, get_settings
from backend.app.logging_config import configure_logging
from backend.app.persistence import SQLiteGeocodeCache

LOGGER = logging.getLogger(__name__)


def purge_expired_geocodes(application: FastAPI, settings: Settings) -> int:
    """Delete geocode cache rows past the retention limit; run at backend start."""
    cache = SQLiteGeocodeCache(
        database_for_app(application, settings),
        ttl_seconds=settings.geocode_cache_ttl_seconds,
    )
    removed = cache.purge_expired()
    if removed:
        LOGGER.info("Purged %s expired geocode cache entries at start-up", removed)
    return removed


def purge_unstorable_matrices(application: FastAPI, settings: Settings) -> RetentionSweep:
    """Remove Google matrices that Version 1.0 cached or saved (decision D6)."""
    return sweep_unstorable_matrices(database_for_app(application, settings))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a backend application with explicit process-level dependencies."""
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        purge_expired_geocodes(application, active_settings)
        purge_unstorable_matrices(application, active_settings)
        yield

    application = FastAPI(
        title="Manufacturing PO Route Optimizer API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.middleware("http")(request_context_middleware)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(system_router, prefix="/api/v1")
    application.include_router(locations_router, prefix="/api/v1")
    application.include_router(routing_router, prefix="/api/v1")
    application.include_router(plans_router, prefix="/api/v1")
    application.include_router(scenarios_router, prefix="/api/v1")
    application.include_router(imports_router, prefix="/api/v1")
    register_error_handlers(application)
    return application


app = create_app()
