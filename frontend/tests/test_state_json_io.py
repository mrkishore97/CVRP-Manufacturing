"""V1.1-M2 JSON import and export: clean and complete modes, and applying edits."""

from __future__ import annotations

import json

from frontend.state.json_io import (
    ExportMode,
    carry_over_derived,
    clean_scenario,
    parse_document,
    scenario_to_json,
    split_document,
)
from frontend.state.readiness import workflow_status
from frontend.state.scenario_state import DERIVED_LOCATION_FIELDS, find_row
from frontend.state.workspace import (
    apply_document,
    load_document,
    save_document,
    slice_matrix,
)
from frontend.tests.scenario_fixtures import NOW, current_workspace, small_matrix, small_scenario


def test_complete_round_trip_yields_an_equal_scenario_and_matrix() -> None:
    scenario, matrix = small_scenario(), small_matrix()

    text = scenario_to_json(scenario, mode=ExportMode.COMPLETE, matrix=matrix)
    parsed = parse_document(text)
    assert parsed.document is not None

    assert split_document(parsed.document) == (scenario, matrix)


def test_clean_round_trip_yields_an_equal_clean_scenario() -> None:
    scenario = small_scenario()

    parsed = parse_document(
        scenario_to_json(scenario, mode=ExportMode.CLEAN, matrix=small_matrix())
    )
    assert parsed.document is not None
    imported, matrix = split_document(parsed.document)

    assert imported == clean_scenario(scenario)
    assert matrix is None
    assert not any(
        field in location for location in imported["locations"] for field in DERIVED_LOCATION_FIELDS
    )
    assert imported["locations"][1] == {
        "location_id": "SUPPLIER_A",
        "name": "Supplier A",
        "address": "200 Supplier Avenue, Vaughan, ON",
    }


def test_clean_export_keeps_every_planner_key() -> None:
    clean = clean_scenario(small_scenario())

    for key in ("name", "routing_options", "optimization_options", "planner_defaults", "tasks"):
        assert clean[key] == small_scenario()[key]


def test_complete_round_trip_through_a_workspace() -> None:
    workspace = current_workspace()

    reloaded = load_document(json.loads(json.dumps(save_document(workspace))), source="file")

    assert reloaded.scenario == workspace.scenario
    assert reloaded.derived.matrix == workspace.derived.matrix
    assert workflow_status(reloaded, now=NOW).locations_usable


def test_syntax_errors_report_line_and_column() -> None:
    parsed = parse_document('{\n  "scenario_id": "A",\n  "tasks": [\n}')

    assert parsed.document is None
    assert parsed.error is not None
    assert parsed.error.startswith("JSON line 4, column 1:")


def test_non_objects_and_empty_text_are_rejected() -> None:
    assert parse_document("[1, 2]").error == "The scenario must be a JSON object ({ … })."
    assert parse_document("   ").error == "The JSON text is empty."


def test_older_location_order_matrices_are_normalized() -> None:
    matrix = small_matrix()
    matrix["location_order"] = matrix.pop("location_ids")

    workspace = load_document({**small_scenario(), "routing_matrix": matrix}, source="file")

    assert workspace.derived.matrix is not None
    assert workspace.derived.matrix["location_ids"] == ["PLANT", "SUPPLIER_A", "SPARE"]
    assert workflow_status(workspace, now=NOW).matrix_current


def test_a_matrix_for_other_locations_is_kept_but_not_activated() -> None:
    matrix = slice_matrix(small_matrix(), ["PLANT", "SUPPLIER_A"])

    workspace = load_document({**small_scenario(), "routing_matrix": matrix}, source="file")

    assert workspace.derived.embedded_matrix == matrix
    assert workspace.derived.matrix is None


def test_carry_over_keeps_resolutions_for_unchanged_addresses_only() -> None:
    current = small_scenario()
    edited = clean_scenario(current)
    edited["locations"][2]["address"] = "301 Spare Street, Toronto, ON"
    edited["name"] = "Edited in the clean view"

    merged = carry_over_derived(edited, current)

    assert find_row(merged, "locations", "SUPPLIER_A") == current["locations"][1]
    assert find_row(merged, "locations", "PLANT") == current["locations"][0]
    assert find_row(merged, "locations", "SPARE") == {
        "location_id": "SPARE",
        "name": "Spare dock",
        "address": "301 Spare Street, Toronto, ON",
    }


def test_derived_fields_typed_in_the_json_win_over_carry_over() -> None:
    current = small_scenario()
    edited = clean_scenario(current)
    edited["locations"][0].update({"latitude": 10.0, "longitude": 20.0})

    merged = carry_over_derived(edited, current)

    assert (find_row(merged, "locations", "PLANT") or {})["latitude"] == 10.0


def test_applying_clean_json_keeps_resolutions_and_travel_times() -> None:
    workspace = current_workspace()
    document = clean_scenario(workspace.scenario)
    document["name"] = "Renamed in the clean view"

    applied = apply_document(workspace, document, carry_derived=True)
    status = workflow_status(applied, now=NOW)

    assert applied.scenario["name"] == "Renamed in the clean view"
    assert status.matrix_current
    assert status.locations_usable


def test_applying_complete_json_is_literal() -> None:
    workspace = current_workspace()
    document = clean_scenario(workspace.scenario)

    applied = apply_document(workspace, document, carry_derived=False)

    assert (find_row(applied.scenario, "locations", "PLANT") or {}).get("latitude") is None
    assert not workflow_status(applied, now=NOW).matrix_current


def test_applying_json_with_new_travel_times_activates_them() -> None:
    workspace = current_workspace()
    matrix = small_matrix()
    matrix["distance_meters"][0][1] = 30_000

    applied = apply_document(
        workspace, {**workspace.scenario, "routing_matrix": matrix}, carry_derived=False
    )
    status = workflow_status(applied, now=NOW)

    assert applied.derived.matrix == matrix
    assert applied.derived.matrix_origin == "json"
    assert status.matrix_current
    assert not status.plan_current
