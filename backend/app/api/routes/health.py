"""Backend health endpoint."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend import __version__
from backend.app.api.dependencies import SettingsDependency


class HealthResponse(BaseModel):
    """Stable response returned by the service health endpoint."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDependency) -> HealthResponse:
    """Report process health without requiring external services or secrets."""
    return HealthResponse(
        service="manufacturing-po-route-optimizer-backend",
        version=__version__,
        environment=settings.app_environment,
    )
