"""Backend runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated backend settings.

    No Google key is required during M1. The optional field is present so secrets
    have a backend-only home when the Google adapter is implemented in M3.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_environment: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    plant_timezone: str = Field(
        default="America/Toronto",
        validation_alias="PLANT_TIMEZONE",
    )
    backend_host: str = Field(default="127.0.0.1", validation_alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, ge=1, le=65535, validation_alias="BACKEND_PORT")
    database_path: Path = Field(
        default=Path("data/route_optimizer.db"),
        validation_alias="DATABASE_PATH",
    )
    google_maps_api_key: str | None = Field(
        default=None,
        validation_alias="GOOGLE_MAPS_API_KEY",
        repr=False,
    )
    google_geocoding_url: str = Field(
        default="https://maps.googleapis.com/maps/api/geocode/json",
        validation_alias="GOOGLE_GEOCODING_URL",
    )
    google_routes_matrix_url: str = Field(
        default="https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
        validation_alias="GOOGLE_ROUTES_MATRIX_URL",
    )
    routing_request_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        validation_alias="ROUTING_REQUEST_TIMEOUT_SECONDS",
    )
    routing_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="ROUTING_MAX_ATTEMPTS",
    )
    routing_retry_base_delay_seconds: float = Field(
        default=0.25,
        ge=0,
        validation_alias="ROUTING_RETRY_BASE_DELAY_SECONDS",
    )
    routes_max_origins: int = Field(
        default=25,
        ge=1,
        le=50,
        validation_alias="ROUTES_MAX_ORIGINS",
    )
    routes_max_destinations: int = Field(
        default=25,
        ge=1,
        le=50,
        validation_alias="ROUTES_MAX_DESTINATIONS",
    )
    routes_max_elements: int = Field(
        default=625,
        ge=1,
        le=625,
        validation_alias="ROUTES_MAX_ELEMENTS",
    )
    matrix_cache_ttl_seconds: int = Field(
        default=86_400,
        ge=1,
        validation_alias="MATRIX_CACHE_TTL_SECONDS",
    )
    matrix_departure_bucket_minutes: int = Field(
        default=60,
        ge=1,
        le=1_440,
        validation_alias="MATRIX_DEPARTURE_BUCKET_MINUTES",
    )
    solver_time_limit_seconds: int = Field(
        default=10,
        ge=1,
        le=300,
        validation_alias="SOLVER_TIME_LIMIT_SECONDS",
    )
    api_max_request_bytes: int = Field(
        default=2_000_000,
        ge=1_024,
        validation_alias="API_MAX_REQUEST_BYTES",
    )
    api_max_locations: int = Field(
        default=200,
        ge=1,
        le=5_000,
        validation_alias="API_MAX_LOCATIONS",
    )
    api_max_tasks: int = Field(
        default=1_000,
        ge=1,
        le=50_000,
        validation_alias="API_MAX_TASKS",
    )
    api_max_geocode_addresses: int = Field(
        default=100,
        ge=1,
        le=5_000,
        validation_alias="API_MAX_GEOCODE_ADDRESSES",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one validated settings object per backend process."""
    return Settings()
