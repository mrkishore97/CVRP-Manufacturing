"""Route-matrix request estimator and batching tests."""

from backend.app.domain.enums import RoutingPreference
from backend.app.routing import (
    RoutingLimits,
    RoutingOptions,
    estimate_matrix_request,
    plan_matrix_batches,
)


def test_estimator_reports_square_elements_and_requests() -> None:
    limits = RoutingLimits(maximum_origins=2, maximum_destinations=2, maximum_elements=4)

    estimate = estimate_matrix_request(5, limits, RoutingOptions())

    assert estimate.location_count == 5
    assert estimate.matrix_element_count == 25
    assert estimate.request_count == 9
    assert estimate.maximum_elements_per_request == 4


def test_batches_cover_every_pair_exactly_once_within_limits() -> None:
    limits = RoutingLimits(maximum_origins=3, maximum_destinations=4, maximum_elements=8)

    batches = plan_matrix_batches(7, limits, RoutingOptions())
    covered: list[tuple[int, int]] = []
    for batch in batches:
        assert batch.origin_count <= limits.maximum_origins
        assert batch.destination_count <= limits.maximum_destinations
        assert batch.element_count <= limits.maximum_elements
        covered.extend(
            (origin, destination)
            for origin in range(batch.origin_start, batch.origin_end)
            for destination in range(batch.destination_start, batch.destination_end)
        )

    assert len(covered) == 49
    assert len(set(covered)) == 49


def test_optimal_traffic_uses_lower_element_limit() -> None:
    limits = RoutingLimits(
        maximum_origins=25,
        maximum_destinations=25,
        maximum_elements=625,
        traffic_aware_optimal_maximum_elements=100,
    )
    options = RoutingOptions(routing_preference=RoutingPreference.TRAFFIC_AWARE_OPTIMAL)

    estimate = estimate_matrix_request(20, limits, options)

    assert estimate.maximum_elements_per_request == 100
    assert estimate.request_count > 1
    assert all(batch.element_count <= 100 for batch in plan_matrix_batches(20, limits, options))
