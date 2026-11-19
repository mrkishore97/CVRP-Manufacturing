"""Sample scenarios offered in the app.

The Version 1.0 samples come from ``sample_data/canonical`` with their embedded
travel times, so they solve without a Google key. The address-only sample
(``sample_data/v1_1``) has no coordinates and no travel times: its addresses are
resolved and its travel times calculated like a planner's own scenario.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = PROJECT_ROOT / "sample_data" / "canonical"
V1_1_DIR = PROJECT_ROOT / "sample_data" / "v1_1"
SAMPLE_SCENARIOS = {
    "A": "scenario_a_feasible_mixed.json",
    "C": "scenario_c_deadline_impossible.json",
    "D": "scenario_d_collective_shortage.json",
}
ADDRESS_ONLY_SAMPLES = {"V11A": "v11_a_address_only.json"}
SAMPLE_LABELS = {
    "A": "feasible sample",
    "C": "deadline issue sample",
    "D": "fleet shortage sample",
    "V11A": "address-only sample",
}
PLANNING_PAYLOAD_KEYS = {
    "scenario_id",
    "name",
    "timezone",
    "planning_horizon",
    "plant_location_id",
    "locations",
    "vehicles",
    "vehicle_shifts",
    "tasks",
    "routing_matrix",
    "routing_options",
    "optimization_options",
    "planner_defaults",
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object in {path.name}.")
    return value


def load_sample_payload(scenario: str = "A", *, include_matrix: bool = True) -> dict[str, Any]:
    """One sample as a planning document; Version 1.0 samples carry their matrix."""
    key = scenario.upper()
    if key in ADDRESS_ONLY_SAMPLES:
        return _load_json(V1_1_DIR / ADDRESS_ONLY_SAMPLES[key])
    scenario_file = SAMPLE_SCENARIOS.get(key, SAMPLE_SCENARIOS["A"])
    fixture = _load_json(CANONICAL_DIR / scenario_file)
    payload = {
        key: deepcopy(value) for key, value in fixture.items() if key in PLANNING_PAYLOAD_KEYS
    }
    locations_ref = fixture.get("locations_ref")
    if isinstance(locations_ref, str):
        payload["locations"] = deepcopy(_load_json(CANONICAL_DIR / locations_ref)["locations"])
    if include_matrix:
        matrix_ref = fixture.get("matrix_ref")
        if isinstance(matrix_ref, str):
            payload["routing_matrix"] = deepcopy(_load_json(CANONICAL_DIR / matrix_ref))
    else:
        payload.pop("routing_matrix", None)
    return payload
