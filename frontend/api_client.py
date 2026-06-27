"""HTTP-only client used by the Streamlit frontend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


class BackendClientError(RuntimeError):
    """Base class for controlled frontend-to-backend communication errors."""


class BackendUnavailableError(BackendClientError):
    """The backend could not be reached before the configured timeout."""


class BackendTimeoutError(BackendUnavailableError):
    """The backend did not respond before the client timeout."""


class BackendResponseError(BackendClientError):
    """The backend responded, but not with the expected contract."""


@dataclass(frozen=True, slots=True)
class ApiErrorDetail:
    """Structured API error detail copied from backend JSON."""

    code: str | None = None
    message: str | None = None
    field: str | None = None
    row_number: int | None = None
    task_id: str | None = None


class BackendApiError(BackendResponseError):
    """A controlled backend API error with stable code and request ID."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str | None,
        details: tuple[ApiErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.details = details


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Frontend representation of the backend health response."""

    status: str
    service: str
    version: str
    environment: str

    @classmethod
    def from_payload(cls, payload: Any) -> HealthStatus:
        """Validate the small M1 health contract without importing backend models."""
        if not isinstance(payload, dict):
            raise BackendResponseError("Backend health response was not a JSON object.")
        required = ("status", "service", "version", "environment")
        if any(not isinstance(payload.get(field), str) for field in required):
            raise BackendResponseError("Backend health response is missing required fields.")
        if payload["status"] != "ok":
            raise BackendResponseError("Backend reported an unhealthy status.")
        return cls(
            status=payload["status"],
            service=payload["service"],
            version=payload["version"],
            environment=payload["environment"],
        )


@dataclass(frozen=True, slots=True)
class ApiResult:
    """Generic parsed JSON API response used by the Streamlit workflow."""

    payload: dict[str, Any]
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """Small frontend view over the backend validation response."""

    valid: bool
    issues: tuple[dict[str, Any], ...] = ()
    normalized_request: dict[str, Any] | None = None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> ValidationSummary:
        validation = payload.get("validation")
        if not isinstance(validation, dict):
            raise BackendResponseError("Validation response is missing the validation object.")
        issues = validation.get("issues", ())
        if not isinstance(issues, list):
            raise BackendResponseError("Validation issues were not returned as a list.")
        normalized_request = validation.get("normalized_request")
        if normalized_request is not None and not isinstance(normalized_request, dict):
            raise BackendResponseError("Normalized request was not a JSON object.")
        return cls(
            valid=bool(validation.get("valid")),
            issues=tuple(issue for issue in issues if isinstance(issue, dict)),
            normalized_request=normalized_request,
        )


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """Small frontend view over the backend plan response."""

    plan_id: str
    status: str
    scheduled_task_ids: tuple[str, ...] = ()
    unscheduled_task_ids: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    routes: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> PlanSummary:
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise BackendResponseError("Solve response is missing the plan object.")
        return cls(
            plan_id=str(plan.get("plan_id", "")),
            status=str(plan.get("status", "")),
            scheduled_task_ids=tuple(str(value) for value in plan.get("scheduled_task_ids", ())),
            unscheduled_task_ids=tuple(
                str(value) for value in plan.get("unscheduled_task_ids", ())
            ),
            diagnostics=tuple(
                diagnostic
                for diagnostic in plan.get("diagnostics", ())
                if isinstance(diagnostic, dict)
            ),
            routes=tuple(route for route in plan.get("routes", ()) if isinstance(route, dict)),
        )


@dataclass(frozen=True, slots=True)
class WorkflowResponse:
    """Combined raw and summarized response for validation/solve actions."""

    raw: dict[str, Any]
    request_id: str | None = None
    validation: ValidationSummary | None = None
    plan: PlanSummary | None = None


class BackendClient:
    """Small synchronous client suitable for Streamlit's execution model."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        self._default_headers = default_headers or {}

    @classmethod
    def from_environment(cls) -> BackendClient:
        """Create a client using the public backend URL only."""
        return cls(os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000"))

    def get_health(self) -> HealthStatus:
        """Return backend health or a safe, user-facing error."""
        payload = self._request("GET", "/api/v1/health").payload
        return HealthStatus.from_payload(payload)

    def geocode(self, addresses: list[str]) -> ApiResult:
        """Resolve addresses through the backend routing provider."""
        return self._request(
            "POST",
            "/api/v1/locations/geocode",
            json_payload={"addresses": addresses},
        )

    def compute_matrix(
        self,
        locations: list[dict[str, Any]],
        *,
        force_refresh: bool = False,
    ) -> ApiResult:
        """Compute a route matrix through the backend."""
        return self._request(
            "POST",
            "/api/v1/matrices/compute",
            json_payload={"locations": locations, "force_refresh": force_refresh},
        )

    def validate_plan(self, payload: dict[str, Any]) -> WorkflowResponse:
        """Validate a planning payload and summarize the response."""
        result = self._request("POST", "/api/v1/plans/validate", json_payload=payload)
        return WorkflowResponse(
            raw=result.payload,
            request_id=result.request_id,
            validation=ValidationSummary.from_response(result.payload),
        )

    def solve_plan(self, payload: dict[str, Any]) -> WorkflowResponse:
        """Solve a planning payload and summarize the response."""
        result = self._request("POST", "/api/v1/plans/solve", json_payload=payload)
        return WorkflowResponse(
            raw=result.payload,
            request_id=result.request_id,
            validation=ValidationSummary.from_response(result.payload),
            plan=PlanSummary.from_response(result.payload),
        )

    def get_plan(self, plan_id: str) -> WorkflowResponse:
        """Retrieve a saved backend plan."""
        result = self._request("GET", f"/api/v1/plans/{plan_id}")
        return WorkflowResponse(
            raw=result.payload,
            request_id=result.request_id,
            plan=PlanSummary.from_response(result.payload),
        )

    def export_plan(self, plan_id: str) -> ApiResult:
        """Return backend JSON export rows for a plan."""
        return self._request("GET", f"/api/v1/plans/{plan_id}/export")

    def save_scenario(self, payload: dict[str, Any]) -> ApiResult:
        """Create or replace a scenario using the payload's scenario_id."""
        return self._request("POST", "/api/v1/scenarios", json_payload=payload)

    def load_scenario(self, scenario_id: str) -> ApiResult:
        """Retrieve a saved scenario payload."""
        return self._request("GET", f"/api/v1/scenarios/{scenario_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> ApiResult:
        """Execute one JSON request and normalize backend/network failures."""
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers=self._default_headers,
            ) as client:
                response = client.request(method, path, json=json_payload)
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                "The planning backend timed out. Try again or reduce the scenario size."
            ) from exc
        except httpx.RequestError as exc:
            raise BackendUnavailableError(
                "The planning backend is unavailable. Start the backend and try again."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            if response.is_error:
                raise BackendResponseError(
                    f"Backend returned HTTP {response.status_code} with a non-JSON response."
                ) from exc
            raise BackendResponseError("Backend response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise BackendResponseError("Backend response was not a JSON object.")

        request_id = response.headers.get("X-Request-ID")
        if not request_id and isinstance(payload.get("request_id"), str):
            request_id = str(payload["request_id"])

        if response.is_error:
            details = payload.get("details", ())
            parsed_details: list[ApiErrorDetail] = []
            if isinstance(details, list):
                for detail in details:
                    if isinstance(detail, dict):
                        parsed_details.append(
                            ApiErrorDetail(
                                code=(
                                    str(detail["code"]) if detail.get("code") is not None else None
                                ),
                                message=(
                                    str(detail["message"])
                                    if detail.get("message") is not None
                                    else None
                                ),
                                field=(
                                    str(detail["field"])
                                    if detail.get("field") is not None
                                    else None
                                ),
                                row_number=(
                                    int(detail["row_number"])
                                    if detail.get("row_number") is not None
                                    else None
                                ),
                                task_id=(
                                    str(detail["task_id"])
                                    if detail.get("task_id") is not None
                                    else None
                                ),
                            )
                        )
            raise BackendApiError(
                status_code=response.status_code,
                code=str(payload.get("code", "BACKEND_ERROR")),
                message=str(
                    payload.get("message", f"Backend returned HTTP {response.status_code}.")
                ),
                request_id=request_id,
                details=tuple(parsed_details),
            )

        return ApiResult(payload=payload, request_id=request_id)
