"""Spreadsheet import previews; the backend owns the column contract (plan §9.5)."""

from __future__ import annotations

from fastapi import APIRouter, status

from backend.app.api.contracts import (
    ApiRequestError,
    ImportedLocationPayload,
    LocationImportPreviewRequest,
    LocationImportPreviewResponse,
)
from backend.app.api.dependencies import RequestIdDependency, SettingsDependency
from backend.app.domain.location_import import preview_location_import

router = APIRouter(tags=["imports"])


@router.post(
    "/imports/locations/preview",
    response_model=LocationImportPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_locations(
    request_body: LocationImportPreviewRequest,
    settings: SettingsDependency,
    request_id: RequestIdDependency,
) -> LocationImportPreviewResponse:
    """Map a location spreadsheet to name and address rows; nothing is stored."""
    if len(request_body.rows) > settings.api_max_locations:
        raise ApiRequestError(
            status_code=413,
            code="LOCATION_LIMIT_EXCEEDED",
            message=f"The file has more than {settings.api_max_locations} location rows.",
        )
    preview = preview_location_import(request_body.rows)
    return LocationImportPreviewResponse(
        request_id=request_id,
        valid=preview.valid,
        rows=tuple(ImportedLocationPayload.from_domain(row) for row in preview.rows),
        issues=preview.issues,
        column_mapping=dict(preview.column_mapping),
        unknown_columns=preview.unknown_columns,
    )
