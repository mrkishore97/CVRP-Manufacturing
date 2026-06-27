"""API middleware for request IDs and coarse request-size limits."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from starlette.responses import JSONResponse

from backend.app.api.contracts import ApiErrorResponse
from backend.app.config import Settings

RequestHandler = Callable[[Request], Awaitable[Response]]


async def request_context_middleware(request: Request, call_next: RequestHandler) -> Response:
    """Attach/echo a request ID and reject bodies above the configured byte limit."""
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id

    settings = request.app.state.settings
    if isinstance(settings, Settings):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                body_size = int(content_length)
            except ValueError:
                body_size = 0
            if body_size > settings.api_max_request_bytes:
                payload_too_large_response = JSONResponse(
                    status_code=413,
                    content=ApiErrorResponse(
                        request_id=request_id,
                        code="PAYLOAD_TOO_LARGE",
                        message=(
                            "Request body exceeds the configured API size limit "
                            f"of {settings.api_max_request_bytes} bytes."
                        ),
                    ).model_dump(mode="json"),
                )
                payload_too_large_response.headers["X-Request-ID"] = request_id
                return payload_too_large_response

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
