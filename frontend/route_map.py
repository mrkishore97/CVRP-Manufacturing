"""Route map data shaping for the Streamlit frontend."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

JsonPayload = dict[str, Any]

VEHICLE_COLORS = (
    "blue",
    "green",
    "purple",
    "orange",
    "darkred",
    "cadetblue",
    "darkgreen",
    "darkblue",
    "pink",
    "gray",
)
DUPLICATE_OFFSET_DEGREES = 0.00008


@dataclass(frozen=True, slots=True)
class RouteMarker:
    """One ordered marker on a route map."""

    route_index: int
    stop_index: int
    vehicle_id: str
    shift_id: str
    sequence: int | None
    kind: str
    location_id: str
    task_id: str | None
    latitude: float
    longitude: float
    display_latitude: float
    display_longitude: float
    color: str
    label: str
    popup: str
    duplicate_index: int = 0
    duplicate_count: int = 1


@dataclass(frozen=True, slots=True)
class RoutePolyline:
    """One visual route path using backend stop order."""

    vehicle_id: str
    shift_id: str
    color: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class RouteMapData:
    """Marker and polyline payload for map rendering."""

    markers: tuple[RouteMarker, ...]
    polylines: tuple[RoutePolyline, ...]
    center: tuple[float, float] | None


def build_route_map_data(plan_payload: JsonPayload, locations: list[JsonPayload]) -> RouteMapData:
    """Build ordered route-map markers from plan JSON and planner locations."""
    location_lookup = _location_lookup(locations)
    vehicle_colors: dict[str, str] = {}
    raw_markers: list[dict[str, Any]] = []

    for route_index, route in enumerate(_as_dicts(plan_payload.get("routes"))):
        vehicle_id = str(route.get("vehicle_id", "vehicle"))
        shift_id = str(route.get("shift_id", "shift"))
        color = vehicle_colors.setdefault(
            vehicle_id,
            VEHICLE_COLORS[len(vehicle_colors) % len(VEHICLE_COLORS)],
        )
        for stop_index, stop in enumerate(_as_dicts(route.get("stops"))):
            location_id = str(stop.get("location_id", ""))
            coordinates = location_lookup.get(location_id)
            if coordinates is None:
                continue
            latitude, longitude = coordinates
            raw_markers.append(
                {
                    "route_index": route_index,
                    "stop_index": stop_index,
                    "vehicle_id": vehicle_id,
                    "shift_id": shift_id,
                    "sequence": _optional_int(stop.get("sequence")),
                    "kind": str(stop.get("kind", "")),
                    "location_id": location_id,
                    "task_id": (
                        str(stop.get("task_id")) if stop.get("task_id") is not None else None
                    ),
                    "latitude": latitude,
                    "longitude": longitude,
                    "color": color,
                    "arrival_at": stop.get("arrival_at"),
                    "departure_at": stop.get("departure_at"),
                }
            )

    coordinate_counts = Counter(
        (_coordinate_key(marker["latitude"]), _coordinate_key(marker["longitude"]))
        for marker in raw_markers
    )
    seen_coordinates: Counter[tuple[float, float]] = Counter()
    markers: list[RouteMarker] = []
    for marker in raw_markers:
        key = (_coordinate_key(marker["latitude"]), _coordinate_key(marker["longitude"]))
        duplicate_count = coordinate_counts[key]
        duplicate_index = seen_coordinates[key]
        seen_coordinates[key] += 1
        display_latitude = float(marker["latitude"])
        display_longitude = float(marker["longitude"])
        if duplicate_count > 1:
            offset = (duplicate_index - ((duplicate_count - 1) / 2)) * DUPLICATE_OFFSET_DEGREES
            display_latitude += offset
            display_longitude += offset
        sequence = marker["sequence"]
        label = _marker_label(
            vehicle_id=marker["vehicle_id"],
            sequence=sequence,
            location_id=marker["location_id"],
            duplicate_index=duplicate_index,
            duplicate_count=duplicate_count,
        )
        markers.append(
            RouteMarker(
                route_index=int(marker["route_index"]),
                stop_index=int(marker["stop_index"]),
                vehicle_id=str(marker["vehicle_id"]),
                shift_id=str(marker["shift_id"]),
                sequence=sequence,
                kind=str(marker["kind"]),
                location_id=str(marker["location_id"]),
                task_id=marker["task_id"],
                latitude=float(marker["latitude"]),
                longitude=float(marker["longitude"]),
                display_latitude=display_latitude,
                display_longitude=display_longitude,
                color=str(marker["color"]),
                label=label,
                popup=_marker_popup(marker, duplicate_index, duplicate_count),
                duplicate_index=duplicate_index,
                duplicate_count=duplicate_count,
            )
        )

    points_by_route: dict[tuple[int, str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for route_marker in markers:
        points_by_route[
            (
                route_marker.route_index,
                route_marker.vehicle_id,
                route_marker.shift_id,
                route_marker.color,
            )
        ].append((route_marker.display_latitude, route_marker.display_longitude))
    polylines = tuple(
        RoutePolyline(
            vehicle_id=vehicle_id,
            shift_id=shift_id,
            color=color,
            points=tuple(points),
        )
        for (_route_index, vehicle_id, shift_id, color), points in points_by_route.items()
        if len(points) >= 2
    )

    if not markers:
        return RouteMapData(markers=(), polylines=(), center=None)
    center = (
        sum(marker.display_latitude for marker in markers) / len(markers),
        sum(marker.display_longitude for marker in markers) / len(markers),
    )
    return RouteMapData(markers=tuple(markers), polylines=polylines, center=center)


def _location_lookup(locations: list[JsonPayload]) -> dict[str, tuple[float, float]]:
    lookup: dict[str, tuple[float, float]] = {}
    for location in locations:
        location_id = str(location.get("location_id", ""))
        latitude = _optional_float(location.get("latitude"))
        longitude = _optional_float(location.get("longitude"))
        if location_id and latitude is not None and longitude is not None:
            lookup[location_id] = (latitude, longitude)
    return lookup


def _as_dicts(value: Any) -> list[JsonPayload]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coordinate_key(value: float) -> float:
    return round(float(value), 7)


def _marker_label(
    *,
    vehicle_id: str,
    sequence: int | None,
    location_id: str,
    duplicate_index: int,
    duplicate_count: int,
) -> str:
    duplicate_suffix = (
        f" ({duplicate_index + 1} of {duplicate_count} at this coordinate)"
        if duplicate_count > 1
        else ""
    )
    sequence_label = "?" if sequence is None else str(sequence)
    return f"{vehicle_id} stop {sequence_label}: {location_id}{duplicate_suffix}"


def _marker_popup(
    marker: dict[str, Any],
    duplicate_index: int,
    duplicate_count: int,
) -> str:
    duplicate_text = (
        f"<br>Duplicate coordinate marker: {duplicate_index + 1} of {duplicate_count}"
        if duplicate_count > 1
        else ""
    )
    return (
        f"<b>{marker['vehicle_id']} / {marker['shift_id']}</b>"
        f"<br>Stop sequence: {marker['sequence']}"
        f"<br>Kind: {marker['kind']}"
        f"<br>Location: {marker['location_id']}"
        f"<br>Task: {marker['task_id'] or ''}"
        f"<br>Arrival: {marker['arrival_at'] or ''}"
        f"<br>Departure: {marker['departure_at'] or ''}"
        f"{duplicate_text}"
    )
