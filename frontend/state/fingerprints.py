"""Granular freshness fingerprints over the canonical scenario (plan §12).

Each fingerprint covers only what its artifact depends on, so renaming a scenario or a
location, or editing task notes, never invalidates travel times or a plan (finding F11).

| Fingerprint  | Built from                                                              |
|--------------|-------------------------------------------------------------------------|
| Address      | Location IDs and address text                                           |
| Matrix input | Location IDs, addresses, place IDs, rounded coordinates, routing options |
| Plan input   | Timezone, period, plant, location IDs, trucks, shifts, tasks,           |
|              | optimization options, active matrix identity; no names or notes         |
| Saved        | The whole scenario                                                      |

The matrix input includes the address text as well as the coordinates, so editing an
address makes travel times stale even for a location that has no coordinates yet.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from frontend.state.scenario_state import normalize_address, rows

COORDINATE_DECIMALS = 6


def stable_fingerprint(value: Any) -> str:
    """Deterministic SHA-256 of a JSON-like value."""
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def address_fingerprint(scenario: Mapping[str, Any]) -> str:
    return stable_fingerprint(
        sorted(
            (str(location.get("location_id")), normalize_address(str(location.get("address", ""))))
            for location in rows(scenario, "locations")
        )
    )


def matrix_input_fingerprint(scenario: Mapping[str, Any]) -> str:
    locations = sorted(
        (
            {
                "location_id": str(location.get("location_id")),
                "address": normalize_address(str(location.get("address", ""))),
                "place_id": location.get("place_id"),
                "latitude": _rounded(location.get("latitude")),
                "longitude": _rounded(location.get("longitude")),
            }
            for location in rows(scenario, "locations")
        ),
        key=lambda value: str(value["location_id"]),
    )
    return stable_fingerprint(
        {"locations": locations, "routing_options": scenario.get("routing_options") or {}}
    )


def matrix_identity(matrix: Mapping[str, Any] | None) -> str | None:
    """Identity of one calculated or imported matrix."""
    if matrix is None:
        return None
    return stable_fingerprint(
        {
            key: matrix.get(key)
            for key in (
                "location_ids",
                "distance_meters",
                "duration_seconds",
                "source",
                "travel_mode",
                "routing_preference",
                "departure_time",
                "created_at",
            )
        }
    )


def plan_input_fingerprint(scenario: Mapping[str, Any], matrix: Mapping[str, Any] | None) -> str:
    return stable_fingerprint(
        {
            "timezone": scenario.get("timezone"),
            "planning_horizon": scenario.get("planning_horizon", scenario.get("horizon")),
            "plant_location_id": scenario.get("plant_location_id", "PLANT"),
            "location_ids": sorted(
                str(location.get("location_id")) for location in rows(scenario, "locations")
            ),
            "vehicles": [_without(vehicle, "name") for vehicle in rows(scenario, "vehicles")],
            "vehicle_shifts": rows(scenario, "vehicle_shifts"),
            "tasks": [_without(task, "notes") for task in rows(scenario, "tasks")],
            "optimization_options": scenario.get("optimization_options") or {},
            "matrix": matrix_identity(matrix),
        }
    )


def saved_fingerprint(scenario: Mapping[str, Any]) -> str:
    return stable_fingerprint(scenario)


def _rounded(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(float(value), COORDINATE_DECIMALS)
    return None


def _without(row: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != field}
