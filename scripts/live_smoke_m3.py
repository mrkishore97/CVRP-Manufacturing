"""Restricted live smoke test for Google Geocoding and Routes APIs."""

from __future__ import annotations

import asyncio

from backend.app.config import get_settings
from backend.app.routing import (
    RoutingOptions,
    RoutingProviderError,
    google_provider_from_settings,
)

PUBLIC_TEST_ADDRESSES = (
    "100 Queen Street West, Toronto, Ontario, Canada",
    "6301 Silver Dart Drive, Mississauga, Ontario, Canada",
)


async def run_live_smoke() -> None:
    settings = get_settings()
    provider = google_provider_from_settings(settings)
    geocoded = await provider.geocode(PUBLIC_TEST_ADDRESSES)
    if len(geocoded) != 2 or len({location.location_id for location in geocoded}) != 2:
        raise RuntimeError("Live geocoding did not return two distinct locations")
    matrix = await provider.compute_matrix(geocoded, RoutingOptions())
    if len(matrix.location_ids) != 2:
        raise RuntimeError("Live route matrix was not 2x2")
    if matrix.distance_meters[0][1] <= 0 or matrix.distance_meters[1][0] <= 0:
        raise RuntimeError("Live route matrix off-diagonal distance was not positive")
    if matrix.duration_seconds[0][1] <= 0 or matrix.duration_seconds[1][0] <= 0:
        raise RuntimeError("Live route matrix off-diagonal duration was not positive")
    print("M3 LIVE SMOKE PASSED")
    print("Geocoded public test addresses: 2")
    print("Validated road matrix: 2x2 with positive off-diagonal distance and duration")


def main() -> int:
    try:
        asyncio.run(run_live_smoke())
    except RoutingProviderError as exc:
        print(f"M3 LIVE SMOKE FAILED: {exc.code} - {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
