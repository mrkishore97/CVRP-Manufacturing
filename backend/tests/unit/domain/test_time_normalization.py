"""Timezone, date-only, and daylight-saving boundary tests."""

from datetime import UTC, datetime

import pytest

from backend.app.domain.enums import ValidationCode
from backend.app.domain.time_normalization import (
    DateTimeNormalizationError,
    display_in_timezone,
    normalize_datetime,
)
from backend.tests.fixtures.canonical import load_json


def test_aware_datetime_is_converted_to_utc() -> None:
    normalized = normalize_datetime(
        "2026-06-22T09:00:00-04:00",
        "America/Toronto",
    )

    assert normalized == datetime(2026, 6, 22, 13, tzinfo=UTC)
    assert display_in_timezone(normalized, "America/Toronto").isoformat() == (
        "2026-06-22T09:00:00-04:00"
    )


def test_naive_datetime_is_interpreted_in_plant_timezone() -> None:
    normalized = normalize_datetime("2026-06-22T09:00:00", "America/Toronto")

    assert normalized == datetime(2026, 6, 22, 13, tzinfo=UTC)


def test_date_only_value_requires_explicit_shift_boundary() -> None:
    with pytest.raises(DateTimeNormalizationError) as error:
        normalize_datetime("2026-06-22", "America/Toronto")

    assert error.value.code is ValidationCode.DATE_ONLY_REQUIRES_SHIFT


def test_nonexistent_dst_time_is_rejected() -> None:
    with pytest.raises(DateTimeNormalizationError) as error:
        normalize_datetime("2026-03-08T02:30:00", "America/Toronto")

    assert error.value.code is ValidationCode.NONEXISTENT_LOCAL_TIME


def test_ambiguous_dst_time_is_rejected() -> None:
    with pytest.raises(DateTimeNormalizationError) as error:
        normalize_datetime("2026-11-01T01:30:00", "America/Toronto")

    assert error.value.code is ValidationCode.AMBIGUOUS_LOCAL_TIME


def test_invalid_timezone_has_stable_error_code() -> None:
    with pytest.raises(DateTimeNormalizationError) as error:
        normalize_datetime("2026-06-22T09:00:00", "Not/A_Real_Zone")

    assert error.value.code is ValidationCode.INVALID_TIMEZONE


def test_canonical_scenario_h_datetime_contract() -> None:
    fixture = load_json("scenario_h_timezone_boundaries.json")
    cases = {case["case_id"]: case for case in fixture["cases"]}

    date_only = cases["H-DATE-ONLY"]
    shift_end = datetime.fromisoformat(date_only["input"]["applicable_shift_end"])
    normalized_due = normalize_datetime(
        date_only["input"]["due_at"],
        fixture["timezone"],
        date_boundary=shift_end,
    )
    assert (
        display_in_timezone(normalized_due, fixture["timezone"]).isoformat()
        == (date_only["expected"]["normalized_due_at"])
    )

    aware = cases["H-AWARE"]
    assert (
        normalize_datetime(aware["input"]["ready_at"], fixture["timezone"]).isoformat()
        == (aware["expected"]["ready_at_utc"])
    )

    for case_id in ("H-DST-NONEXISTENT", "H-DST-AMBIGUOUS"):
        case = cases[case_id]
        with pytest.raises(DateTimeNormalizationError) as error:
            normalize_datetime(case["input"]["ready_at"], fixture["timezone"])
        assert error.value.code.value == case["expected"]["error_code"]
