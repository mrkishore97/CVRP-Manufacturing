"""Spreadsheet import previews and templates; the backend owns the column contract.

Plan §9.5: one import contract, defined here and nowhere else. Previews map and check
rows without storing anything; the app applies a valid preview all-or-nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from backend.app.api.contracts import (
    ApiRequestError,
    ImportedLocationPayload,
    ImportedTaskPayload,
    ImportTemplateResponse,
    LocationImportPreviewRequest,
    LocationImportPreviewResponse,
    TaskImportPreviewRequest,
    TaskImportPreviewResponse,
)
from backend.app.api.dependencies import RequestIdDependency, SettingsDependency
from backend.app.domain.location_import import preview_location_import
from backend.app.domain.task_import import IMPORT_TEMPLATES, LocationRef, preview_task_import

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


@router.post(
    "/imports/tasks/preview",
    response_model=TaskImportPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_tasks(
    request_body: TaskImportPreviewRequest,
    settings: SettingsDependency,
    request_id: RequestIdDependency,
) -> TaskImportPreviewResponse:
    """Map a task spreadsheet to canonical task rows; nothing is stored."""
    if len(request_body.rows) > settings.api_max_tasks:
        raise ApiRequestError(
            status_code=413,
            code="TASK_LIMIT_EXCEEDED",
            message=f"The file has more than {settings.api_max_tasks} task rows.",
        )
    preview = preview_task_import(
        request_body.rows,
        locations=tuple(
            LocationRef(location_id=location.location_id, name=location.name)
            for location in request_body.locations
        ),
        plant_location_id=request_body.plant_location_id,
        timezone=request_body.timezone,
        default_pickup_service_minutes=request_body.default_pickup_service_minutes,
        default_delivery_service_minutes=request_body.default_delivery_service_minutes,
    )
    return TaskImportPreviewResponse(
        request_id=request_id,
        valid=preview.valid,
        rows=tuple(ImportedTaskPayload.from_domain(row) for row in preview.rows),
        issues=preview.issues,
        column_mapping=dict(preview.column_mapping),
        unknown_columns=preview.unknown_columns,
    )


@router.get(
    "/imports/templates/{kind}",
    response_model=ImportTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def import_template(kind: str, request_id: RequestIdDependency) -> ImportTemplateResponse:
    """Columns, aliases, and one example row for the ``tasks`` or ``locations`` template."""
    template = IMPORT_TEMPLATES.get(kind)
    if template is None:
        raise ApiRequestError(
            status_code=404,
            code="UNKNOWN_IMPORT_KIND",
            message="Import templates exist for 'tasks' and 'locations'.",
        )
    return ImportTemplateResponse.from_domain(template, request_id)
