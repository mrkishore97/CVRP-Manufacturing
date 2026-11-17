"""Address resolution by location ID with per-row match status."""

from __future__ import annotations

from fastapi import APIRouter, status

from backend.app.api.contracts import (
    ApiRequestError,
    LocationResolutionPayload,
    LocationResolveRequest,
    LocationResolveResponse,
    ResolveSummaryPayload,
)
from backend.app.api.dependencies import (
    LocationServiceDependency,
    RequestIdDependency,
    SettingsDependency,
)
from backend.app.application.location_service import AddressRequest, PlantCoordinates

router = APIRouter(tags=["locations"])


@router.post(
    "/locations/resolve",
    response_model=LocationResolveResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_locations(
    request_body: LocationResolveRequest,
    location_service: LocationServiceDependency,
    settings: SettingsDependency,
    request_id: RequestIdDependency,
) -> LocationResolveResponse:
    """Resolve addresses; one unmatched address is a row status, not a failed request."""
    if len(request_body.locations) > settings.api_max_geocode_addresses:
        raise ApiRequestError(
            status_code=413,
            code="RESOLVE_LIMIT_EXCEEDED",
            message=(
                f"Request contains more than {settings.api_max_geocode_addresses} "
                "addresses to resolve."
            ),
        )
    if request_body.region_code is None:
        region_code = settings.geocode_region_code
    else:
        region_code = request_body.region_code or None
    plant_coordinates = (
        PlantCoordinates(
            latitude=request_body.plant_coordinates.latitude,
            longitude=request_body.plant_coordinates.longitude,
        )
        if request_body.plant_coordinates is not None
        else None
    )
    outcome = await location_service.resolve(
        tuple(
            AddressRequest(
                location_id=location.location_id,
                address=location.address,
                confirmed_place_id=location.confirmed_place_id,
            )
            for location in request_body.locations
        ),
        region_code=region_code,
        plant_location_id=request_body.plant_location_id,
        plant_coordinates=plant_coordinates,
        force_refresh=request_body.force_refresh,
    )
    summary = outcome.summary
    return LocationResolveResponse(
        request_id=request_id,
        region_code=outcome.region_code,
        results=tuple(LocationResolutionPayload.from_domain(result) for result in outcome.results),
        summary=ResolveSummaryPayload(
            resolved=summary.resolved,
            needs_review=summary.needs_review,
            failed=summary.failed,
            cache_hits=summary.cache_hits,
            provider_calls=summary.provider_calls,
            unique_addresses=summary.unique_addresses,
            plant_distance_checked=summary.plant_distance_checked,
        ),
    )
