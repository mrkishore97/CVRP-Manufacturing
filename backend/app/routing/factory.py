"""Construct routing providers from validated backend configuration."""

from backend.app.config import Settings
from backend.app.routing.base import RoutingProviderError
from backend.app.routing.errors import RoutingErrorCode
from backend.app.routing.estimator import RoutingLimits
from backend.app.routing.google import GoogleRoutingProvider


def google_provider_from_settings(settings: Settings) -> GoogleRoutingProvider:
    """Create the production Google adapter without exposing its credential."""
    api_key = settings.google_maps_api_key
    if api_key is None or not api_key.strip():
        raise RoutingProviderError(
            RoutingErrorCode.CONFIGURATION_ERROR,
            "GOOGLE_MAPS_API_KEY is not configured.",
        )
    return GoogleRoutingProvider(
        api_key=api_key,
        geocoding_url=settings.google_geocoding_url,
        routes_matrix_url=settings.google_routes_matrix_url,
        timeout_seconds=settings.routing_request_timeout_seconds,
        maximum_attempts=settings.routing_max_attempts,
        retry_base_delay_seconds=settings.routing_retry_base_delay_seconds,
        limits=RoutingLimits(
            maximum_origins=settings.routes_max_origins,
            maximum_destinations=settings.routes_max_destinations,
            maximum_elements=settings.routes_max_elements,
        ),
    )
