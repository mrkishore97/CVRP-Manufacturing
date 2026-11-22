"""Versioned scenario persistence endpoints: saved scenarios and their drafts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Body, Query, status

from backend.app.api.contracts import (
    ApiRequestError,
    DraftDeleteResponse,
    DraftRequest,
    DraftResponse,
    JsonObject,
    ScenarioDeleteResponse,
    ScenarioListResponse,
    ScenarioResponse,
    ScenarioSummaryPayload,
)
from backend.app.api.dependencies import (
    DraftRepositoryDependency,
    PlanRepositoryDependency,
    RequestIdDependency,
    ScenarioRepositoryDependency,
    SettingsDependency,
)
from backend.app.api.routes.plans import _enforce_planning_payload_limits
from backend.app.application.retention import (
    strip_expired_coordinates,
    without_unstorable_matrix,
)
from backend.app.config import Settings
from backend.app.persistence import PersistedDraft, PersistedScenario, ScenarioExistsError

router = APIRouter(tags=["scenarios"])
PAYLOAD_BODY = Body(...)
DRAFT_BODY = Body(...)
IF_EXISTS_QUERY = Query(
    default="replace",
    description=(
        "What to do when a scenario with this ID is already saved: replace it (the "
        "default, as in Version 1.0) or answer 409 SCENARIO_EXISTS (V1.1-M6)."
    ),
)
MAX_DRAFT_META_BYTES = 16_384


def _scenario_id_from_payload(payload: JsonObject) -> str:
    scenario_id = str(payload.get("scenario_id", "")).strip()
    if not scenario_id:
        raise ApiRequestError(
            status_code=422,
            code="SCENARIO_ID_REQUIRED",
            message="Scenario payload requires a non-empty scenario_id.",
        )
    return scenario_id


def _require_matching_ids(path_id: str, payload: JsonObject) -> None:
    if _scenario_id_from_payload(payload) != path_id:
        raise ApiRequestError(
            status_code=409,
            code="SCENARIO_ID_MISMATCH",
            message="Scenario ID in the path must match the payload scenario_id.",
        )


def _scenario_response(
    request_id: str,
    persisted: PersistedScenario,
    *,
    matrix_dropped: bool = False,
    expired_removed: int = 0,
    payload: JsonObject | None = None,
) -> ScenarioResponse:
    return ScenarioResponse(
        request_id=request_id,
        scenario_id=persisted.scenario_id,
        payload=payload if payload is not None else persisted.payload,
        created_at=persisted.created_at,
        updated_at=persisted.updated_at,
        routing_matrix_dropped=matrix_dropped,
        expired_coordinates_removed=expired_removed,
    )


def _without_expired(payload: JsonObject, settings: Settings) -> tuple[JsonObject, int]:
    return strip_expired_coordinates(
        payload,
        now=datetime.now(UTC),
        max_age_seconds=settings.geocode_cache_ttl_seconds,
    )


@router.get(
    "/scenarios",
    response_model=ScenarioListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_scenarios(
    request_id: RequestIdDependency,
    repository: ScenarioRepositoryDependency,
    plan_repository: PlanRepositoryDependency,
) -> ScenarioListResponse:
    """Saved scenarios with their names and row counts, most recently updated first."""
    plan_counts = plan_repository.counts_by_scenario()
    return ScenarioListResponse(
        request_id=request_id,
        scenarios=tuple(
            ScenarioSummaryPayload.from_domain(
                summary, plan_count=plan_counts.get(summary.scenario_id, 0)
            )
            for summary in repository.list_summaries()
        ),
    )


@router.post(
    "/scenarios",
    response_model=ScenarioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_scenario(
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    repository: ScenarioRepositoryDependency,
    payload: JsonObject = PAYLOAD_BODY,
    if_exists: Literal["replace", "error"] = IF_EXISTS_QUERY,
) -> ScenarioResponse:
    """Create or replace a scenario payload under its embedded scenario ID.

    With ``if_exists=error`` an existing ID is never overwritten (Save as, Duplicate,
    and the app's overwrite guard). An embedded Google matrix is not stored (decision
    D6); the response says so.
    """
    _enforce_planning_payload_limits(payload, settings)
    scenario_id = _scenario_id_from_payload(payload)
    storable, dropped = without_unstorable_matrix(payload)
    try:
        persisted = repository.save(scenario_id, storable, overwrite=if_exists == "replace")
    except ScenarioExistsError as exc:
        raise ApiRequestError(
            status_code=409,
            code="SCENARIO_EXISTS",
            message=str(exc),
        ) from exc
    return _scenario_response(request_id, persisted, matrix_dropped=dropped)


@router.put(
    "/scenarios/{scenario_id}",
    response_model=ScenarioResponse,
    status_code=status.HTTP_200_OK,
)
async def update_scenario(
    scenario_id: str,
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    repository: ScenarioRepositoryDependency,
    payload: JsonObject = PAYLOAD_BODY,
) -> ScenarioResponse:
    """Replace a scenario payload, requiring path and body IDs to agree."""
    _enforce_planning_payload_limits(payload, settings)
    _require_matching_ids(scenario_id, payload)
    storable, dropped = without_unstorable_matrix(payload)
    persisted = repository.save(scenario_id, storable)
    return _scenario_response(request_id, persisted, matrix_dropped=dropped)


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioResponse,
    status_code=status.HTTP_200_OK,
)
async def get_scenario(
    scenario_id: str,
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    repository: ScenarioRepositoryDependency,
) -> ScenarioResponse:
    """Retrieve a saved scenario; coordinates past the 30-day limit are removed (D2)."""
    persisted = repository.get(scenario_id)
    if persisted is None:
        raise ApiRequestError(
            status_code=404,
            code="SCENARIO_NOT_FOUND",
            message=f"Scenario does not exist: {scenario_id}",
        )
    payload, removed = _without_expired(persisted.payload, settings)
    if removed:
        repository.replace_payload(scenario_id, payload)
    return _scenario_response(request_id, persisted, expired_removed=removed, payload=payload)


@router.delete(
    "/scenarios/{scenario_id}",
    response_model=ScenarioDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_scenario(
    scenario_id: str,
    request_id: RequestIdDependency,
    repository: ScenarioRepositoryDependency,
    plan_repository: PlanRepositoryDependency,
    draft_repository: DraftRepositoryDependency,
) -> ScenarioDeleteResponse:
    """Delete a saved scenario together with its stored plans and its draft."""
    if repository.get(scenario_id) is None:
        raise ApiRequestError(
            status_code=404,
            code="SCENARIO_NOT_FOUND",
            message=f"Scenario does not exist: {scenario_id}",
        )
    plans_removed = plan_repository.delete_for_scenario(scenario_id)
    draft_removed = draft_repository.delete(scenario_id)
    repository.delete(scenario_id)
    return ScenarioDeleteResponse(
        request_id=request_id,
        scenario_id=scenario_id,
        plans_removed=plans_removed,
        draft_removed=draft_removed,
    )


def _draft_response(
    request_id: str,
    draft: PersistedDraft,
    *,
    payload: JsonObject | None = None,
    matrix_dropped: bool = False,
    expired_removed: int = 0,
) -> DraftResponse:
    return DraftResponse(
        request_id=request_id,
        scenario_id=draft.scenario_id,
        payload=payload if payload is not None else draft.payload,
        meta=draft.meta,
        updated_at=draft.updated_at,
        routing_matrix_dropped=matrix_dropped,
        expired_coordinates_removed=expired_removed,
    )


@router.put(
    "/scenarios/{scenario_id}/draft",
    response_model=DraftResponse,
    status_code=status.HTTP_200_OK,
)
async def put_draft(
    scenario_id: str,
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    drafts: DraftRepositoryDependency,
    body: DraftRequest = DRAFT_BODY,
) -> DraftResponse:
    """Keep the working copy after a change, so a browser refresh loses nothing.

    It never changes the saved scenario. A Google matrix is not kept (decision D6).
    """
    _enforce_planning_payload_limits(body.payload, settings)
    _require_matching_ids(scenario_id, body.payload)
    if len(json.dumps(body.meta, separators=(",", ":"))) > MAX_DRAFT_META_BYTES:
        raise ApiRequestError(
            status_code=413,
            code="DRAFT_META_TOO_LARGE",
            message=f"Draft meta is larger than {MAX_DRAFT_META_BYTES} bytes.",
        )
    storable, dropped = without_unstorable_matrix(body.payload)
    draft = drafts.put(scenario_id, storable, body.meta)
    return _draft_response(request_id, draft, matrix_dropped=dropped)


@router.get(
    "/scenarios/{scenario_id}/draft",
    response_model=DraftResponse,
    status_code=status.HTTP_200_OK,
)
async def get_draft(
    scenario_id: str,
    request_id: RequestIdDependency,
    settings: SettingsDependency,
    drafts: DraftRepositoryDependency,
) -> DraftResponse:
    """The working copy kept for this scenario ID; 404 when there is none."""
    draft = drafts.get(scenario_id)
    if draft is None:
        raise ApiRequestError(
            status_code=404,
            code="DRAFT_NOT_FOUND",
            message=f"No draft is kept for scenario {scenario_id}.",
        )
    payload, removed = _without_expired(draft.payload, settings)
    if removed:
        drafts.replace_payload(scenario_id, payload)
    return _draft_response(request_id, draft, payload=payload, expired_removed=removed)


@router.delete(
    "/scenarios/{scenario_id}/draft",
    response_model=DraftDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_draft(
    scenario_id: str,
    request_id: RequestIdDependency,
    drafts: DraftRepositoryDependency,
) -> DraftDeleteResponse:
    """Discard the working copy; answers ``deleted: false`` when there was none."""
    return DraftDeleteResponse(
        request_id=request_id,
        scenario_id=scenario_id,
        deleted=drafts.delete(scenario_id),
    )
