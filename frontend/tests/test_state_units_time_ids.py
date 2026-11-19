"""V1.1-M2 unit conversions, plant-local time, and ID suggestions."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from frontend.state import ids, units
from frontend.state.timeutil import (
    WallClockStatus,
    format_local,
    local_iso,
    local_to_utc,
    parse_datetime_text,
    split_for_form,
    to_local,
    wall_clock_status,
    wall_clock_text,
)

TORONTO = "America/Toronto"


@pytest.mark.parametrize(("meters", "km"), [(0, 0.0), (216_000, 216.0), (1_250, 1.25)])
def test_km_and_meters_round_trip(meters: int, km: float) -> None:
    assert units.meters_to_km(meters) == km
    assert units.km_to_meters(km) == meters


def test_distance_formatting_and_rounding() -> None:
    assert units.format_km(216_000) == "216.0 km"
    assert units.format_km(None) == "—"
    assert units.km_to_meters(12.3456) == 12_346
    with pytest.raises(ValueError, match="negative"):
        units.km_to_meters(-1)


@pytest.mark.parametrize("minutes", [0, 1, 59, 60, 125, 24 * 60, 36 * 60 + 5])
def test_hmm_round_trips_whole_minutes(minutes: int) -> None:
    seconds = minutes * 60
    assert units.hmm_to_seconds(units.seconds_to_hmm(seconds)) == seconds


def test_hmm_examples_and_rejections() -> None:
    assert units.seconds_to_hmm(7_500) == "2:05"
    assert units.seconds_to_hmm(89) == "0:01"
    assert units.hmm_to_seconds(" 10:30 ") == 37_800
    for bad in ("2:60", "2", "2:5", "-1:00", "abc"):
        with pytest.raises(ValueError, match="h:mm"):
            units.hmm_to_seconds(bad)


def test_wall_clock_text_has_no_offset() -> None:
    assert wall_clock_text(date(2026, 6, 22), time(7, 0, 30, 999)) == "2026-06-22T07:00:30"


def test_plant_local_display() -> None:
    assert format_local("2026-06-22T11:00:00Z", TORONTO) == "2026-06-22 07:00 EDT"
    assert format_local("2026-12-01T12:00:00+00:00", TORONTO) == "2026-12-01 07:00 EST"
    assert format_local("2026-06-22T07:00:00", TORONTO) == "2026-06-22 07:00 EDT"
    assert format_local(None, TORONTO) == "—"


def _instants_around(utc_start: datetime) -> list[datetime]:
    return [utc_start + timedelta(minutes=30 * step) for step in range(-6, 7)]


@pytest.mark.parametrize(
    "transition",
    [
        datetime(2026, 3, 8, 7, 0, tzinfo=UTC),  # clocks go forward at 02:00 EST
        datetime(2026, 11, 1, 6, 0, tzinfo=UTC),  # clocks go back at 02:00 EDT
    ],
    ids=["spring forward", "fall back"],
)
def test_utc_to_local_and_back_round_trips_across_dst(transition: datetime) -> None:
    for instant in _instants_around(transition):
        text = local_iso(instant, TORONTO)
        assert parse_datetime_text(text).astimezone(UTC) == instant
        assert local_to_utc(text, TORONTO) == instant
        wall_clock = to_local(instant, TORONTO).replace(tzinfo=None).isoformat()
        if wall_clock_status(wall_clock, TORONTO) is WallClockStatus.OK:
            assert local_to_utc(wall_clock, TORONTO) == instant


def test_dst_gaps_and_overlaps_are_detected() -> None:
    assert wall_clock_status("2026-03-08T02:30:00", TORONTO) is WallClockStatus.NONEXISTENT
    assert wall_clock_status("2026-11-01T01:30:00", TORONTO) is WallClockStatus.AMBIGUOUS
    assert wall_clock_status("2026-11-01T02:30:00", TORONTO) is WallClockStatus.OK
    assert wall_clock_status("2026-11-01T01:30:00-05:00", TORONTO) is WallClockStatus.OK
    with pytest.raises(ValueError, match="ambiguous"):
        local_to_utc("2026-11-01T01:30:00", TORONTO)
    with pytest.raises(ValueError, match="nonexistent"):
        local_to_utc("2026-03-08T02:30:00", TORONTO)


def test_offset_values_from_json_are_shown_in_plant_time_for_forms() -> None:
    assert split_for_form("2026-06-22T11:00:00+00:00", TORONTO) == (date(2026, 6, 22), time(7, 0))
    assert split_for_form("2026-06-22T07:15:00", TORONTO) == (date(2026, 6, 22), time(7, 15))


def test_slugs_follow_the_backend_id_rules() -> None:
    assert ids.slugify_id("Acme Steel Ltd.") == "ACME-STEEL-LTD"
    assert ids.slugify_id("Café Économie") == "CAFE-ECONOMIE"
    assert ids.slugify_id("!!!", fallback="LOCATION") == "LOCATION"
    assert ids.is_valid_id(ids.slugify_id("x" * 300))
    assert ids.is_valid_id("TRUCK-1:A.b_c")
    assert not ids.is_valid_id("-LEADING")
    assert not ids.is_valid_id("has space")


def test_suggestions_stay_unique() -> None:
    assert ids.suggest_location_id("Acme Steel", ["ACME-STEEL", "acme-steel-2"]) == "ACME-STEEL-3"
    assert ids.suggest_vehicle_id("Truck 1", []) == "TRUCK-1"
    assert ids.suggest_scenario_id("Week 26 inbound") == "WEEK-26-INBOUND"
    assert ids.suggest_shift_id("TRUCK-1", date(2026, 6, 22), []) == "TRUCK-1-20260622"
    assert ids.suggest_task_id(["TASK-0006", "TASK-PICK-001", "TASK-0002"]) == "TASK-0007"
    assert ids.suggest_task_id([]) == "TASK-0001"
    long_base = "A" * 120
    assert len(ids.unique_id(long_base, [long_base])) == 120
