"""Non-secret runtime configuration for the planner UI."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.contracts import ConfigLimitsPayload, ConfigResponse
from backend.app.api.dependencies import RequestIdDependency, SettingsDependency

router = APIRouter(tags=["system"])

MAX_MATRIX_LOCATIONS = 100
"""Matches the location limit of ``POST /matrices/compute`` and ``/matrices/estimate``."""


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    settings: SettingsDependency,
    request_id: RequestIdDependency,
) -> ConfigResponse:
    """Report defaults and limits, and whether Google is configured, never the key."""
    return ConfigResponse(
        request_id=request_id,
        default_timezone=settings.plant_timezone,
        google_maps_configured=settings.google_maps_configured,
        geocode_region_code=settings.geocode_region_code,
        geocode_cache_ttl_seconds=settings.geocode_cache_ttl_seconds,
        geocode_max_plant_distance_km=settings.geocode_max_plant_distance_km,
        matrix_confirm_elements=settings.matrix_confirm_elements,
        solver_time_limit_seconds=settings.solver_time_limit_seconds,
        solver_max_time_limit_seconds=settings.solver_max_time_limit_seconds,
        plan_history_limit=settings.plan_history_limit,
        limits=ConfigLimitsPayload(
            max_request_bytes=settings.api_max_request_bytes,
            max_locations=settings.api_max_locations,
            max_tasks=settings.api_max_tasks,
            max_resolve_addresses=settings.api_max_geocode_addresses,
            max_matrix_locations=MAX_MATRIX_LOCATIONS,
        ),
    )
