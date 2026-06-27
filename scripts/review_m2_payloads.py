"""Print and verify business-readable M2 canonical payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.domain import (
    ValidationCode,
    normalized_payload_for_display,
    validate_planning_payload,
)
from backend.app.optimization import expand_tasks

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = PROJECT_ROOT / "sample_data" / "canonical"


def load_json(file_name: str) -> dict[str, Any]:
    with (CANONICAL_DIR / file_name).open(encoding="utf-8") as handle:
        value: dict[str, Any] = json.load(handle)
    return value


def embedded_payload(file_name: str) -> dict[str, Any]:
    payload = load_json(file_name)
    payload["locations"] = load_json(payload["locations_ref"])["locations"]
    payload["routing_matrix"] = load_json(payload["matrix_ref"])
    return payload


def main() -> int:
    feasible = validate_planning_payload(embedded_payload("scenario_a_feasible_mixed.json"))
    if not feasible.valid or feasible.normalized_request is None:
        raise RuntimeError(f"Scenario A did not validate: {feasible.issues}")
    display = normalized_payload_for_display(feasible)
    if display is None:
        raise RuntimeError("Scenario A did not produce a display payload")

    print("M2 NORMALIZED SCENARIO A")
    print("TASK | PO | TYPE | QTY | READY LOCAL | DUE LOCAL | DEADLINE EVENT")
    for task in display["tasks"]:
        print(
            f"{task['task_id']} | {task['po_number']} | {task['task_type']} | "
            f"{task['quantity']} | {task['ready_at_local']} | {task['due_at_local']} | "
            f"{task['due_event']}"
        )

    expanded = expand_tasks(
        feasible.normalized_request.tasks,
        feasible.normalized_request.plant_location_id,
    )
    if not all(task.quantity > 0 for task in feasible.normalized_request.tasks):
        raise RuntimeError("User-facing task quantity must remain positive")
    if not all(pair.pickup.load_delta == -pair.delivery.load_delta for pair in expanded):
        raise RuntimeError("Expanded pickup/delivery loads are not balanced")

    capacity_case = validate_planning_payload(
        embedded_payload("scenario_b_capacity_impossible.json")
    )
    capacity_issues = [
        issue for issue in capacity_case.issues if issue.code is ValidationCode.CAPACITY_EXCEEDED
    ]
    if capacity_case.valid or len(capacity_issues) != 1:
        raise RuntimeError("Scenario B did not produce one capacity diagnostic")
    issue = capacity_issues[0]
    print(
        "SCENARIO B DIAGNOSTIC | "
        f"row={issue.row_number} | task={issue.task_id} | code={issue.code} | {issue.message}"
    )
    print("M2 PAYLOAD REVIEW PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
