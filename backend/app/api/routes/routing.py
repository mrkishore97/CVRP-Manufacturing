"""Versioned routing endpoints for geocoding and route matrices."""

from __future__ import annotations

from fastapi import APIRouter, status

from backend.app.api.contracts import (
    GeocodeRequest,
    GeocodeResponse,
    MatrixComputeRequest,
    MatrixComputeResponse,
    MatrixEstimateRequest,
    MatrixEstimateResponse,
    RoutingLocationPayload,
)
from backend.app.api.dependencies import (
    RequestIdDependency,
    RoutingServiceDependency,
    SettingsDependency,
)

router = APIRouter(tags=["routing"])


@router.post(
    "/locations/geocode",
    response_model=GeocodeResponse,
    status_code=status.HTTP_200_OK,
)
async def geocode_locations(
    request_body: GeocodeRequest,
    routing_service: RoutingServiceDependency,
    request_id: RequestIdDependency,
) -> GeocodeResponse:
    """Resolve one or more addresses through the configured routing provider."""
    locations = await routing_service.geocode(request_body.addresses)
    return GeocodeResponse(
        request_id=request_id,
        locations=tuple(RoutingLocationPayload.from_domain(location) for location in locations),
    )


@router.post(
    "/matrices/estimate",
    response_model=MatrixEstimateResponse,
    status_code=status.HTTP_200_OK,
)
async def estimate_matrix(
    request_body: MatrixEstimateRequest,
    routing_service: RoutingServiceDependency,
    settings: SettingsDependency,
    request_id: RequestIdDependency,
) -> MatrixEstimateResponse:
    """Report billable elements, request count, and cache status without calling Google."""
    result = routing_service.estimate_matrix(
        tuple(location.to_domain() for location in request_body.locations),
        request_body.options.to_domain(),
    )
    estimate = result.estimate
    billable = 0 if result.cache_hit else estimate.matrix_element_count
    return MatrixEstimateResponse(
        request_id=request_id,
        location_count=estimate.location_count,
        element_count=estimate.matrix_element_count,
        request_count=estimate.request_count,
        maximum_elements_per_request=estimate.maximum_elements_per_request,
        cache_hit=result.cache_hit,
        cache_key=result.cache_key,
        billable_element_count=billable,
        billable_request_count=0 if result.cache_hit else estimate.request_count,
        confirmation_threshold_elements=settings.matrix_confirm_elements,
        confirmation_required=billable > settings.matrix_confirm_elements,
    )


@router.post(
    "/matrices/compute",
    response_model=MatrixComputeResponse,
    status_code=status.HTTP_200_OK,
)
async def compute_matrix(
    request_body: MatrixComputeRequest,
    routing_service: RoutingServiceDependency,
    request_id: RequestIdDependency,
) -> MatrixComputeResponse:
    """Compute or retrieve a complete provider-neutral route matrix."""
    result = await routing_service.compute_matrix(
        tuple(location.to_domain() for location in request_body.locations),
        request_body.options.to_domain(),
        force_refresh=request_body.force_refresh,
    )
    return MatrixComputeResponse(
        request_id=request_id,
        matrix=result.matrix,
        cache_hit=result.cache_hit,
        cache_key=result.cache_key,
    )
