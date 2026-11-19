"""Per-location readiness and the overall workflow status.

A location is ready for travel times when it has coordinates, its status is resolved,
and either its provenance fingerprint matches its current address (Google-derived and
fresh) or it has no fingerprint at all (coordinates supplied in JSON, trusted as in
Version 1.0). Coordinates older than the 30-day limit are not used.

The provenance fingerprint mirrors the backend's address-resolution fingerprint:
``v1:<region>:<sha256("v1\\n<region>\\n<normalised address>")>``. Both test suites
pin the same golden values so the two cannot drift apart.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from frontend.state.fingerprints import matrix_input_fingerprint, plan_input_fingerprint
from frontend.state.scenario_state import normalize_address, row_ids, rows
from frontend.state.timeutil import parse_datetime_text
from frontend.state.workspace import (
    Workspace,
    has_unsaved_edits,
    validation_payload_fingerprint,
)

GEOCODE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
_FINGERPRINT = re.compile(r"^v1:(?P<region>[a-z]{2}|-):(?P<digest>[0-9a-f]{64})$")


class LocationReadiness(StrEnum):
    READY = "READY"  # resolved from its current address, within 30 days
    SUPPLIED = "SUPPLIED"  # coordinates supplied in JSON, no provenance
    NOT_RESOLVED = "NOT_RESOLVED"  # no coordinates yet
    NEEDS_REVIEW = "NEEDS_REVIEW"  # a doubtful match awaiting the planner
    FAILED = "FAILED"  # the address was not found
    STALE = "STALE"  # coordinates belong to a different address
    EXPIRED = "EXPIRED"  # older than the 30-day limit


USABLE_READINESS = frozenset({LocationReadiness.READY, LocationReadiness.SUPPLIED})
INVALIDATING_READINESS = frozenset({LocationReadiness.STALE, LocationReadiness.EXPIRED})


def geocode_fingerprint(address: str, region_code: str | None) -> str:
    """The provenance fingerprint the backend stamps on a resolved location."""
    region = (region_code or "").strip().lower() or "-"
    digest = hashlib.sha256(f"v1\n{region}\n{normalize_address(address)}".encode()).hexdigest()
    return f"v1:{region}:{digest}"


def geocode_fingerprint_matches(fingerprint: str, address: str) -> bool:
    match = _FINGERPRINT.fullmatch(fingerprint.strip())
    if match is None or not normalize_address(address):
        return False
    region = match.group("region")
    return geocode_fingerprint(address, None if region == "-" else region) == fingerprint.strip()


def location_readiness(
    location: Mapping[str, Any],
    *,
    now: datetime,
    max_age_seconds: int = GEOCODE_MAX_AGE_SECONDS,
) -> LocationReadiness:
    if location.get("geocode_status") == "FAILED":
        return LocationReadiness.FAILED
    if location.get("latitude") is None or location.get("longitude") is None:
        return LocationReadiness.NOT_RESOLVED
    fingerprint = location.get("geocode_source_fingerprint")
    if isinstance(fingerprint, str) and not geocode_fingerprint_matches(
        fingerprint, str(location.get("address", ""))
    ):
        return LocationReadiness.STALE
    geocoded_at = location.get("geocoded_at")
    if geocoded_at is not None:
        if _expired(geocoded_at, now, max_age_seconds):
            return LocationReadiness.EXPIRED
    elif fingerprint is not None:
        return LocationReadiness.EXPIRED
    if location.get("geocode_status") == "NEEDS_REVIEW" and not location.get("geocode_confirmed"):
        return LocationReadiness.NEEDS_REVIEW
    if fingerprint is None and geocoded_at is None:
        return LocationReadiness.SUPPLIED
    return LocationReadiness.READY


def readiness_by_location(
    scenario: Mapping[str, Any], *, now: datetime
) -> dict[str, LocationReadiness]:
    return {
        str(location.get("location_id")): location_readiness(location, now=now)
        for location in rows(scenario, "locations")
    }


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    """What is current, what is stale, and which actions are allowed."""

    validation_current: bool
    validation_valid: bool
    error_count: int
    warning_count: int
    readiness: Mapping[str, LocationReadiness]
    locations_usable: bool
    matrix_current: bool
    plan_current: bool
    stale_plan_hidden: bool
    can_compute_matrix: bool
    can_solve: bool
    unsaved_edits: bool

    @property
    def readiness_counts(self) -> Counter[LocationReadiness]:
        return Counter(self.readiness.values())


def workflow_status(workspace: Workspace, *, now: datetime | None = None) -> WorkflowStatus:
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    scenario = workspace.scenario
    derived = workspace.derived

    validation_current = derived.validation is not None and (
        derived.validation_fingerprint == validation_payload_fingerprint(workspace)
    )
    issues = derived.validation.get("issues", []) if derived.validation else []
    severities = Counter(
        str(issue.get("severity", "")).upper() for issue in issues if isinstance(issue, dict)
    )
    validation_valid = validation_current and bool(
        derived.validation and derived.validation.get("valid")
    )

    readiness = readiness_by_location(scenario, now=current_time)
    locations_usable = bool(readiness) and all(
        value in USABLE_READINESS for value in readiness.values()
    )

    matrix = derived.matrix
    matrix_current = (
        matrix is not None
        and derived.matrix_input_fingerprint == matrix_input_fingerprint(scenario)
        and set(map(str, matrix.get("location_ids", []))) == set(row_ids(scenario, "locations"))
        and not any(value in INVALIDATING_READINESS for value in readiness.values())
    )
    plan_current = (
        derived.plan is not None
        and matrix_current
        and derived.plan_input_fingerprint == plan_input_fingerprint(scenario, matrix)
    )
    return WorkflowStatus(
        validation_current=validation_current,
        validation_valid=validation_valid,
        error_count=severities.get("ERROR", 0) if validation_current else 0,
        warning_count=severities.get("WARNING", 0) if validation_current else 0,
        readiness=readiness,
        locations_usable=locations_usable,
        matrix_current=matrix_current,
        plan_current=plan_current,
        stale_plan_hidden=derived.plan is not None and not plan_current,
        can_compute_matrix=validation_valid and locations_usable,
        can_solve=validation_valid and matrix_current,
        unsaved_edits=has_unsaved_edits(workspace),
    )


def _expired(value: Any, now: datetime, max_age_seconds: int) -> bool:
    try:
        geocoded_at = parse_datetime_text(str(value))
    except ValueError:
        return True
    if geocoded_at.tzinfo is None:
        return True
    return now - geocoded_at.astimezone(UTC) >= timedelta(seconds=max_age_seconds)
