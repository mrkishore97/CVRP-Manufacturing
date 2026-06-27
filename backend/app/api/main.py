"""FastAPI application factory and ASGI application."""

from fastapi import FastAPI

from backend import __version__
from backend.app.api.error_handlers import register_error_handlers
from backend.app.api.middleware import request_context_middleware
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.plans import router as plans_router
from backend.app.api.routes.routing import router as routing_router
from backend.app.api.routes.scenarios import router as scenarios_router
from backend.app.config import Settings, get_settings
from backend.app.logging_config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a backend application with explicit process-level dependencies."""
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    application = FastAPI(
        title="Manufacturing PO Route Optimizer API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.state.settings = active_settings
    application.middleware("http")(request_context_middleware)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(routing_router, prefix="/api/v1")
    application.include_router(plans_router, prefix="/api/v1")
    application.include_router(scenarios_router, prefix="/api/v1")
    register_error_handlers(application)
    return application


app = create_app()
