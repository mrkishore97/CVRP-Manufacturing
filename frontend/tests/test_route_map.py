"""Route map data shaping tests."""

from frontend.route_map import build_route_map_data


def test_map_data_preserves_backend_stop_order() -> None:
    plan = {
        "routes": [
            {
                "vehicle_id": "TRUCK-1",
                "shift_id": "SHIFT-1",
                "stops": [
                    {"sequence": 10, "kind": "DEPOT_START", "location_id": "A"},
                    {"sequence": 5, "kind": "PICKUP", "location_id": "B"},
                    {"sequence": 20, "kind": "DEPOT_END", "location_id": "C"},
                ],
            }
        ]
    }
    locations = [
        {"location_id": "A", "latitude": 43.70, "longitude": -79.40},
        {"location_id": "B", "latitude": 43.71, "longitude": -79.41},
        {"location_id": "C", "latitude": 43.72, "longitude": -79.42},
    ]

    map_data = build_route_map_data(plan, locations)

    assert [marker.sequence for marker in map_data.markers] == [10, 5, 20]
    assert map_data.polylines[0].points == tuple(
        (marker.display_latitude, marker.display_longitude) for marker in map_data.markers
    )


def test_duplicate_coordinate_markers_are_identifiable() -> None:
    plan = {
        "routes": [
            {
                "vehicle_id": "TRUCK-1",
                "shift_id": "SHIFT-1",
                "stops": [
                    {"sequence": 0, "kind": "DEPOT_START", "location_id": "PLANT"},
                    {"sequence": 1, "kind": "PICKUP", "location_id": "SUPPLIER"},
                ],
            }
        ]
    }
    locations = [
        {"location_id": "PLANT", "latitude": 43.70, "longitude": -79.40},
        {"location_id": "SUPPLIER", "latitude": 43.70, "longitude": -79.40},
    ]

    map_data = build_route_map_data(plan, locations)

    assert len(map_data.markers) == 2
    assert {marker.duplicate_count for marker in map_data.markers} == {2}
    assert map_data.markers[0].display_latitude != map_data.markers[1].display_latitude
    assert "1 of 2" in map_data.markers[0].label
    assert "2 of 2" in map_data.markers[1].label


def test_vehicle_colors_are_distinct_for_multiple_vehicles() -> None:
    plan = {
        "routes": [
            {
                "vehicle_id": "TRUCK-1",
                "shift_id": "SHIFT-1",
                "stops": [{"sequence": 0, "kind": "DEPOT_START", "location_id": "A"}],
            },
            {
                "vehicle_id": "TRUCK-2",
                "shift_id": "SHIFT-2",
                "stops": [{"sequence": 0, "kind": "DEPOT_START", "location_id": "B"}],
            },
        ]
    }
    locations = [
        {"location_id": "A", "latitude": 43.70, "longitude": -79.40},
        {"location_id": "B", "latitude": 43.80, "longitude": -79.50},
    ]

    map_data = build_route_map_data(plan, locations)

    assert map_data.markers[0].color != map_data.markers[1].color
