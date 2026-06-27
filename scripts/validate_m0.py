"""Validate M0 documentation, traceability, and canonical acceptance fixtures.

This script deliberately uses only the Python standard library so the M0 gate can
run before the project dependency environment is scaffolded in M1.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "sample_data" / "canonical"
ERRORS: list[str] = []
CHECK_COUNT = 0


def check(condition: bool, message: str) -> None:
    """Record a validation result without stopping at the first failure."""
    global CHECK_COUNT
    CHECK_COUNT += 1
    if not condition:
        ERRORS.append(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=reject_duplicate_keys)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        ERRORS.append(f"{path.relative_to(PROJECT_ROOT)} cannot be loaded: {exc}")
        return {}
    check(isinstance(value, dict), f"{path.name} root must be a JSON object")
    return value


def parse_aware(value: Any, label: str) -> datetime | None:
    if not isinstance(value, str):
        ERRORS.append(f"{label} must be an ISO datetime string")
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        ERRORS.append(f"{label} is not a valid ISO datetime: {value}")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        ERRORS.append(f"{label} must include an explicit UTC offset: {value}")
        return None
    return parsed


def unique_values(items: list[dict[str, Any]], key: str, label: str) -> set[str]:
    values = [item.get(key) for item in items]
    check(
        all(isinstance(value, str) and value for value in values),
        f"{label} must all have non-empty {key}",
    )
    string_values = [value for value in values if isinstance(value, str)]
    check(len(string_values) == len(set(string_values)), f"{label} contain duplicate {key} values")
    return set(string_values)


def validate_shared_data() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    locations_doc = load_json(FIXTURE_DIR / "shared_locations.json")
    locations = locations_doc.get("locations", [])
    check(
        isinstance(locations, list) and len(locations) >= 7,
        "shared locations must contain at least seven locations",
    )
    location_ids = (
        unique_values(locations, "location_id", "shared locations")
        if isinstance(locations, list)
        else set()
    )
    location_map = {
        item["location_id"]: item
        for item in locations
        if isinstance(item, dict) and isinstance(item.get("location_id"), str)
    }
    check("PLANT" in location_ids, "shared locations must include PLANT")
    for location_id, location in location_map.items():
        check(bool(location.get("name")), f"{location_id} must have a name")
        check(bool(location.get("address")), f"{location_id} must have an address")
        check(
            isinstance(location.get("latitude"), int | float),
            f"{location_id} latitude must be numeric",
        )
        check(
            isinstance(location.get("longitude"), int | float),
            f"{location_id} longitude must be numeric",
        )

    matrix = load_json(FIXTURE_DIR / "shared_matrix.json")
    order = matrix.get("location_order", [])
    distances = matrix.get("distance_meters", [])
    durations = matrix.get("duration_seconds", [])
    size = len(order) if isinstance(order, list) else 0
    check(
        set(order) == location_ids, "matrix location order must exactly match shared location IDs"
    )
    check(len(order) == len(set(order)), "matrix location order must not contain duplicates")

    for matrix_name, values in (("distance_meters", distances), ("duration_seconds", durations)):
        check(
            isinstance(values, list) and len(values) == size,
            f"{matrix_name} must have one row per location",
        )
        if not isinstance(values, list):
            continue
        for row_index, row in enumerate(values):
            check(
                isinstance(row, list) and len(row) == size,
                f"{matrix_name} row {row_index} must have {size} columns",
            )
            if not isinstance(row, list):
                continue
            for column_index, value in enumerate(row):
                check(
                    isinstance(value, int) and value >= 0,
                    f"{matrix_name}[{row_index}][{column_index}] must be a nonnegative integer",
                )
            if row_index < len(row):
                check(row[row_index] == 0, f"{matrix_name} diagonal {row_index} must be zero")

    asymmetric = False
    if isinstance(durations, list) and all(
        isinstance(row, list) and len(row) == size for row in durations
    ):
        asymmetric = any(
            durations[i][j] != durations[j][i] for i in range(size) for j in range(i + 1, size)
        )
    check(asymmetric, "duration fixture must preserve asymmetric road travel behavior")
    return location_map, matrix


def validate_planning_scenario(
    scenario: dict[str, Any],
    location_map: dict[str, dict[str, Any]],
    matrix: dict[str, Any],
) -> None:
    scenario_id = scenario.get("scenario_id", "?")
    prefix = f"Scenario {scenario_id}"
    check(scenario.get("category") == "planning", f"{prefix} category must be planning")
    check(scenario.get("timezone") == "America/Toronto", f"{prefix} must use America/Toronto")
    check(scenario.get("plant_location_id") == "PLANT", f"{prefix} plant must be PLANT")
    check(
        scenario.get("locations_ref") == "shared_locations.json",
        f"{prefix} must reference shared locations",
    )
    check(
        scenario.get("matrix_ref") == "shared_matrix.json", f"{prefix} must reference shared matrix"
    )

    horizon = scenario.get("planning_horizon", {})
    horizon_start = parse_aware(horizon.get("start"), f"{prefix} horizon start")
    horizon_end = parse_aware(horizon.get("end"), f"{prefix} horizon end")
    if horizon_start and horizon_end:
        check(horizon_start < horizon_end, f"{prefix} horizon start must precede end")

    vehicles = scenario.get("vehicles", [])
    shifts = scenario.get("vehicle_shifts", [])
    tasks = scenario.get("tasks", [])
    check(isinstance(vehicles, list) and len(vehicles) > 0, f"{prefix} must have vehicles")
    check(isinstance(shifts, list) and len(shifts) > 0, f"{prefix} must have shifts")
    check(isinstance(tasks, list) and len(tasks) > 0, f"{prefix} must have tasks")
    if not all(isinstance(group, list) for group in (vehicles, shifts, tasks)):
        return

    vehicle_ids = unique_values(vehicles, "vehicle_id", f"{prefix} vehicles")
    shift_ids = unique_values(shifts, "shift_id", f"{prefix} shifts")
    task_ids = unique_values(tasks, "task_id", f"{prefix} tasks")
    del shift_ids, task_ids
    capacities: dict[str, float] = {}
    for vehicle in vehicles:
        capacity = vehicle.get("capacity")
        check(
            isinstance(capacity, int | float) and capacity > 0,
            f"{prefix} vehicle capacity must be positive",
        )
        check(isinstance(vehicle.get("enabled"), bool), f"{prefix} vehicle enabled must be boolean")
        if isinstance(vehicle.get("vehicle_id"), str) and isinstance(capacity, int | float):
            capacities[vehicle["vehicle_id"]] = float(capacity)

    shift_intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    earliest_shift_start: datetime | None = None
    for shift in shifts:
        vehicle_id = shift.get("vehicle_id")
        check(vehicle_id in vehicle_ids, f"{prefix} shift references unknown vehicle {vehicle_id}")
        start = parse_aware(shift.get("start"), f"{prefix} shift {shift.get('shift_id')} start")
        end = parse_aware(shift.get("end"), f"{prefix} shift {shift.get('shift_id')} end")
        if start and end:
            check(start < end, f"{prefix} shift {shift.get('shift_id')} start must precede end")
            if horizon_start and horizon_end:
                check(
                    horizon_start <= start <= end <= horizon_end,
                    f"{prefix} shift {shift.get('shift_id')} must fit horizon",
                )
            if isinstance(vehicle_id, str):
                shift_intervals[vehicle_id].append((start, end))
            earliest_shift_start = (
                start if earliest_shift_start is None else min(earliest_shift_start, start)
            )

    for vehicle_id, intervals in shift_intervals.items():
        ordered = sorted(intervals)
        for previous, current in pairwise(ordered):
            check(
                previous[1] <= current[0],
                f"{prefix} shifts overlap for physical vehicle {vehicle_id}",
            )

    task_types: set[str] = set()
    matrix_locations = set(matrix.get("location_order", []))
    for task in tasks:
        task_id = task.get("task_id")
        task_type = task.get("task_type")
        origin = task.get("origin_location_id")
        destination = task.get("destination_location_id")
        quantity = task.get("quantity")
        task_types.add(task_type) if isinstance(task_type, str) else None
        check(
            task_type in {"PICKUP", "DROP", "PICKUP_DROP"},
            f"{prefix} task {task_id} has invalid type",
        )
        check(
            origin in location_map and origin in matrix_locations,
            f"{prefix} task {task_id} has unknown origin",
        )
        check(
            destination in location_map and destination in matrix_locations,
            f"{prefix} task {task_id} has unknown destination",
        )
        check(origin != destination, f"{prefix} task {task_id} origin and destination must differ")
        check(
            isinstance(quantity, int | float) and quantity > 0,
            f"{prefix} task {task_id} quantity must be positive",
        )
        check(
            task.get("due_event") in {"PICKUP_COMPLETE", "DELIVERY_COMPLETE"},
            f"{prefix} task {task_id} due_event is invalid",
        )
        check(
            isinstance(task.get("pickup_service_minutes"), int)
            and task.get("pickup_service_minutes", -1) >= 0,
            f"{prefix} task {task_id} pickup service must be a nonnegative integer",
        )
        check(
            isinstance(task.get("delivery_service_minutes"), int)
            and task.get("delivery_service_minutes", -1) >= 0,
            f"{prefix} task {task_id} delivery service must be a nonnegative integer",
        )
        check(
            isinstance(task.get("priority"), int) and task.get("priority", 0) > 0,
            f"{prefix} task {task_id} priority must be a positive integer",
        )
        if task_type == "PICKUP":
            check(
                origin != "PLANT" and destination == "PLANT",
                f"{prefix} pickup {task_id} must end at PLANT",
            )
        elif task_type == "DROP":
            check(
                origin == "PLANT" and destination != "PLANT",
                f"{prefix} drop {task_id} must start at PLANT",
            )
        elif task_type == "PICKUP_DROP":
            check(
                origin != "PLANT" and destination != "PLANT",
                f"{prefix} pickup-drop {task_id} must use non-plant endpoints",
            )

        ready = parse_aware(task.get("ready_at"), f"{prefix} task {task_id} ready_at")
        due = parse_aware(task.get("due_at"), f"{prefix} task {task_id} due_at")
        if ready and due:
            check(ready <= due, f"{prefix} task {task_id} ready_at must not exceed due_at")
            if horizon_start and horizon_end:
                check(
                    horizon_start <= ready <= due <= horizon_end,
                    f"{prefix} task {task_id} must fit planning horizon",
                )

    expected = scenario.get("expected")
    check(
        isinstance(expected, dict) and bool(expected.get("status")),
        f"{prefix} must define expected status",
    )

    if scenario_id == "A":
        check(len(vehicles) == 3, "Scenario A must contain exactly three physical trucks")
        check(
            task_types == {"PICKUP", "DROP", "PICKUP_DROP"},
            "Scenario A must cover all three task types",
        )
        check(expected.get("status") == "FEASIBLE", "Scenario A must expect FEASIBLE")
        check(
            expected.get("scheduled_task_count") == len(tasks),
            "Scenario A must expect every task scheduled",
        )
    elif scenario_id == "B":
        max_capacity = max(capacities.values()) if capacities else 0
        check(
            any(float(task["quantity"]) > max_capacity for task in tasks),
            "Scenario B task must exceed all capacities",
        )
        check(
            "CAPACITY_EXCEEDED" in expected.get("reason_codes", []),
            "Scenario B must expect CAPACITY_EXCEEDED",
        )
        check(
            expected.get("solver_call_required") is False,
            "Scenario B must not require a solver call",
        )
    elif scenario_id == "C":
        task = tasks[0]
        order = matrix.get("location_order", [])
        durations = matrix.get("duration_seconds", [])
        if (
            earliest_shift_start
            and task.get("origin_location_id") in order
            and task.get("destination_location_id") in order
        ):
            origin_index = order.index(task["origin_location_id"])
            destination_index = order.index(task["destination_location_id"])
            plant_index = order.index("PLANT")
            ready = parse_aware(task.get("ready_at"), "Scenario C ready_at recalculation")
            if ready:
                route_start = max(earliest_shift_start, ready)
                seconds = (
                    durations[plant_index][origin_index]
                    + task["pickup_service_minutes"] * 60
                    + durations[origin_index][destination_index]
                    + task["delivery_service_minutes"] * 60
                )
                calculated = route_start + timedelta(seconds=seconds)
                expected_completion = parse_aware(
                    expected.get("earliest_completion"), "Scenario C expected earliest completion"
                )
                if expected_completion:
                    check(
                        calculated == expected_completion,
                        "Scenario C earliest completion must match matrix "
                        "and service-time lower bound",
                    )
                due = parse_aware(task.get("due_at"), "Scenario C due_at recalculation")
                if due:
                    check(
                        calculated > due, "Scenario C calculated earliest completion must be late"
                    )
                    check(
                        int((calculated - due).total_seconds()) == expected.get("late_by_seconds"),
                        "Scenario C lateness must match expected seconds",
                    )
        check(
            "DEADLINE_IMPOSSIBLE_INDIVIDUALLY" in expected.get("reason_codes", []),
            "Scenario C must expect deadline reason",
        )
    elif scenario_id == "D":
        check(
            len(vehicles) == 3 and len(tasks) == 4,
            "Scenario D must contain three trucks and four tasks",
        )
        check(
            expected.get("status") == "PARTIALLY_FEASIBLE",
            "Scenario D must expect PARTIALLY_FEASIBLE",
        )
        check(
            "INSUFFICIENT_COMBINED_FLEET_TIME" in expected.get("reason_codes", []),
            "Scenario D must expect fleet-time reason",
        )
        order = matrix.get("location_order", [])
        durations = matrix.get("duration_seconds", [])
        if earliest_shift_start:
            for task in tasks:
                destination_index = order.index(task["destination_location_id"])
                plant_index = order.index("PLANT")
                completion = earliest_shift_start + timedelta(
                    seconds=durations[plant_index][destination_index]
                    + task["delivery_service_minutes"] * 60
                )
                due = parse_aware(
                    task.get("due_at"), f"Scenario D {task.get('task_id')} due recalculation"
                )
                if due:
                    check(
                        completion <= due,
                        f"Scenario D {task.get('task_id')} must be individually feasible",
                    )
    elif scenario_id == "E":
        check(
            len(tasks) == 1 and tasks[0].get("task_type") == "PICKUP_DROP",
            "Scenario E must contain one pickup-drop task",
        )
        check(
            expected.get("same_vehicle_required") is True,
            "Scenario E must require the same vehicle",
        )
        order_expectation = expected.get("required_task_stop_order", {}).get(
            tasks[0].get("task_id")
        )
        check(
            order_expectation
            == [tasks[0].get("origin_location_id"), tasks[0].get("destination_location_id")],
            "Scenario E expected stop order must match task endpoints",
        )
    elif scenario_id == "F":
        check(
            len(vehicles) == 1 and len(shifts) == 2,
            "Scenario F must have one vehicle and two shifts",
        )
        check(
            len({shift["vehicle_id"] for shift in shifts}) == 1,
            "Scenario F shifts must share one physical vehicle",
        )
        check(
            len({shift["start"][:10] for shift in shifts}) == 2,
            "Scenario F shifts must occur on separate dates",
        )
        check(
            expected.get("overlapping_physical_vehicle_use") is False,
            "Scenario F must prohibit overlapping use",
        )


def validate_routing_failure_scenario(scenario: dict[str, Any]) -> None:
    check(scenario.get("scenario_id") == "G", "Routing failure fixture must be Scenario G")
    check(
        scenario.get("category") == "routing_failure", "Scenario G category must be routing_failure"
    )
    cases = scenario.get("cases", [])
    check(
        isinstance(cases, list) and len(cases) >= 6,
        "Scenario G must contain at least six failure cases",
    )
    if not isinstance(cases, list):
        return
    case_ids = unique_values(cases, "case_id", "Scenario G cases")
    required = {
        "G-AUTH",
        "G-RATE-LIMIT",
        "G-SERVER-ERROR",
        "G-PARTIAL",
        "G-UNREACHABLE",
        "G-TIMEOUT",
    }
    check(
        required <= case_ids,
        "Scenario G must cover auth, rate limit, server, partial, unreachable, and timeout cases",
    )
    for case in cases:
        expected = case.get("expected", {})
        check(
            isinstance(case.get("provider_behavior"), dict),
            f"Scenario G {case.get('case_id')} needs provider behavior",
        )
        check(
            isinstance(expected.get("retry"), bool),
            f"Scenario G {case.get('case_id')} must define retry behavior",
        )
        if expected.get("retry"):
            check(
                isinstance(expected.get("maximum_attempts"), int)
                and expected["maximum_attempts"] > 0,
                f"Scenario G {case.get('case_id')} must bound retries",
            )
        if not expected.get("eventual_success_allowed"):
            check(
                bool(expected.get("error_code")),
                f"Scenario G {case.get('case_id')} must define an error code",
            )


def validate_datetime_scenario(scenario: dict[str, Any]) -> None:
    check(scenario.get("scenario_id") == "H", "Datetime fixture must be Scenario H")
    check(
        scenario.get("category") == "datetime_validation",
        "Scenario H category must be datetime_validation",
    )
    check(scenario.get("timezone") == "America/Toronto", "Scenario H must use America/Toronto")
    cases = scenario.get("cases", [])
    check(
        isinstance(cases, list) and len(cases) >= 5,
        "Scenario H must contain at least five datetime cases",
    )
    if not isinstance(cases, list):
        return
    case_ids = unique_values(cases, "case_id", "Scenario H cases")
    required = {
        "H-DATE-ONLY",
        "H-AWARE",
        "H-READY-AFTER-DUE",
        "H-DST-NONEXISTENT",
        "H-DST-AMBIGUOUS",
    }
    check(
        required <= case_ids,
        "Scenario H must cover date-only, aware, invalid order, and both DST boundaries",
    )
    for case in cases:
        check(
            isinstance(case.get("input"), dict),
            f"Scenario H {case.get('case_id')} must define input",
        )
        expected = case.get("expected", {})
        check(
            isinstance(expected.get("accepted"), bool),
            f"Scenario H {case.get('case_id')} must define accepted",
        )
        if not expected.get("accepted"):
            check(
                bool(expected.get("error_code")),
                f"Scenario H {case.get('case_id')} rejected case needs error_code",
            )


def validate_traceability_and_docs() -> None:
    reference_path = PROJECT_ROOT / "docs" / "reference_behavior_notes.md"
    traceability_path = PROJECT_ROOT / "docs" / "requirements_traceability.md"
    plan_path = PROJECT_ROOT / "project_plan.md"
    build_log_path = PROJECT_ROOT / "build_log.md"
    baseline_path = PROJECT_ROOT / "docs" / "reference_baseline.json"
    for path in (reference_path, traceability_path, plan_path, build_log_path, baseline_path):
        check(
            path.is_file() and path.stat().st_size > 0,
            f"required document missing or empty: {path.name}",
        )

    if reference_path.is_file():
        reference_text = reference_path.read_text(encoding="utf-8")
        for term in ("Nominatim", "geodesic", "OR-Tools", "depot", "Streamlit", "Google"):
            check(term in reference_text, f"reference behavior notes must discuss {term}")

    if traceability_path.is_file():
        traceability_text = traceability_path.read_text(encoding="utf-8")
        for number in range(1, 21):
            criterion = f"AC-{number:02d}"
            check(criterion in traceability_text, f"traceability is missing {criterion}")

    if baseline_path.is_file():
        baseline = load_json(baseline_path)
        check(baseline.get("algorithm") == "SHA256", "reference baseline algorithm must be SHA256")
        reference_directory = (PROJECT_ROOT / baseline.get("reference_directory", "")).resolve()
        files = baseline.get("files", {})
        check(isinstance(files, dict) and bool(files), "reference baseline must list files")
        if isinstance(files, dict):
            for file_name, expected_hash in files.items():
                reference_file = reference_directory / file_name
                check(reference_file.is_file(), f"reference baseline file is missing: {file_name}")
                if reference_file.is_file():
                    actual_hash = hashlib.sha256(reference_file.read_bytes()).hexdigest().upper()
                    check(
                        actual_hash == expected_hash,
                        f"reference file changed since M0 baseline: {file_name}",
                    )


def main() -> int:
    validate_traceability_and_docs()
    manifest = load_json(FIXTURE_DIR / "manifest.json")
    location_map, matrix = validate_shared_data()

    required_scenarios = manifest.get("required_scenarios", [])
    manifest_entries = manifest.get("scenarios", [])
    check(
        required_scenarios == list("ABCDEFGH"),
        "manifest required_scenarios must be A through H in order",
    )
    check(
        isinstance(manifest_entries, list) and len(manifest_entries) == 8,
        "manifest must register exactly eight scenarios",
    )
    if not isinstance(manifest_entries, list):
        manifest_entries = []
    manifest_ids = unique_values(manifest_entries, "id", "manifest scenarios")
    check(
        manifest_ids == set(required_scenarios),
        "manifest scenario IDs must exactly match required scenarios",
    )

    loaded_count = 0
    for entry in manifest_entries:
        file_name = entry.get("file")
        path = FIXTURE_DIR / file_name if isinstance(file_name, str) else FIXTURE_DIR / "missing"
        check(path.is_file(), f"manifest scenario file is missing: {file_name}")
        if not path.is_file():
            continue
        scenario = load_json(path)
        loaded_count += 1
        check(
            scenario.get("scenario_id") == entry.get("id"),
            f"{file_name} scenario_id must match manifest",
        )
        check(
            scenario.get("category") == entry.get("category"),
            f"{file_name} category must match manifest",
        )
        if entry.get("category") == "planning":
            validate_planning_scenario(scenario, location_map, matrix)
        elif entry.get("category") == "routing_failure":
            validate_routing_failure_scenario(scenario)
        elif entry.get("category") == "datetime_validation":
            validate_datetime_scenario(scenario)
        else:
            ERRORS.append(f"unsupported manifest category: {entry.get('category')}")

    check(loaded_count == 8, "all eight canonical scenario files must load")

    if ERRORS:
        print(f"M0 VALIDATION FAILED: {len(ERRORS)} error(s), {CHECK_COUNT} checks executed")
        for number, error in enumerate(ERRORS, start=1):
            print(f"{number}. {error}")
        return 1

    print(f"M0 VALIDATION PASSED: {CHECK_COUNT} checks executed")
    print("Canonical scenarios loaded: A, B, C, D, E, F, G, H")
    print("Traceability coverage: AC-01 through AC-20")
    print("Reference behavior notes: present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
