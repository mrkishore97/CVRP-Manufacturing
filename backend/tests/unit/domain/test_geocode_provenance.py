"""V1.1-M1 address provenance: fingerprints, 30-day expiry, and validation warnings."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.domain import (
    GeocodeLocationType,
    GeocodeStatus,
    Location,
    ValidationCode,
    ValidationSeverity,
    validate_planning_payload,
)
from backend.app.domain.geocoding import (
    GEOCODE_MAX_AGE_SECONDS,
    address_fingerprint,
    fingerprint_matches_address,
    geocode_is_expired,
    normalize_address,
    normalize_region_code,
    straight_line_distance_km,
)
from backend.tests.fixtures.canonical import planning_payload

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
SUPPLIER_ADDRESS = "200 Supplier Avenue, Vaughan, ON"


def test_thirty_day_limit_is_the_google_ceiling() -> None:
    assert GEOCODE_MAX_AGE_SECONDS == 2_592_000


def test_normalize_address_collapses_whitespace_and_case() -> None:
    assert normalize_address("  200  Supplier\tAvenue,  VAUGHAN ") == "200 supplier avenue, vaughan"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("ca", "ca"), (" CA ", "ca"), ("", None), (None, None)],
)
def test_region_codes_normalize(value: str | None, expected: str | None) -> None:
    assert normalize_region_code(value) == expected


@pytest.mark.parametrize("value", ["can", "c", "1a"])
def test_invalid_region_codes_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="two letters"):
        normalize_region_code(value)


def test_fingerprint_is_self_describing_and_stable() -> None:
    fingerprint = address_fingerprint(SUPPLIER_ADDRESS, "ca")
    prefix, region, digest = fingerprint.split(":")

    assert (prefix, region, len(digest)) == ("v1", "ca", 64)
    assert address_fingerprint("200  supplier avenue, VAUGHAN, on", "CA") == fingerprint
    assert address_fingerprint(SUPPLIER_ADDRESS, None).startswith("v1:-:")
    assert address_fingerprint(SUPPLIER_ADDRESS, "us") != fingerprint


def test_fingerprint_golden_values_shared_with_the_frontend() -> None:
    """The frontend pins the same values (frontend/tests/test_state_freshness.py)."""
    assert address_fingerprint(SUPPLIER_ADDRESS, "ca") == (
        "v1:ca:8392875975766cd34689822bd4d7b00da53eb83d4bca2af3e09a66d9ba916052"
    )
    assert address_fingerprint("100 Fixture Plant Road, Toronto, ON", None) == (
        "v1:-:c0693830671573be9e62edab32f173f6a4832db24818c2f21ee517991cb38a52"
    )


def test_fingerprint_matches_only_the_address_that_produced_it() -> None:
    fingerprint = address_fingerprint(SUPPLIER_ADDRESS, "ca")

    assert fingerprint_matches_address(fingerprint, " 200 SUPPLIER Avenue, Vaughan, ON ")
    assert not fingerprint_matches_address(fingerprint, "210 Supplier Avenue, Vaughan, ON")
    assert not fingerprint_matches_address("not-a-fingerprint", SUPPLIER_ADDRESS)
    assert fingerprint_matches_address(address_fingerprint(SUPPLIER_ADDRESS, ""), SUPPLIER_ADDRESS)


def test_geocode_expiry_is_at_thirty_days() -> None:
    assert not geocode_is_expired(NOW - timedelta(days=29, hours=23), NOW)
    assert geocode_is_expired(NOW - timedelta(days=30), NOW)
    assert geocode_is_expired(NOW - timedelta(days=2), NOW, max_age_seconds=86_400)


def test_straight_line_distance_is_plausible() -> None:
    toronto_to_montreal = straight_line_distance_km(43.6532, -79.3832, 45.5019, -73.5674)

    assert 495 < toronto_to_montreal < 510
    assert straight_line_distance_km(43.7, -79.4, 43.7, -79.4) == 0


def test_location_accepts_address_only_and_derived_fields() -> None:
    address_only = Location(location_id="ACME", name="Acme Steel", address=SUPPLIER_ADDRESS)
    resolved = Location(
        location_id="ACME",
        name="Acme Steel",
        address=SUPPLIER_ADDRESS,
        latitude=43.82,
        longitude=-79.5,
        geocode_status=GeocodeStatus.NEEDS_REVIEW,
        geocode_source_fingerprint=address_fingerprint(SUPPLIER_ADDRESS, "ca"),
        geocoded_at=datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
        geocode_location_type=GeocodeLocationType.RANGE_INTERPOLATED,
        geocode_partial_match=True,
    )

    assert address_only.geocode_status is GeocodeStatus.PENDING
    assert address_only.geocode_confirmed is False
    assert resolved.geocoded_at == datetime(2026, 11, 16, 10, 0, tzinfo=UTC)


def test_needs_review_requires_the_matched_coordinates() -> None:
    with pytest.raises(ValidationError, match="needing review requires"):
        Location(
            location_id="ACME",
            name="Acme Steel",
            address=SUPPLIER_ADDRESS,
            geocode_status=GeocodeStatus.NEEDS_REVIEW,
        )


def test_geocoded_at_must_carry_a_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone offset"):
        Location(
            location_id="ACME",
            name="Acme Steel",
            address=SUPPLIER_ADDRESS,
            geocoded_at=datetime(2026, 11, 16, 10, 0),
        )


def _geocode_issues(payload: dict[str, Any]) -> list[tuple[ValidationCode, str | None]]:
    result = validate_planning_payload(payload, now=NOW)
    return [
        (issue.code, issue.message)
        for issue in result.issues
        if issue.code in {ValidationCode.STALE_GEOCODE, ValidationCode.GEOCODE_EXPIRED}
    ]


def _address_derived(payload: dict[str, Any], *, geocoded_at: datetime) -> dict[str, Any]:
    """Mark every location as resolved from its current address at ``geocoded_at``."""
    derived = deepcopy(payload)
    for location in derived["locations"]:
        location["geocode_status"] = "RESOLVED"
        location["geocode_source_fingerprint"] = address_fingerprint(location["address"], "ca")
        location["geocoded_at"] = geocoded_at.isoformat()
    return derived


def test_version_1_0_payload_gets_no_new_warnings() -> None:
    payload = planning_payload("A")
    result = validate_planning_payload(payload, now=NOW)

    assert result.valid
    assert _geocode_issues(payload) == []


def test_address_only_payload_validates() -> None:
    payload = planning_payload("A")
    for location in payload["locations"]:
        for derived_field in ("latitude", "longitude", "formatted_address", "place_id"):
            location.pop(derived_field, None)
        location.pop("geocode_status", None)
    payload.pop("routing_matrix")

    result = validate_planning_payload(payload, now=NOW)

    assert result.valid, result.issues
    assert result.normalized_request is not None
    assert all(
        location.latitude is None and location.geocode_status is GeocodeStatus.PENDING
        for location in result.normalized_request.locations
    )


def test_fresh_address_derived_coordinates_get_no_warning() -> None:
    payload = _address_derived(planning_payload("A"), geocoded_at=NOW - timedelta(days=3))

    assert validate_planning_payload(payload, now=NOW).valid
    assert _geocode_issues(payload) == []


def test_edited_address_produces_stale_geocode_warning() -> None:
    payload = _address_derived(planning_payload("A"), geocoded_at=NOW - timedelta(days=3))
    edited = payload["locations"][1]
    edited["address"] = edited["address"] + " Unit 7"

    result = validate_planning_payload(payload, now=NOW)
    issues = _geocode_issues(payload)

    assert result.valid
    assert [code for code, _ in issues] == [ValidationCode.STALE_GEOCODE]
    assert edited["location_id"] in str(issues[0][1])
    stale = next(issue for issue in result.issues if issue.code is ValidationCode.STALE_GEOCODE)
    assert stale.severity is ValidationSeverity.WARNING
    assert stale.row_number == 3


def test_coordinates_older_than_thirty_days_produce_expired_warning() -> None:
    payload = _address_derived(planning_payload("A"), geocoded_at=NOW - timedelta(days=31))
    location_count = len(payload["locations"])

    issues = _geocode_issues(payload)

    assert [code for code, _ in issues] == [ValidationCode.GEOCODE_EXPIRED] * location_count
    assert "30 days" in str(issues[0][1])


def test_shorter_configured_limit_is_honoured() -> None:
    payload = _address_derived(planning_payload("A"), geocoded_at=NOW - timedelta(days=3))

    result = validate_planning_payload(payload, now=NOW, geocode_max_age_seconds=2 * 86_400)

    assert {issue.code for issue in result.issues} >= {ValidationCode.GEOCODE_EXPIRED}


def test_fingerprint_without_geocoded_at_is_treated_as_expired() -> None:
    payload = _address_derived(planning_payload("A"), geocoded_at=NOW)
    del payload["locations"][0]["geocoded_at"]

    issues = _geocode_issues(payload)

    assert [code for code, _ in issues] == [ValidationCode.GEOCODE_EXPIRED]
    assert "cannot be checked" in str(issues[0][1])
