"""Stable Google routing error taxonomy and secret redaction helpers."""

from enum import StrEnum
from urllib.parse import quote_plus


class RoutingErrorCode(StrEnum):
    """Errors that application and frontend layers can handle consistently."""

    CONFIGURATION_ERROR = "ROUTING_CONFIGURATION_ERROR"
    AUTH_ERROR = "ROUTING_AUTH_ERROR"
    RATE_LIMIT = "ROUTING_RATE_LIMIT"
    TIMEOUT = "ROUTING_TIMEOUT"
    NETWORK_ERROR = "ROUTING_NETWORK_ERROR"
    SERVER_ERROR = "ROUTING_SERVER_ERROR"
    INVALID_REQUEST = "ROUTING_INVALID_REQUEST"
    INVALID_RESPONSE = "ROUTING_INVALID_RESPONSE"
    PARTIAL_RESPONSE = "ROUTING_PARTIAL_RESPONSE"
    GEOCODE_NOT_FOUND = "GEOCODE_NOT_FOUND"
    UNREACHABLE_ROUTE = "UNREACHABLE_ROUTE"
    REQUEST_TOO_LARGE = "ROUTING_REQUEST_TOO_LARGE"


def redact_secret(value: str, secret: str | None) -> str:
    """Remove raw and URL-encoded key forms from diagnostic text."""
    if not secret:
        return value
    redacted = value.replace(secret, "[REDACTED]")
    encoded = quote_plus(secret)
    if encoded != secret:
        redacted = redacted.replace(encoded, "[REDACTED]")
    return redacted
