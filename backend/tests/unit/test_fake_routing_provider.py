"""Deterministic fake routing-provider tests."""

import asyncio

import pytest

from backend.app.routing import (
    FakeRoutingProvider,
    RouteMatrix,
    RoutingLocation,
    RoutingOptions,
    RoutingProvider,
    RoutingProviderError,
)


def build_locations() -> tuple[RoutingLocation, RoutingLocation]:
    return (
        RoutingLocation("PLANT", "Fixture Plant", 43.7, -79.4, "place-plant"),
        RoutingLocation("SUPPLIER_A", "Fixture Supplier", 43.8, -79.5, "place-supplier"),
    )


def build_matrix() -> RouteMatrix:
    return RouteMatrix(
        location_ids=("PLANT", "SUPPLIER_A"),
        distance_meters=((0, 28_000), (27_000, 0)),
        duration_seconds=((0, 1_800), (1_700, 0)),
        source="test-fixture",
    )


def test_fake_provider_is_protocol_compatible_and_preserves_order() -> None:
    plant, supplier = build_locations()
    provider = FakeRoutingProvider(
        geocodes={
            "100 Plant Road": plant,
            "200 Supplier Avenue": supplier,
        },
        matrix=build_matrix(),
    )

    geocoded = asyncio.run(provider.geocode(["200 Supplier Avenue", "100 Plant Road"]))
    matrix = asyncio.run(provider.compute_matrix((plant, supplier), RoutingOptions()))

    assert isinstance(provider, RoutingProvider)
    assert geocoded == (supplier, plant)
    assert matrix.duration_seconds[0][1] == 1_800
    assert matrix.duration_seconds[1][0] == 1_700
    assert provider.geocode_call_count == 1
    assert provider.matrix_call_count == 1


def test_fake_provider_reports_unknown_address_without_network() -> None:
    provider = FakeRoutingProvider()

    with pytest.raises(RoutingProviderError, match="No fake geocode") as error:
        asyncio.run(provider.geocode(["Unknown address"]))

    assert error.value.code == "FAKE_GEOCODE_NOT_FOUND"


def test_fake_provider_rejects_matrix_location_order_mismatch() -> None:
    plant, supplier = build_locations()
    provider = FakeRoutingProvider(matrix=build_matrix())

    with pytest.raises(RoutingProviderError, match="location order") as error:
        asyncio.run(provider.compute_matrix((supplier, plant), RoutingOptions()))

    assert error.value.code == "FAKE_MATRIX_LOCATION_MISMATCH"


@pytest.mark.parametrize(
    ("distances", "durations", "message"),
    [
        (((0,),), ((0, 1), (1, 0)), "square matrix"),
        (((1, 2), (2, 0)), ((0, 1), (1, 0)), "diagonal"),
        (((0, -1), (1, 0)), ((0, 1), (1, 0)), "greater than or equal to 0"),
    ],
)
def test_route_matrix_rejects_invalid_shapes_and_values(
    distances: tuple[tuple[int, ...], ...],
    durations: tuple[tuple[int, ...], ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RouteMatrix(
            location_ids=("A", "B"),
            distance_meters=distances,
            duration_seconds=durations,
            source="invalid-test",
        )
