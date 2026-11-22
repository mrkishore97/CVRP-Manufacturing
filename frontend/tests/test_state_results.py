"""Results in planner language (V1.1-M6): names, local times, units, reasons, links."""

from __future__ import annotations

from datetime import date
from itertools import pairwise
from urllib.parse import parse_qs, urlsplit

import pytest

from frontend.state.results import (
    MAX_LINK_LENGTH,
    MAX_LINK_WAYPOINTS,
    STATUS_TEXT,
    comparison_rows,
    duration_text,
    google_attribution,
    google_maps_links,
    km_text,
    local_clock,
    local_datetime_text,
    plan_context,
    plan_headline,
    plan_problems,
    plan_settings,
    quantity_text,
    route_title,
    stop_rows,
    truck_rows,
    unscheduled_rows,
)
from frontend.tests.plan_fixtures import ROUTE_1, ROUTE_2, partial_plan, sample_scenario

TORONTO = "America/Toronto"


def test_times_are_plant_local_and_say_when_they_fall_on_a_later_day() -> None:
    assert local_clock("2026-06-22T11:00:00Z", TORONTO, None) == "07:00"
    assert plan_context(sample_scenario()).timezone == TORONTO
    assert local_clock("2026-06-23T04:05:00Z", TORONTO, date(2026, 6, 22)) == "00:05 (+1 day)"
    assert local_clock("2026-06-24T12:00:00Z", TORONTO, date(2026, 6, 22)) == "08:00 (+2 days)"
    assert local_datetime_text("2026-06-22T16:30:00Z", TORONTO) == "Mon 22 Jun 12:30"
    # Winter time is UTC-5 in Toronto.
    assert local_datetime_text("2026-01-12T17:00:00Z", TORONTO) == "Mon 12 Jan 12:00"
    assert local_datetime_text(None, TORONTO) == "—"


def test_units_are_kilometres_hours_and_the_capacity_label() -> None:
    assert km_text(64_500) == "64.5 km"
    assert km_text(1_234_567) == "1,234.6 km"
    assert duration_text(9_600) == "2:40"
    assert duration_text(None) == "—"
    assert quantity_text("7", "pallets") == "7 pallets"
    assert quantity_text(2.5, "kg") == "2.5 kg"
    assert quantity_text(1500, "units") == "1,500 units"


def test_every_stop_shows_a_location_name_and_po_instead_of_ids() -> None:
    scenario = sample_scenario()
    context = plan_context(scenario)
    names = {location["name"] for location in scenario["locations"]}
    location_ids = {location["location_id"] for location in scenario["locations"]}
    task_ids = {task["task_id"] for task in scenario["tasks"]}
    for route in (ROUTE_1, ROUTE_2):
        for row in stop_rows(route, context):
            assert row["Location"] in names
            assert row["Location"] not in location_ids
            assert row["PO"] not in task_ids
    rows = stop_rows(ROUTE_1, context)
    assert [row["Action"] for row in rows] == [
        "Depart",
        "Pick up",
        "Pick up",
        "Deliver",
        "Deliver",
        "Return",
    ]
    assert rows[1] == {
        "#": 1,
        "Action": "Pick up",
        "Location": "Fixture Supplier A",
        "PO": "PO-PICK-001",
        "Quantity": "4 units",
        "Arrive": "07:30",
        "Start": "07:30",
        "Depart": "07:45",
        "Load after": "4",
        "Due by": "",
        "Slack": "",
        "Leg distance": "20.0 km",
        "Leg time": "0:30",
    }
    assert rows[0]["Arrive"] == "" and rows[0]["Depart"] == "07:00"
    assert rows[-1]["Depart"] == "" and rows[-1]["Arrive"] == "09:40"
    assert rows[3]["Due by"] == "Mon 22 Jun 15:00" and rows[3]["Slack"] == "6:30"


def test_a_route_ending_away_from_its_start_says_finish() -> None:
    route = {
        **ROUTE_2,
        "stops": [*ROUTE_2["stops"][:-1], {**ROUTE_2["stops"][-1], "location_id": "HUB_B"}],
    }
    assert stop_rows(route, plan_context(sample_scenario()))[-1]["Action"] == "Finish"


def test_trucks_show_day_times_and_peak_load_against_capacity() -> None:
    scenario = sample_scenario()
    context = plan_context(scenario)
    rows = truck_rows(partial_plan(), context)
    assert rows[0] == {
        "Truck": "Truck 1",
        "Day": "Mon 22 Jun",
        "Start": "07:00",
        "End": "09:40",
        "POs": 2,
        "Distance": "64.5 km",
        "Driving": "1:30",
        "Service": "1:00",
        "Waiting": "0:10",
        "Peak load": "7 of 12 units",
    }
    assert rows[1]["Day"] == "Mon 22 Jun"
    assert rows[1]["End"] == "00:05 (+1 day)"
    assert route_title(ROUTE_1, context) == "Truck 1 · Mon 22 Jun · 07:00-09:40"


def test_headline_says_the_status_in_plain_words_with_the_key_figures() -> None:
    headline = plan_headline(partial_plan(), plan_context(sample_scenario()))
    assert (headline.level, headline.sentence) == STATUS_TEXT["PARTIALLY_FEASIBLE"]
    assert headline.figures == {
        "Truck-shifts used": "2 of 6",
        "POs planned": "3 of 6",
        "Total distance": "94.5 km",
        "Driving time": "2:20",
        "Longest route": "2:40",
        "Tightest slack": "0:45",
    }
    for status, (level, sentence) in STATUS_TEXT.items():
        assert level in ("success", "warning", "error")
        assert status not in sentence  # never the backend's code


def test_unplanned_pos_come_highest_priority_first_with_a_reason_and_an_action() -> None:
    rows = unscheduled_rows(partial_plan(), plan_context(sample_scenario()))
    assert [row["PO"] for row in rows] == ["PO-PAIR-002", "PO-DROP-002", "PO-PICK-002"]
    assert [row["Priority"] for row in rows] == ["3 Important", "2 Normal", "2 Normal"]
    deadline = rows[0]
    assert deadline["Reason"].startswith("It cannot meet its due time even planned on its own.")
    assert "The earliest it can be done is Mon 22 Jun 17:15, 0:45 late." in deadline["Reason"]
    assert deadline["Due"] == "Mon 22 Jun 16:30"
    assert "due time later" in deadline["Suggested action"]
    assert "Add a truck or a shift" in rows[1]["Suggested action"]
    assert rows[2]["Reason"] == "It was not planned."  # no diagnostic: still listed
    assert rows[2]["Due"] == "Mon 22 Jun 14:30"  # from the task itself


def test_problems_with_the_whole_plan_are_listed_apart_from_pos() -> None:
    plan = partial_plan(
        status="TIMEOUT",
        routes=[],
        diagnostics=[{"task_id": "REQUEST", "po_number": "REQUEST", "code": "SOLVER_TIMEOUT"}],
        unscheduled_task_ids=[],
    )
    context = plan_context(sample_scenario())
    assert plan_problems(plan, context) == [
        (
            "The search ran out of time.",
            "Raise the time limit on the Optimize page and solve again.",
        )
    ]
    assert unscheduled_rows(plan, context) == []


def test_settings_record_how_the_plan_was_made_and_credit_google() -> None:
    settings = {
        row["Setting"]: row["Value"] for row in plan_settings(partial_plan(), sample_scenario())
    }
    assert settings["Objective"] == "Balanced workload"
    assert settings["Search effort"] == "Thorough"
    assert settings["Time limit"] == "20 s"
    assert settings["Travel-time buffer"] == "20 %"
    assert settings["Balance strength"] == "Light"
    assert settings["Travel times from"] == "Google Maps"
    assert settings["Travel times source"] == "Google Maps"
    assert settings["Scenario"] == "A (Three-truck feasible mixed plan)"
    assert settings["Times are in"] == TORONTO
    fixture = partial_plan(matrix={"source": "deterministic_offline_fixture"})
    assert "Travel times source" not in {
        row["Setting"] for row in plan_settings(fixture, sample_scenario())
    }


def test_comparison_marks_plans_with_the_same_inputs() -> None:
    current = partial_plan()
    history = [
        {
            "plan_id": current["plan_id"],
            "created_at": "2026-06-22T10:00:00Z",
            "status": "PARTIALLY_FEASIBLE",
            "objective_mode": "BALANCE_WORKLOAD",
            "search_effort": "THOROUGH",
            "travel_time_factor": 1.2,
            "truck_shifts_used": 2,
            "truck_shifts_available": 6,
            "total_distance_meters": 94_500,
            "longest_route_seconds": 9_600,
            "longest_working_seconds": 9_000,
            "unscheduled_count": 3,
            "input_fingerprint": current["input_fingerprint"],
        },
        {
            "plan_id": "PLAN-2",
            "created_at": "2026-06-22T09:00:00Z",
            "status": "FEASIBLE",
            "objective_mode": "MINIMIZE_TRUCKS",
            "truck_shifts_used": 1,
            "total_distance_meters": 80_000,
            "unscheduled_count": 0,
            "input_fingerprint": current["input_fingerprint"],
        },
        {"plan_id": "PLAN-3", "created_at": "2026-06-22T08:00:00Z", "input_fingerprint": "v1:b"},
        {"plan_id": "PLAN-OLD", "created_at": "2026-06-21T08:00:00Z"},  # stored by Version 1.0
    ]
    rows = comparison_rows(history, timezone=TORONTO, current=current)
    assert [row["Inputs"] for row in rows] == ["This plan", "Same", "Different", "Unknown"]
    assert rows[0]["Made"] == "Mon 22 Jun 06:00"
    assert rows[0]["Objective"] == "Balanced workload"
    assert rows[0]["Buffer"] == "20 %"
    assert rows[0]["Trucks used"] == "2 of 6"
    assert rows[0]["Longest working time"] == "2:30"
    assert rows[1]["Objective"] == "Fewest trucks"
    assert rows[1]["Buffer"] == "none"
    assert rows[1]["Trucks used"] == "1"
    assert rows[1]["Longest route"] == "—"
    assert comparison_rows(history, timezone=TORONTO, current=None)[0]["Inputs"] == "Unknown"


def _points(url: str) -> list[str]:
    query = parse_qs(urlsplit(url).query)
    waypoints = query.get("waypoints", [""])[0]
    middle = waypoints.split("|") if waypoints else []
    return [query["origin"][0], *middle, query["destination"][0]]


def test_google_maps_link_follows_the_stops_and_merges_repeated_places() -> None:
    scenario = sample_scenario()
    context = plan_context(scenario)
    links = google_maps_links(ROUTE_1, context)
    assert len(links) == 1
    by_id = {location["location_id"]: location for location in scenario["locations"]}

    def point(location_id: str) -> str:
        location = by_id[location_id]
        return f"{location['latitude']:.6f},{location['longitude']:.6f}"

    # PLANT, SUPPLIER_A (twice, merged), HUB_A, PLANT (delivery and end, merged).
    assert _points(links[0]) == [
        point("PLANT"),
        point("SUPPLIER_A"),
        point("HUB_A"),
        point("PLANT"),
    ]
    assert links[0].startswith("https://www.google.com/maps/dir/?api=1&")
    assert "travelmode=driving" in links[0]


def test_long_routes_are_split_into_consecutive_links_within_google_limits() -> None:
    scenario = sample_scenario()
    scenario["locations"] = [
        {
            "location_id": f"L{index}",
            "name": f"Stop {index}",
            "address": f"{index} Main St",
            "latitude": 43.0 + index / 100,
            "longitude": -79.0 - index / 100,
        }
        for index in range(25)
    ]
    route = {
        "vehicle_id": "TRUCK-1",
        "stops": [
            {"sequence": index, "kind": "PICKUP", "location_id": f"L{index}"} for index in range(25)
        ],
    }
    links = google_maps_links(route, plan_context(scenario))
    parts = [_points(url) for url in links]
    assert len(links) == 3
    assert all(len(points) - 2 <= MAX_LINK_WAYPOINTS for points in parts)
    assert all(len(url) <= MAX_LINK_LENGTH for url in links)
    for previous, following in pairwise(parts):
        assert previous[-1] == following[0]  # each part starts where the last ended
    stitched = parts[0] + [point for part in parts[1:] for point in part[1:]]
    assert len(stitched) == 25


def test_long_addresses_shorten_a_link_to_stay_within_2048_characters() -> None:
    scenario = sample_scenario()
    scenario["locations"] = [
        {"location_id": f"L{index}", "name": f"S{index}", "address": f"{index} " + "x" * 300}
        for index in range(12)
    ]
    route = {"stops": [{"kind": "PICKUP", "location_id": f"L{index}"} for index in range(12)]}
    links = google_maps_links(route, plan_context(scenario))
    assert len(links) > 2
    assert all(len(url) <= MAX_LINK_LENGTH for url in links)


def test_a_route_through_an_unknown_place_gets_no_link() -> None:
    scenario = sample_scenario()
    route = {"stops": [{"location_id": "PLANT"}, {"location_id": "GONE"}]}
    assert google_maps_links(route, plan_context(scenario)) == []


@pytest.mark.parametrize(
    ("addresses", "travel_times", "configured", "expected"),
    [
        (True, True, True, "Matched addresses and travel times: Google Maps"),
        (True, False, True, "Matched addresses: Google Maps"),
        (False, True, False, "Travel times: Google Maps"),
        (True, False, False, None),  # the offline test provider, not Google
        (False, False, True, None),
    ],
)
def test_google_is_credited_when_its_content_is_shown(
    addresses: bool, travel_times: bool, configured: bool, expected: str | None
) -> None:
    assert (
        google_attribution(
            addresses=addresses, travel_times=travel_times, google_configured=configured
        )
        == expected
    )
