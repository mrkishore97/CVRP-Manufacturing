"""Central API exception handlers with stable request-ID error envelopes."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.contracts import ApiErrorDetail, ApiErrorResponse, ApiRequestError
from backend.app.routing.base import RoutingProviderError

LOGGER = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown-request"))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: tuple[ApiErrorDetail, ...] = (),
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=ApiErrorResponse(
            request_id=_request_id(request),
            code=code,
            message=message,
            details=details,
        ).model_dump(mode="json"),
    )
    response.headers["X-Request-ID"] = _request_id(request)
    return response


def register_error_handlers(app: FastAPI) -> None:
    """Register controlled exception handlers for every API route."""

    @app.exception_handler(ApiRequestError)
    async def api_request_error_handler(
        request: Request,
        exc: ApiRequestError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            details=exc.details,
        )

    @app.exception_handler(RoutingProviderError)
    async def routing_error_handler(
        request: Request,
        exc: RoutingProviderError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=502,
            code=exc.code,
            message=str(exc),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = tuple(
            ApiErrorDetail(
                code=str(error.get("type", "validation_error")),
                field=".".join(str(part) for part in error.get("loc", ())),
                message=str(error.get("msg", "Invalid request.")),
            )
            for error in exc.errors()
        )
        return _error_response(
            request,
            status_code=422,
            code="REQUEST_VALIDATION_ERROR",
            message="Request body or parameters did not match the API contract.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        message = str(exc.detail) if exc.detail else "HTTP request failed."
        return _error_response(
            request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=message,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API error request_id=%s", _request_id(request))
        del exc
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message=("An unexpected backend error occurred. Provide the request ID to support."),
        )
