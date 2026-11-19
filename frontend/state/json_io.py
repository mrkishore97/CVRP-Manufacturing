"""JSON import and export of the canonical scenario.

Two export modes (plan §7.6):

- **clean**: planner inputs only. Safe to share; addresses are re-resolved on import.
- **complete**: also the derived geocoding fields and, when given, the active
  travel-time matrix as ``routing_matrix``.

Import parses text into a document, then splits an embedded ``routing_matrix`` away
from the scenario, because the scenario never holds the active matrix.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from frontend.state.scenario_state import (
    DERIVED_LOCATION_FIELDS,
    Scenario,
    clear_derived_location_fields,
    normalize_address,
    rows,
)


class ExportMode(StrEnum):
    CLEAN = "clean"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Result of parsing JSON text: a document, or an error a planner can act on."""

    document: dict[str, Any] | None
    error: str | None = None


def parse_document(text: str) -> ParsedDocument:
    """Parse text into a JSON object; syntax errors report line and column."""
    if not text.strip():
        return ParsedDocument(None, "The JSON text is empty.")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParsedDocument(None, f"JSON line {exc.lineno}, column {exc.colno}: {exc.msg}")
    if not isinstance(value, dict):
        return ParsedDocument(None, "The scenario must be a JSON object ({ … }).")
    return ParsedDocument(value)


def split_document(document: Mapping[str, Any]) -> tuple[Scenario, dict[str, Any] | None]:
    """Separate the scenario from an embedded ``routing_matrix``."""
    scenario = {key: deepcopy(value) for key, value in document.items() if key != "routing_matrix"}
    matrix = document.get("routing_matrix")
    return scenario, normalize_matrix(matrix) if isinstance(matrix, dict) else None


def normalize_matrix(matrix: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of a matrix using ``location_ids``; older JSON uses ``location_order``.

    The backend accepts both names, and the canonical samples use the older one.
    """
    normalized = deepcopy(dict(matrix))
    if "location_ids" not in normalized and "location_order" in normalized:
        normalized["location_ids"] = normalized.pop("location_order")
    return normalized


def clean_scenario(scenario: Mapping[str, Any]) -> Scenario:
    """The scenario without derived geocoding fields."""
    cleaned = deepcopy(dict(scenario))
    cleaned.pop("routing_matrix", None)
    if isinstance(cleaned.get("locations"), list):
        cleaned["locations"] = [
            clear_derived_location_fields(location) if isinstance(location, dict) else location
            for location in cleaned["locations"]
        ]
    return cleaned


def document_for_export(
    scenario: Mapping[str, Any],
    *,
    mode: ExportMode,
    matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode is ExportMode.CLEAN:
        return clean_scenario(scenario)
    document = deepcopy(dict(scenario))
    if matrix is not None:
        document["routing_matrix"] = deepcopy(dict(matrix))
    return document


def scenario_to_json(
    scenario: Mapping[str, Any],
    *,
    mode: ExportMode,
    matrix: Mapping[str, Any] | None = None,
) -> str:
    return json.dumps(
        document_for_export(scenario, mode=mode, matrix=matrix), indent=2, ensure_ascii=False
    )


def has_derived_fields(location: Mapping[str, Any]) -> bool:
    return any(field in location for field in DERIVED_LOCATION_FIELDS)


def carry_over_derived(
    new_scenario: Mapping[str, Any], current_scenario: Mapping[str, Any]
) -> Scenario:
    """Keep resolved coordinates for locations edited in the clean view.

    The clean view hides derived fields. A location that comes back without any derived
    field, with the same ID and the same address as before, gets its previous derived
    fields back, so applying clean JSON never discards a resolution. A changed address
    gets nothing back. Derived fields typed into the JSON are kept as they are.
    """
    previous = {
        str(location.get("location_id")): location
        for location in rows(current_scenario, "locations")
    }
    updated = deepcopy(dict(new_scenario))
    if not isinstance(updated.get("locations"), list):
        return updated
    merged: list[Any] = []
    for location in updated["locations"]:
        if isinstance(location, dict) and not has_derived_fields(location):
            old = previous.get(str(location.get("location_id")))
            if old is not None and normalize_address(str(old.get("address", ""))) == (
                normalize_address(str(location.get("address", "")))
            ):
                location = {
                    **location,
                    **{field: old[field] for field in DERIVED_LOCATION_FIELDS if field in old},
                }
        merged.append(location)
    updated["locations"] = merged
    return updated
