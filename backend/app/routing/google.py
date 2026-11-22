"""Google Geocoding and Routes Compute Route Matrix adapter."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.domain.enums import GeocodeLocationType
from backend.app.domain.geocoding import normalize_address, normalize_region_code
from backend.app.domain.models import RoutingMatrix
from backend.app.routing.base import (
    AddressResolution,
    GeocodeCandidate,
    RoutingLocation,
    RoutingOptions,
    RoutingProviderError,
)
from backend.app.routing.errors import RoutingErrorCode, redact_secret
from backend.app.routing.estimator import (
    MatrixBatch,
    RoutingLimits,
    plan_matrix_batches,
)

LOGGER = logging.getLogger(__name__)
TRANSPORT_LOGGER_NAMES = ("httpx", "httpcore")
GOOGLE_FIELD_MASK = "originIndex,destinationIndex,status,condition,distanceMeters,duration"
DURATION_PATTERN = re.compile(r"^(?P<seconds>\d+)(?:\.(?P<fraction>\d{1,9}))?s$")
SleepFunction = Callable[[float], Awaitable[None]]
JitterFunction = Callable[[float, float], float]
NowFunction = Callable[[], datetime]
MAX_PROVIDER_REASON_LENGTH = 300
KEY_LIKE_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


def provider_reason(text: object, *, secret: str | None = None) -> str | None:
    """Google's own explanation of a rejection, made safe to show to the planner.

    The key is removed (as given, URL-encoded, or anything shaped like a Google key),
    the text is one line, and it is cut to a bounded length. Without a reason the
    error still carries the stable code and the HTTP status. The reason is never
    logged: a request echo could contain coordinates.
    """
    if not isinstance(text, str):
        return None
    cleaned = KEY_LIKE_PATTERN.sub("[REDACTED]", " ".join(redact_secret(text, secret).split()))
    if not cleaned:
        return None
    if len(cleaned) > MAX_PROVIDER_REASON_LENGTH:
        cleaned = cleaned[: MAX_PROVIDER_REASON_LENGTH - 1].rstrip() + "…"
    return cleaned


def with_reason(message: str, reason: str | None) -> str:
    return f"{message} Google says: {reason}" if reason else message


def quiet_transport_loggers() -> None:
    """Stop httpx logging request URLs.

    httpx logs every request URL at INFO. Geocoding URLs carry the API key and the
    raw address in the query string, so at the default log level both would reach
    the backend log. Only warnings and errors from the transport are kept.
    """
    for name in TRANSPORT_LOGGER_NAMES:
        transport_logger = logging.getLogger(name)
        if transport_logger.level < logging.WARNING:  # includes NOTSET
            transport_logger.setLevel(logging.WARNING)


class GoogleRoutingProvider:
    """Server-side Google routing provider with bounded retry behavior."""

    def __init__(
        self,
        *,
        api_key: str,
        geocoding_url: str = "https://maps.googleapis.com/maps/api/geocode/json",
        routes_matrix_url: str = (
            "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
        ),
        timeout_seconds: float = 15.0,
        maximum_attempts: int = 3,
        retry_base_delay_seconds: float = 0.25,
        limits: RoutingLimits | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFunction = asyncio.sleep,
        jitter: JitterFunction = random.uniform,
        now: NowFunction | None = None,
    ) -> None:
        if not api_key.strip():
            raise RoutingProviderError(
                RoutingErrorCode.CONFIGURATION_ERROR,
                "Google Maps API key is not configured.",
            )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if maximum_attempts <= 0:
            raise ValueError("maximum_attempts must be positive")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds cannot be negative")
        quiet_transport_loggers()
        self._api_key = api_key
        self._geocoding_url = geocoding_url
        self._routes_matrix_url = routes_matrix_url
        self._timeout_seconds = timeout_seconds
        self._maximum_attempts = maximum_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._limits = limits or RoutingLimits()
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def provider_name(self) -> str:
        return "google_routes"

    @property
    def matrix_storage_allowed(self) -> bool:
        """Decision D6: Routes API distances and durations are never stored."""
        return False

    @property
    def limits(self) -> RoutingLimits:
        return self._limits

    async def _wait_before_retry(self, failed_attempt: int) -> None:
        base_delay = self._retry_base_delay_seconds * (2 ** (failed_attempt - 1))
        jitter = self._jitter(0.0, self._retry_base_delay_seconds)
        await self._sleep(base_delay + jitter)

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(1, self._maximum_attempts + 1):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                LOGGER.warning(
                    "Google %s timed out on attempt %s of %s",
                    operation,
                    attempt,
                    self._maximum_attempts,
                )
                if attempt < self._maximum_attempts:
                    await self._wait_before_retry(attempt)
                    continue
                raise RoutingProviderError(
                    RoutingErrorCode.TIMEOUT,
                    f"Google {operation} timed out after bounded retries.",
                ) from None
            except httpx.RequestError:
                LOGGER.warning(
                    "Google %s network failure on attempt %s of %s",
                    operation,
                    attempt,
                    self._maximum_attempts,
                )
                if attempt < self._maximum_attempts:
                    await self._wait_before_retry(attempt)
                    continue
                raise RoutingProviderError(
                    RoutingErrorCode.NETWORK_ERROR,
                    f"Google {operation} could not be reached after bounded retries.",
                ) from None

            if response.status_code < 400:
                return response

            code, message, retryable = self._map_http_error(response.status_code, operation)
            LOGGER.warning(
                "Google %s returned HTTP %s on attempt %s of %s",
                operation,
                response.status_code,
                attempt,
                self._maximum_attempts,
            )
            if retryable and attempt < self._maximum_attempts:
                await self._wait_before_retry(attempt)
                continue
            raise RoutingProviderError(
                code, with_reason(message, self._http_error_reason(response))
            )

        raise AssertionError("bounded request loop ended unexpectedly")

    @staticmethod
    def _map_http_error(
        status_code: int,
        operation: str,
    ) -> tuple[RoutingErrorCode, str, bool]:
        if status_code in {401, 403}:
            return (
                RoutingErrorCode.AUTH_ERROR,
                f"Google {operation} authentication or API restrictions rejected the request.",
                False,
            )
        if status_code == 429:
            return (
                RoutingErrorCode.RATE_LIMIT,
                f"Google {operation} rate limit was reached after bounded retries.",
                True,
            )
        if 500 <= status_code <= 599:
            return (
                RoutingErrorCode.SERVER_ERROR,
                f"Google {operation} service failed after bounded retries.",
                True,
            )
        return (
            RoutingErrorCode.INVALID_REQUEST,
            f"Google {operation} rejected the request with HTTP {status_code}.",
            False,
        )

    def _http_error_reason(self, response: httpx.Response) -> str | None:
        """The ``error.message`` of a Google error body, if it has one.

        Routes answers ``{"error": {"code", "message", "status"}}``, sometimes wrapped
        in a one-item list; the Geocoding API uses ``error_message``.
        """
        try:
            body = response.json()
        except ValueError:
            return None
        if isinstance(body, list) and len(body) == 1:
            body = body[0]
        if not isinstance(body, dict):
            return None
        error = body.get("error")
        text = error.get("message") if isinstance(error, dict) else body.get("error_message")
        return provider_reason(text, secret=self._api_key)

    @staticmethod
    def _response_json(response: httpx.Response, operation: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                f"Google {operation} returned malformed JSON.",
            ) from exc

    async def geocode(self, addresses: Sequence[str]) -> tuple[RoutingLocation, ...]:
        """Geocode unique addresses once and preserve original request order.

        Version 1.0 contract: no region bias, the first match wins, and an address
        with no match fails the whole request with ``GEOCODE_NOT_FOUND``.
        """
        if not addresses:
            return ()
        normalized_addresses: list[str] = []
        unique_addresses: dict[str, str] = {}
        for address in addresses:
            normalized = normalize_address(address)
            if not normalized:
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_REQUEST,
                    "Address cannot be empty.",
                )
            normalized_addresses.append(normalized)
            unique_addresses.setdefault(normalized, address.strip())

        resolved: dict[str, RoutingLocation] = {}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            for normalized, original in unique_addresses.items():
                resolved[normalized] = await self._geocode_one(client, original, normalized)
        return tuple(resolved[normalized] for normalized in normalized_addresses)

    async def resolve_address(
        self,
        address: str,
        *,
        region_code: str | None = None,
    ) -> AddressResolution:
        """Return every Google candidate for one address, with match-quality fields.

        No match returns an empty resolution; key, quota, and transport failures
        raise ``RoutingProviderError`` with the stable codes.
        """
        normalized = normalize_address(address)
        if not normalized:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_REQUEST,
                "Address cannot be empty.",
            )
        try:
            region = normalize_region_code(region_code)
        except ValueError as exc:
            raise RoutingProviderError(RoutingErrorCode.INVALID_REQUEST, str(exc)) from None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            return await self._request_geocode(
                client,
                address.strip(),
                normalized,
                region_code=region,
            )

    async def _geocode_one(
        self,
        client: httpx.AsyncClient,
        address: str,
        normalized_address: str,
    ) -> RoutingLocation:
        resolution = await self._request_geocode(
            client,
            address,
            normalized_address,
            region_code=None,
        )
        best = resolution.best
        if best is None:
            raise RoutingProviderError(
                RoutingErrorCode.GEOCODE_NOT_FOUND,
                f"Google geocoding found no match for address hash "
                f"{self._address_hash(normalized_address)}.",
            )
        return RoutingLocation(
            location_id=f"GEO-{self._address_hash(normalized_address)}",
            formatted_address=best.formatted_address,
            latitude=best.latitude,
            longitude=best.longitude,
            place_id=best.place_id,
        )

    async def _request_geocode(
        self,
        client: httpx.AsyncClient,
        address: str,
        normalized_address: str,
        *,
        region_code: str | None,
    ) -> AddressResolution:
        params = {"address": address, "key": self._api_key}
        if region_code is not None:
            params["region"] = region_code
        for api_attempt in range(1, self._maximum_attempts + 1):
            response = await self._send(
                client,
                "GET",
                self._geocoding_url,
                operation="geocoding",
                params=params,
            )
            payload = self._response_json(response, "geocoding")
            if not isinstance(payload, dict):
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_RESPONSE,
                    "Google geocoding response was not an object.",
                )
            status = payload.get("status")
            if status == "OK":
                return self._parse_geocode_results(payload)
            if status == "ZERO_RESULTS":
                LOGGER.info(
                    "Google geocoding found no match for address hash %s",
                    self._address_hash(normalized_address),
                )
                return AddressResolution()
            reason = provider_reason(payload.get("error_message"), secret=self._api_key)
            if status == "REQUEST_DENIED":
                raise RoutingProviderError(
                    RoutingErrorCode.AUTH_ERROR,
                    with_reason(
                        "Google geocoding authentication or API restrictions rejected the request.",
                        reason,
                    ),
                )
            if status == "INVALID_REQUEST":
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_REQUEST,
                    with_reason("Google geocoding rejected an invalid address request.", reason),
                )
            if status in {"OVER_DAILY_LIMIT", "OVER_QUERY_LIMIT"}:
                if api_attempt < self._maximum_attempts:
                    await self._wait_before_retry(api_attempt)
                    continue
                raise RoutingProviderError(
                    RoutingErrorCode.RATE_LIMIT,
                    with_reason(
                        "Google geocoding quota was reached after bounded retries.", reason
                    ),
                )
            if status == "UNKNOWN_ERROR" and api_attempt < self._maximum_attempts:
                await self._wait_before_retry(api_attempt)
                continue
            if status == "UNKNOWN_ERROR":
                raise RoutingProviderError(
                    RoutingErrorCode.SERVER_ERROR,
                    "Google geocoding failed after bounded retries.",
                )
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google geocoding returned an unknown status.",
            )
        raise AssertionError("bounded geocoding loop ended unexpectedly")

    @staticmethod
    def _address_hash(normalized_address: str) -> str:
        return hashlib.sha256(normalized_address.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def _parse_geocode_results(cls, payload: dict[str, Any]) -> AddressResolution:
        """Parse the first result strictly and keep only well-formed alternatives."""
        results = payload.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google geocoding response did not contain a usable result.",
            )
        candidates = [cls._parse_candidate(results[0])]
        for alternative in results[1:]:
            if not isinstance(alternative, dict):
                continue
            try:
                candidates.append(cls._parse_candidate(alternative))
            except RoutingProviderError:
                LOGGER.info("Ignoring a malformed alternative Google geocoding result")
        return AddressResolution(candidates=tuple(candidates))

    @staticmethod
    def _parse_candidate(result: dict[str, Any]) -> GeocodeCandidate:
        geometry = result.get("geometry")
        location = geometry.get("location") if isinstance(geometry, dict) else None
        if not isinstance(location, dict):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google geocoding response did not contain coordinates.",
            )
        latitude = location.get("lat")
        longitude = location.get("lng")
        if (
            not isinstance(latitude, int | float)
            or isinstance(latitude, bool)
            or not isinstance(longitude, int | float)
            or isinstance(longitude, bool)
            or not -90 <= float(latitude) <= 90
            or not -180 <= float(longitude) <= 180
        ):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google geocoding returned invalid coordinates.",
            )
        formatted_address = result.get("formatted_address")
        place_id = result.get("place_id")
        if not isinstance(formatted_address, str) or not formatted_address.strip():
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google geocoding response did not contain a formatted address.",
            )
        raw_location_type = geometry.get("location_type") if isinstance(geometry, dict) else None
        try:
            location_type = (
                GeocodeLocationType(raw_location_type)
                if isinstance(raw_location_type, str)
                else None
            )
        except ValueError:
            location_type = None
        return GeocodeCandidate(
            formatted_address=formatted_address,
            latitude=float(latitude),
            longitude=float(longitude),
            place_id=place_id if isinstance(place_id, str) else None,
            location_type=location_type,
            partial_match=result.get("partial_match") is True,
        )

    async def compute_matrix(
        self,
        locations: Sequence[RoutingLocation],
        options: RoutingOptions,
    ) -> RoutingMatrix:
        """Calculate and strictly assemble a complete square road matrix."""
        if not locations:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_REQUEST,
                "At least one location is required for a route matrix.",
            )
        location_ids = tuple(location.location_id for location in locations)
        if len(location_ids) != len(set(location_ids)):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_REQUEST,
                "Route matrix location IDs must be unique.",
            )
        if options.departure_time is not None and options.departure_time <= self._now():
            # Google rejects a past departure time for driving with HTTP 400; say why
            # before sending anything.
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_REQUEST,
                "The departure time in the routing options is in the past, and Google "
                "accepts only a future departure time for driving. Clear it, or choose a "
                "later one, under Travel times > Advanced: routing options.",
            )
        batches = plan_matrix_batches(len(locations), self._limits, options)
        distances: list[list[int | None]] = [[None for _ in locations] for _ in locations]
        durations: list[list[int | None]] = [[None for _ in locations] for _ in locations]

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            for batch in batches:
                await self._compute_batch(
                    client,
                    locations,
                    options,
                    batch,
                    distances,
                    durations,
                )

        if any(value is None for row in distances for value in row) or any(
            value is None for row in durations for value in row
        ):
            raise RoutingProviderError(
                RoutingErrorCode.PARTIAL_RESPONSE,
                "Google Routes response did not cover the complete matrix.",
            )
        complete_distances = self._complete_matrix(distances)
        complete_durations = self._complete_matrix(durations)
        departure_time = (
            options.departure_time.astimezone(UTC) if options.departure_time is not None else None
        )
        return RoutingMatrix(
            location_ids=location_ids,
            distance_meters=complete_distances,
            duration_seconds=complete_durations,
            source=self.provider_name,
            travel_mode=options.travel_mode,
            routing_preference=options.routing_preference,
            departure_time=departure_time,
            created_at=self._now(),
        )

    @staticmethod
    def _complete_matrix(values: list[list[int | None]]) -> tuple[tuple[int, ...], ...]:
        completed: list[tuple[int, ...]] = []
        for row in values:
            if any(value is None for value in row):
                raise RoutingProviderError(
                    RoutingErrorCode.PARTIAL_RESPONSE,
                    "Google Routes response did not cover the complete matrix.",
                )
            completed.append(tuple(value for value in row if value is not None))
        return tuple(completed)

    async def _compute_batch(
        self,
        client: httpx.AsyncClient,
        locations: Sequence[RoutingLocation],
        options: RoutingOptions,
        batch: MatrixBatch,
        distances: list[list[int | None]],
        durations: list[list[int | None]],
    ) -> None:
        origins = locations[batch.origin_start : batch.origin_end]
        destinations = locations[batch.destination_start : batch.destination_end]
        payload: dict[str, Any] = {
            "origins": [self._route_waypoint(location) for location in origins],
            "destinations": [self._route_waypoint(location) for location in destinations],
            "travelMode": options.travel_mode.value,
            "routingPreference": options.routing_preference.value,
        }
        if options.departure_time is not None:
            payload["departureTime"] = (
                options.departure_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )
        response = await self._send(
            client,
            "POST",
            self._routes_matrix_url,
            operation="route matrix",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
            },
            json=payload,
        )
        elements = self._response_json(response, "route matrix")
        if not isinstance(elements, list):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix response was not a list.",
            )
        expected_count = batch.element_count
        if len(elements) != expected_count:
            raise RoutingProviderError(
                RoutingErrorCode.PARTIAL_RESPONSE,
                "Google Routes matrix response had an unexpected element count.",
            )

        seen: set[tuple[int, int]] = set()
        for element in elements:
            if not isinstance(element, dict):
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_RESPONSE,
                    "Google Routes matrix element was not an object.",
                )
            origin_index = element.get("originIndex")
            destination_index = element.get("destinationIndex")
            if (
                not isinstance(origin_index, int)
                or isinstance(origin_index, bool)
                or not isinstance(destination_index, int)
                or isinstance(destination_index, bool)
                or not 0 <= origin_index < batch.origin_count
                or not 0 <= destination_index < batch.destination_count
            ):
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_RESPONSE,
                    "Google Routes matrix element contained invalid indexes.",
                )
            local_pair = (origin_index, destination_index)
            if local_pair in seen:
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_RESPONSE,
                    "Google Routes matrix response contained duplicate elements.",
                )
            seen.add(local_pair)
            self._validate_route_condition(element)
            global_origin = batch.origin_start + origin_index
            global_destination = batch.destination_start + destination_index
            duration_seconds = self._parse_duration(element.get("duration"))
            distance = element.get("distanceMeters")
            if distance is None and global_origin == global_destination and duration_seconds == 0:
                # Protobuf JSON omits scalar fields at their default value. Google
                # therefore omits distanceMeters for valid zero-distance diagonal
                # elements while still returning ROUTE_EXISTS and duration "0s".
                distance = 0
            if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
                raise RoutingProviderError(
                    RoutingErrorCode.INVALID_RESPONSE,
                    "Google Routes matrix element contained invalid distance.",
                )
            distances[global_origin][global_destination] = distance
            durations[global_origin][global_destination] = duration_seconds

        if len(seen) != expected_count:
            raise RoutingProviderError(
                RoutingErrorCode.PARTIAL_RESPONSE,
                "Google Routes matrix response omitted required elements.",
            )

    @staticmethod
    def _route_waypoint(location: RoutingLocation) -> dict[str, Any]:
        return {
            "waypoint": {
                "location": {
                    "latLng": {
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                    }
                }
            }
        }

    @staticmethod
    def _validate_route_condition(element: dict[str, Any]) -> None:
        status = element.get("status", {})
        if not isinstance(status, dict):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix element contained invalid status.",
            )
        status_code = status.get("code", 0)
        condition = element.get("condition")
        if status_code not in {None, 0} or condition == "ROUTE_NOT_FOUND":
            raise RoutingProviderError(
                RoutingErrorCode.UNREACHABLE_ROUTE,
                "Google Routes reported an unreachable required route.",
            )
        if condition not in {None, "ROUTE_EXISTS"}:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix element contained an unknown condition.",
            )

    @staticmethod
    def _parse_duration(value: Any) -> int:
        if not isinstance(value, str):
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix element contained invalid duration.",
            )
        match = DURATION_PATTERN.fullmatch(value)
        if match is None:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix element contained malformed duration.",
            )
        try:
            seconds = Decimal(value[:-1]).to_integral_value(rounding=ROUND_CEILING)
        except InvalidOperation as exc:
            raise RoutingProviderError(
                RoutingErrorCode.INVALID_RESPONSE,
                "Google Routes matrix element contained malformed duration.",
            ) from exc
        return int(seconds)
