"""Backend runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.domain.geocoding import GEOCODE_MAX_AGE_SECONDS, normalize_region_code


class Settings(BaseSettings):
    """Validated backend settings.

    The Google key is optional: without it the API still validates, solves embedded
    matrices, and reports through ``GET /config`` that Google calls are unavailable.
    ``GEOCODE_CACHE_TTL_SECONDS`` cannot exceed 30 days (Google's caching limit).
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
    matrix_confirm_elements: int = Field(
        default=400,
        ge=1,
        validation_alias="MATRIX_CONFIRM_ELEMENTS",
    )
    geocode_region_code: str | None = Field(
        default="ca",
        validation_alias="GEOCODE_REGION_CODE",
    )
    geocode_cache_ttl_seconds: int = Field(
        default=GEOCODE_MAX_AGE_SECONDS,
        ge=1,
        le=GEOCODE_MAX_AGE_SECONDS,
        validation_alias="GEOCODE_CACHE_TTL_SECONDS",
    )
    geocode_max_plant_distance_km: float = Field(
        default=500.0,
        gt=0,
        le=20_100,
        validation_alias="GEOCODE_MAX_PLANT_DISTANCE_KM",
    )
    geocode_max_concurrency: int = Field(
        default=4,
        ge=1,
        le=10,
        validation_alias="GEOCODE_MAX_CONCURRENCY",
    )
    solver_time_limit_seconds: int = Field(
        default=10,
        ge=1,
        le=300,
        validation_alias="SOLVER_TIME_LIMIT_SECONDS",
    )
    solver_max_time_limit_seconds: int = Field(
        default=120,
        ge=1,
        le=3_600,
        validation_alias="SOLVER_MAX_TIME_LIMIT_SECONDS",
    )
    solver_in_subprocess: bool = Field(
        default=True,
        validation_alias="SOLVER_IN_SUBPROCESS",
        description="Solve in a worker process so the API stays responsive (V1.1-M5).",
    )
    plan_history_limit: int = Field(
        default=20,
        ge=1,
        le=1_000,
        validation_alias="PLAN_HISTORY_LIMIT",
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

    @field_validator("geocode_region_code", mode="before")
    @classmethod
    def normalize_geocode_region_code(cls, value: object) -> object:
        if value is None or isinstance(value, str):
            return normalize_region_code(value)
        return value

    @model_validator(mode="after")
    def default_time_limit_within_maximum(self) -> "Settings":
        if self.solver_time_limit_seconds > self.solver_max_time_limit_seconds:
            raise ValueError(
                "SOLVER_TIME_LIMIT_SECONDS must not exceed SOLVER_MAX_TIME_LIMIT_SECONDS"
            )
        return self

    @property
    def google_maps_configured(self) -> bool:
        """Whether a Google key is present, without revealing anything about it."""
        return bool(self.google_maps_api_key and self.google_maps_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one validated settings object per backend process."""
    return Settings()
