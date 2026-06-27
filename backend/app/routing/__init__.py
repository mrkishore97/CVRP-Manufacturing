"""Routing-provider contracts and adapters."""

from backend.app.routing.base import (
    RouteMatrix,
    RoutingLocation,
    RoutingOptions,
    RoutingProvider,
    RoutingProviderError,
)
from backend.app.routing.errors import RoutingErrorCode, redact_secret
from backend.app.routing.estimator import (
    MatrixBatch,
    MatrixRequestEstimate,
    RoutingLimits,
    estimate_matrix_request,
    plan_matrix_batches,
)
from backend.app.routing.factory import google_provider_from_settings
from backend.app.routing.fake import FakeRoutingProvider
from backend.app.routing.google import GoogleRoutingProvider

__all__ = [
    "FakeRoutingProvider",
    "GoogleRoutingProvider",
    "MatrixBatch",
    "MatrixRequestEstimate",
    "RouteMatrix",
    "RoutingErrorCode",
    "RoutingLimits",
    "RoutingLocation",
    "RoutingOptions",
    "RoutingProvider",
    "RoutingProviderError",
    "estimate_matrix_request",
    "google_provider_from_settings",
    "plan_matrix_batches",
    "redact_secret",
]
