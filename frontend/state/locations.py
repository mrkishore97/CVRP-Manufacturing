"""Address resolution on the canonical scenario: what to send, and what came back.

Pure functions, no Streamlit. Planners type a name and an address; everything else on
a location is derived by the backend's ``/locations/resolve`` and written here. Only
new or changed addresses are sent (plan §8.1). A result is applied only if the
location still has the address that was sent, so a late answer can never attach
coordinates to a different address.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from frontend.state.ids import is_valid_id, suggest_location_id, unique_id
from frontend.state.readiness import USABLE_READINESS, LocationReadiness
from frontend.state.scenario_state import (
    Row,
    Scenario,
    ScenarioEditError,
    clear_derived_location_fields,
    describe_dependants,
    find_row,
    location_dependants,
    normalize_address,
    row_ids,
    rows,
    upsert_location,
)

PENDING_READINESS = frozenset(
    {LocationReadiness.NOT_RESOLVED, LocationReadiness.STALE, LocationReadiness.EXPIRED}
)
"""Locations that need sending: never resolved, address changed, or older than 30 days."""

ADDRESS_HINT = (
    "A street address works best. Company names, postal codes, and Plus Codes also work "
    "for hard-to-find sites."
)

READINESS_LABELS: Mapping[LocationReadiness, str] = {
    LocationReadiness.READY: "Resolved",
    LocationReadiness.SUPPLIED: "Supplied coordinates",
    LocationReadiness.NOT_RESOLVED: "Not resolved yet",
    LocationReadiness.NEEDS_REVIEW: "Needs review",
    LocationReadiness.FAILED: "Not found",
    LocationReadiness.STALE: "Address changed — resolve again",
    LocationReadiness.EXPIRED: "Older than 30 days — resolve again",
}

_RESULT_FIELDS: Mapping[str, str] = {
    "formatted_address": "formatted_address",
    "place_id": "place_id",
    "latitude": "latitude",
    "longitude": "longitude",
    "geocode_source_fingerprint": "geocode_source_fingerprint",
    "geocoded_at": "geocoded_at",
    "location_type": "geocode_location_type",
    "partial_match": "geocode_partial_match",
}


def plant_id(scenario: Mapping[str, Any]) -> str:
    return str(scenario.get("plant_location_id", "PLANT"))


def locations_in_order(scenario: Mapping[str, Any]) -> list[Row]:
    """Locations with the plant pinned first, then in scenario order."""
    plant = plant_id(scenario)
    all_rows = rows(scenario, "locations")
    return [row for row in all_rows if row.get("location_id") == plant] + [
        row for row in all_rows if row.get("location_id") != plant
    ]


def ids_with(
    readiness: Mapping[str, LocationReadiness], wanted: Iterable[LocationReadiness]
) -> list[str]:
    wanted_set = frozenset(wanted)
    return [location_id for location_id, value in readiness.items() if value in wanted_set]


def pending_ids(
    scenario: Mapping[str, Any], readiness: Mapping[str, LocationReadiness]
) -> list[str]:
    """Locations whose address must be sent: plant first, blank addresses skipped."""
    pending = set(ids_with(readiness, PENDING_READINESS))
    return [
        str(location["location_id"])
        for location in locations_in_order(scenario)
        if location.get("location_id") in pending and str(location.get("address", "")).strip()
    ]


def failed_ids(
    scenario: Mapping[str, Any], readiness: Mapping[str, LocationReadiness]
) -> list[str]:
    failed = set(ids_with(readiness, (LocationReadiness.FAILED,)))
    return [
        str(location["location_id"])
        for location in locations_in_order(scenario)
        if location.get("location_id") in failed
    ]


def resolve_rows(scenario: Mapping[str, Any], location_ids: Sequence[str]) -> list[dict[str, Any]]:
    """The ``locations`` rows of a resolve request, in the order given.

    A location the planner already confirmed carries its place ID, so the backend does
    not ask again when Google returns the same place.
    """
    result: list[dict[str, Any]] = []
    for location_id in location_ids:
        location = find_row(scenario, "locations", location_id)
        if location is None:
            raise ScenarioEditError(f"Location {location_id} does not exist.")
        row: dict[str, Any] = {
            "location_id": location_id,
            "address": str(location.get("address", "")).strip(),
        }
        if location.get("geocode_confirmed") and location.get("place_id"):
            row["confirmed_place_id"] = str(location["place_id"])
        result.append(row)
    return result


def plant_coordinates(
    scenario: Mapping[str, Any],
    readiness: Mapping[str, LocationReadiness],
    sent_ids: Sequence[str],
) -> dict[str, float] | None:
    """Known plant coordinates for the far-from-plant check when the plant is not sent."""
    plant = plant_id(scenario)
    if plant in sent_ids or readiness.get(plant) not in USABLE_READINESS:
        return None
    location = find_row(scenario, "locations", plant)
    if location is None:
        return None
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if not isinstance(latitude, int | float) or not isinstance(longitude, int | float):
        return None
    return {"latitude": float(latitude), "longitude": float(longitude)}


def resolve_batches(location_ids: Sequence[str], *, plant: str, size: int) -> list[list[str]]:
    """Requests of at most ``size`` locations, the plant first so its match is known early."""
    if size < 1:
        raise ValueError("size must be at least 1")
    ordered = sorted(location_ids, key=lambda location_id: location_id != plant)
    return [ordered[start : start + size] for start in range(0, len(ordered), size)]


def result_coordinates(
    results: Sequence[Mapping[str, Any]], location_id: str
) -> dict[str, float] | None:
    """The coordinates a resolve result gave ``location_id``, if it has them."""
    for result in results:
        if result.get("location_id") != location_id:
            continue
        latitude, longitude = result.get("latitude"), result.get("longitude")
        if isinstance(latitude, int | float) and isinstance(longitude, int | float):
            return {"latitude": float(latitude), "longitude": float(longitude)}
    return None


SUMMARY_COUNTS = ("resolved", "needs_review", "failed", "provider_calls", "cache_hits")


def merge_summaries(summaries: Sequence[Any]) -> dict[str, int]:
    """One summary for several resolve requests: the counts added up."""
    merged = dict.fromkeys(SUMMARY_COUNTS, 0)
    for summary in summaries:
        if isinstance(summary, Mapping):
            for key in SUMMARY_COUNTS:
                value = summary.get(key)
                if isinstance(value, int):
                    merged[key] += value
    return merged


@dataclass(frozen=True, slots=True)
class AppliedResolutions:
    scenario: Scenario
    applied: tuple[str, ...]
    skipped: tuple[str, ...] = ()
    """Locations whose address changed after the request was sent; left untouched."""


def apply_resolutions(
    scenario: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    sent_addresses: Mapping[str, str],
) -> AppliedResolutions:
    """Write each result into its location, if that location still has the sent address."""
    updated: Scenario = deepcopy(dict(scenario))
    applied: list[str] = []
    skipped: list[str] = []
    for result in results:
        location_id = str(result.get("location_id", ""))
        location = find_row(updated, "locations", location_id)
        sent = sent_addresses.get(location_id)
        if location is None or sent is None:
            skipped.append(location_id)
            continue
        if normalize_address(str(location.get("address", ""))) != normalize_address(sent):
            skipped.append(location_id)
            continue
        updated = _replace_location(updated, location_from_result(location, result))
        applied.append(location_id)
    return AppliedResolutions(updated, tuple(applied), tuple(skipped))


def location_from_result(location: Mapping[str, Any], result: Mapping[str, Any]) -> Row:
    """The location with its derived fields replaced by one resolve result."""
    resolved = clear_derived_location_fields(location)
    status = str(result.get("status", "FAILED"))
    resolved["geocode_status"] = status
    if status in ("RESOLVED", "NEEDS_REVIEW"):
        for source, target in _RESULT_FIELDS.items():
            value = result.get(source)
            if value is not None:
                resolved[target] = value
        resolved["geocode_confirmed"] = bool(result.get("geocode_confirmed"))
    message = str(result.get("message") or "").strip()
    codes = result.get("reason_codes") or ()
    if message and (status != "RESOLVED" or codes):
        resolved["geocode_warning"] = message
    return resolved


def confirm_match(scenario: Mapping[str, Any], location_id: str) -> Scenario:
    """The planner accepts a "Needs review" match: it becomes resolved and confirmed."""
    location = find_row(scenario, "locations", location_id)
    if location is None:
        raise ScenarioEditError(f"Location {location_id} does not exist.")
    if location.get("geocode_status") != "NEEDS_REVIEW" or location.get("latitude") is None:
        raise ScenarioEditError(f"Location {location_id} has no match waiting for review.")
    location["geocode_status"] = "RESOLVED"
    location["geocode_confirmed"] = True
    return _replace_location(scenario, location)


def used_by(scenario: Mapping[str, Any], location_id: str) -> str:
    """``Plant; used by 5 tasks and 3 shifts``, ``Used by 1 task``, or ``Not used``."""
    dependants = location_dependants(scenario, location_id)
    others = [dependant for dependant in dependants if dependant.kind != "plant"]
    usage = describe_dependants(others) if others else ""
    if len(others) != len(dependants):
        return f"Plant; {usage}" if usage else "Plant"
    return usage[0].upper() + usage[1:] if usage else "Not used"


def unused_ids(scenario: Mapping[str, Any]) -> list[str]:
    """Locations no task or shift uses and that are not the plant (they enlarge the matrix)."""
    return [
        location_id
        for location_id in row_ids(scenario, "locations")
        if not location_dependants(scenario, location_id)
    ]


def table_rows(
    scenario: Mapping[str, Any], readiness: Mapping[str, LocationReadiness]
) -> list[dict[str, Any]]:
    """The Locations table: what the planner typed, what Google matched, and status."""
    plant = plant_id(scenario)
    result: list[dict[str, Any]] = []
    for location in locations_in_order(scenario):
        location_id = str(location.get("location_id"))
        state = readiness.get(location_id, LocationReadiness.NOT_RESOLVED)
        name = str(location.get("name", ""))
        result.append(
            {
                "Name": f"🏭 {name}" if location_id == plant else name,
                "Address": location.get("address"),
                "Matched address": location.get("formatted_address") or "—",
                "Status": READINESS_LABELS[state],
                "Used by": used_by(scenario, location_id),
                "ID": location_id,
            }
        )
    return result


def new_location(
    scenario: Mapping[str, Any], *, name: str, address: str, location_id: str | None = None
) -> Row:
    """A planner-typed location: name and address only, with an ID suggested if needed."""
    clean_name = " ".join(name.split())
    clean_address = " ".join(address.split())
    if not clean_name:
        raise ScenarioEditError("Enter a name.")
    if not clean_address:
        raise ScenarioEditError("Enter an address.")
    existing = row_ids(scenario, "locations")
    chosen = (location_id or "").strip() or suggest_location_id(clean_name, existing)
    if not is_valid_id(chosen):
        raise ScenarioEditError(f"{chosen!r} is not a valid ID.")
    if chosen in existing:
        raise ScenarioEditError(f"Location ID {chosen} is already used.")
    return {"location_id": chosen, "name": clean_name, "address": clean_address}


def add_location(
    scenario: Mapping[str, Any], *, name: str, address: str, location_id: str | None = None
) -> Scenario:
    return upsert_location(
        scenario, new_location(scenario, name=name, address=address, location_id=location_id)
    )


def edit_location(
    scenario: Mapping[str, Any], location_id: str, *, name: str, address: str
) -> Scenario:
    """Change a name and address; an address change clears that location's resolution."""
    location = find_row(scenario, "locations", location_id)
    if location is None:
        raise ScenarioEditError(f"Location {location_id} does not exist.")
    clean_name = " ".join(name.split())
    clean_address = " ".join(address.split())
    if not clean_name or not clean_address:
        raise ScenarioEditError("A location needs a name and an address.")
    location["name"] = clean_name
    location["address"] = clean_address
    return upsert_location(scenario, location)


def duplicate_location(scenario: Mapping[str, Any], location_id: str) -> tuple[Scenario, str]:
    """A copy with a new ID and "(copy)" name; same address, so the resolution is kept."""
    location = find_row(scenario, "locations", location_id)
    if location is None:
        raise ScenarioEditError(f"Location {location_id} does not exist.")
    new_id = unique_id(location_id, row_ids(scenario, "locations"))
    location["location_id"] = new_id
    location["name"] = f"{location.get('name', location_id)} (copy)"
    return upsert_location(scenario, location), new_id


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    scenario: Scenario
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()


def merge_imported_locations(
    scenario: Mapping[str, Any], imported: Sequence[Mapping[str, Any]]
) -> MergeOutcome:
    """Apply checked import rows: update a match by ID, or by a unique name; else add.

    Imported rows carry no coordinates, so a new or re-addressed location starts as
    "not resolved yet". Applying is all-or-nothing: an invalid row raises and the
    scenario is unchanged.
    """
    updated: Scenario = deepcopy(dict(scenario))
    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for row in imported:
        name = " ".join(str(row.get("name", "")).split())
        address = " ".join(str(row.get("address", "")).split())
        if not name or not address:
            raise ScenarioEditError("Every imported location needs a name and an address.")
        target = _import_target(updated, row.get("location_id"), name)
        if target is None:
            location = new_location(
                updated,
                name=name,
                address=address,
                location_id=str(row.get("location_id") or "") or None,
            )
            updated = upsert_location(updated, location)
            added.append(str(location["location_id"]))
            continue
        existing = find_row(updated, "locations", target)
        assert existing is not None
        if existing.get("name") == name and normalize_address(
            str(existing.get("address", ""))
        ) == normalize_address(address):
            unchanged.append(target)
            continue
        updated = edit_location(updated, target, name=name, address=address)
        changed.append(target)
    return MergeOutcome(updated, tuple(added), tuple(changed), tuple(unchanged))


def copy_locations(
    scenario: Mapping[str, Any], source_locations: Sequence[Mapping[str, Any]]
) -> MergeOutcome:
    """Copy locations from another scenario, with their resolution and its provenance.

    A location whose address is already in this scenario is skipped. A taken ID gets a
    suffix. Copied coordinates keep their fingerprint and date, so readiness still
    decides whether they can be used (an expired one shows "Older than 30 days").
    """
    updated: Scenario = deepcopy(dict(scenario))
    added: list[str] = []
    skipped: list[str] = []
    for source in source_locations:
        source_id = str(source.get("location_id", "")).strip()
        address = normalize_address(str(source.get("address", "")))
        if not source_id or not address or not str(source.get("name", "")).strip():
            skipped.append(source_id or "(no ID)")
            continue
        if any(
            normalize_address(str(location.get("address", ""))) == address
            for location in rows(updated, "locations")
        ):
            skipped.append(source_id)
            continue
        copied = deepcopy(dict(source))
        copied["location_id"] = unique_id(source_id, row_ids(updated, "locations"))
        updated = upsert_location(updated, copied)
        added.append(str(copied["location_id"]))
    return MergeOutcome(updated, added=tuple(added), skipped=tuple(skipped))


def _import_target(scenario: Mapping[str, Any], location_id: Any, name: str) -> str | None:
    if location_id:
        return str(location_id) if str(location_id) in row_ids(scenario, "locations") else None
    matches = [
        str(location.get("location_id"))
        for location in rows(scenario, "locations")
        if str(location.get("name", "")).casefold() == name.casefold()
    ]
    return matches[0] if len(matches) == 1 else None


def _replace_location(scenario: Mapping[str, Any], location: Mapping[str, Any]) -> Scenario:
    """Replace a location in place, derived fields included (no address-change rule)."""
    updated: Scenario = deepcopy(dict(scenario))
    updated["locations"] = [
        deepcopy(dict(location))
        if existing.get("location_id") == location.get("location_id")
        else existing
        for existing in rows(updated, "locations")
    ]
    return updated
