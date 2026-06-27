"""Matrix request estimation and provider-safe rectangular batching."""

from dataclasses import dataclass

from backend.app.domain.enums import RoutingPreference
from backend.app.routing.base import RoutingOptions


@dataclass(frozen=True, slots=True)
class RoutingLimits:
    """Configurable Google Routes request limits used by the batch planner."""

    maximum_origins: int = 25
    maximum_destinations: int = 25
    maximum_elements: int = 625
    traffic_aware_optimal_maximum_elements: int = 100

    def __post_init__(self) -> None:
        values = (
            self.maximum_origins,
            self.maximum_destinations,
            self.maximum_elements,
            self.traffic_aware_optimal_maximum_elements,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Routing limits must be positive")


@dataclass(frozen=True, slots=True)
class MatrixBatch:
    """One rectangular request slice using Python-exclusive end indexes."""

    origin_start: int
    origin_end: int
    destination_start: int
    destination_end: int

    @property
    def origin_count(self) -> int:
        return self.origin_end - self.origin_start

    @property
    def destination_count(self) -> int:
        return self.destination_end - self.destination_start

    @property
    def element_count(self) -> int:
        return self.origin_count * self.destination_count


@dataclass(frozen=True, slots=True)
class MatrixRequestEstimate:
    """Billable element and HTTP request estimate shown before calculation."""

    location_count: int
    matrix_element_count: int
    request_count: int
    maximum_elements_per_request: int


def effective_maximum_elements(limits: RoutingLimits, options: RoutingOptions) -> int:
    if options.routing_preference is RoutingPreference.TRAFFIC_AWARE_OPTIMAL:
        return min(limits.maximum_elements, limits.traffic_aware_optimal_maximum_elements)
    return limits.maximum_elements


def plan_matrix_batches(
    location_count: int,
    limits: RoutingLimits,
    options: RoutingOptions,
) -> tuple[MatrixBatch, ...]:
    """Split a square matrix into complete rectangular requests."""
    if location_count <= 0:
        raise ValueError("location_count must be positive")
    maximum_elements = effective_maximum_elements(limits, options)
    origin_chunk_size = min(limits.maximum_origins, maximum_elements, location_count)
    batches: list[MatrixBatch] = []
    for origin_start in range(0, location_count, origin_chunk_size):
        origin_end = min(origin_start + origin_chunk_size, location_count)
        origin_count = origin_end - origin_start
        destination_chunk_size = min(
            limits.maximum_destinations,
            maximum_elements // origin_count,
            location_count,
        )
        if destination_chunk_size <= 0:
            raise ValueError("Routing limits cannot fit one destination")
        for destination_start in range(0, location_count, destination_chunk_size):
            destination_end = min(destination_start + destination_chunk_size, location_count)
            batch = MatrixBatch(
                origin_start=origin_start,
                origin_end=origin_end,
                destination_start=destination_start,
                destination_end=destination_end,
            )
            if batch.element_count > maximum_elements:
                raise ValueError("Planned matrix batch exceeds maximum elements")
            batches.append(batch)
    return tuple(batches)


def estimate_matrix_request(
    location_count: int,
    limits: RoutingLimits,
    options: RoutingOptions,
) -> MatrixRequestEstimate:
    batches = plan_matrix_batches(location_count, limits, options)
    return MatrixRequestEstimate(
        location_count=location_count,
        matrix_element_count=location_count * location_count,
        request_count=len(batches),
        maximum_elements_per_request=effective_maximum_elements(limits, options),
    )
