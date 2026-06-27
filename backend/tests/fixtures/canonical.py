"""Load canonical planning fixtures into the M2 validation payload shape."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DIR = PROJECT_ROOT / "sample_data" / "canonical"


def load_json(file_name: str) -> dict[str, Any]:
    with (CANONICAL_DIR / file_name).open(encoding="utf-8") as handle:
        value: dict[str, Any] = json.load(handle)
    return value


def planning_payload(scenario_letter: str) -> dict[str, Any]:
    """Return one embedded planning payload from canonical fixture references."""
    file_by_letter = {
        "A": "scenario_a_feasible_mixed.json",
        "B": "scenario_b_capacity_impossible.json",
        "C": "scenario_c_deadline_impossible.json",
        "D": "scenario_d_collective_shortage.json",
        "E": "scenario_e_pair_precedence.json",
        "F": "scenario_f_multiday_shifts.json",
    }
    payload = deepcopy(load_json(file_by_letter[scenario_letter.upper()]))
    payload["locations"] = deepcopy(load_json(payload["locations_ref"])["locations"])
    payload["routing_matrix"] = deepcopy(load_json(payload["matrix_ref"]))
    return payload
