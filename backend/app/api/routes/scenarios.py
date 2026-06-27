"""Versioned scenario persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, status

from backend.app.api.contracts import ApiRequestError, JsonObject, ScenarioResponse
from backend.app.api.dependencies import (
    RequestIdDependency,
    ScenarioRepositoryDependency,
    SettingsDependency,
)
from backend.app.api.routes.plans import _enforce_planning_payload_limits
from backend.app.persistence import PersistedScenario

router = APIRouter(tags=["scenarios"])
PAYLOAD_BODY = Body(...)


def _scenario_id_from_payload(payload: JsonObject) -> str:
    scenario_id = str(payload.get("scenario_id", "")).strip()
    if not scenario_id:
        raise ApiRequestError(
            status_code=422,
            code="SCENARIO_ID_REQUIRED",
            message="Scenario payload requires a non-empty scenario_id.",
        )
    return scenario_id


def _scenario_response(request_id: str, persisted: PersistedScenario) -> ScenarioResponse:
    return ScenarioResponse(
        request_id=request_id,
        scenario_id=persisted.scenario_id,
        payload=persisted.payload,
        created_at=persisted.created_at,
        updated_at=persisted.updated_at,
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
) -> ScenarioResponse:
    """Create or replace a scenario payload under its embedded scenario ID."""
    _enforce_planning_payload_limits(payload, settings)
    scenario_id = _scenario_id_from_payload(payload)
    persisted = repository.save(scenario_id, payload)
    return _scenario_response(request_id, persisted)


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
    body_scenario_id = _scenario_id_from_payload(payload)
    if body_scenario_id != scenario_id:
        raise ApiRequestError(
            status_code=409,
            code="SCENARIO_ID_MISMATCH",
            message="Scenario ID in the path must match the payload scenario_id.",
        )
    persisted = repository.save(scenario_id, payload)
    return _scenario_response(request_id, persisted)


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioResponse,
    status_code=status.HTTP_200_OK,
)
async def get_scenario(
    scenario_id: str,
    request_id: RequestIdDependency,
    repository: ScenarioRepositoryDependency,
) -> ScenarioResponse:
    """Retrieve a saved scenario payload."""
    persisted = repository.get(scenario_id)
    if persisted is None:
        raise ApiRequestError(
            status_code=404,
            code="SCENARIO_NOT_FOUND",
            message=f"Scenario does not exist: {scenario_id}",
        )
    return _scenario_response(request_id, persisted)
