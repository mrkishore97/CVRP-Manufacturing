"""Row-aware normalization and validation for planning payloads."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.app.domain.enums import (
    IssueSection,
    TaskType,
    ValidationCode,
    ValidationSeverity,
)
from backend.app.domain.geocoding import (
    GEOCODE_MAX_AGE_SECONDS,
    fingerprint_matches_address,
    geocode_is_expired,
)
from backend.app.domain.import_contract import (
    ImportMappingError,
    map_task_import_row,
    missing_required_task_columns,
)
from backend.app.domain.models import (
    Location,
    PlanningHorizon,
    PlanningRequest,
    RoutingMatrix,
    Task,
    Vehicle,
    VehicleShift,
)
from backend.app.domain.results import ValidationIssue, ValidationResult
from backend.app.domain.time_normalization import (
    DateTimeInput,
    DateTimeNormalizationError,
    get_timezone,
    normalize_datetime,
    parse_datetime_input,
)

KNOWN_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "scenario_id",
        "name",
        "description",
        "timezone",
        "planning_horizon",
        "horizon",
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
)
"""Top-level keys the planning payload may carry; any other key is a likely typo."""

_SECTION_ID_FIELDS: Mapping[IssueSection, str] = {
    IssueSection.LOCATIONS: "location_id",
    IssueSection.VEHICLES: "vehicle_id",
    IssueSection.VEHICLE_SHIFTS: "shift_id",
    IssueSection.TASKS: "task_id",
}


def _issue(
    code: ValidationCode,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    row_number: int | None = None,
    field: str | None = None,
    task_id: str | None = None,
    section: IssueSection | None = None,
    item_id: str | None = None,
) -> ValidationIssue:
    if item_id is None and section is IssueSection.TASKS:
        item_id = task_id
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        row_number=row_number,
        field=field,
        task_id=task_id,
        section=section,
        item_id=item_id,
    )


def _row_id(value: Any, section: IssueSection) -> str | None:
    """The row's ID as written, when it has one, so issues can link to the row."""
    if not isinstance(value, Mapping):
        return None
    raw = value.get(_SECTION_ID_FIELDS[section])
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _validation_issues(
    error: ValidationError,
    *,
    row_number: int | None = None,
    task_id: str | None = None,
    prefix: str = "",
    section: IssueSection | None = None,
    item_id: str | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"])
        field = f"{prefix}.{location}".strip(".") or None
        error_type = str(detail["type"])
        message = str(detail["msg"])
        code = (
            ValidationCode.MISSING_REQUIRED_FIELD
            if error_type == "missing"
            else ValidationCode.INVALID_VALUE
        )
        if "ready_at must not be after due_at" in message:
            code = ValidationCode.READY_AFTER_DUE
        issues.append(
            _issue(
                code,
                message,
                row_number=row_number,
                field=field,
                task_id=task_id,
                section=section,
                item_id=item_id,
            )
        )
    return issues


def _normalize_required_datetime(
    value: Any,
    timezone_name: str,
    *,
    boundary: datetime | None,
    row_number: int,
    field: str,
    task_id: str | None,
    normalized_code: ValidationCode,
) -> tuple[datetime | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    try:
        parsed = parse_datetime_input(value)
        is_date_only = isinstance(parsed, date) and not isinstance(parsed, datetime)
        normalized = normalize_datetime(value, timezone_name, date_boundary=boundary)
    except DateTimeNormalizationError as exc:
        issues.append(
            _issue(
                exc.code,
                str(exc),
                row_number=row_number,
                field=field,
                task_id=task_id,
                section=IssueSection.TASKS,
            )
        )
        return None, issues

    if is_date_only:
        issues.append(
            _issue(
                normalized_code,
                f"{field} was normalized to the applicable truck-shift boundary.",
                severity=ValidationSeverity.WARNING,
                row_number=row_number,
                field=field,
                task_id=task_id,
                section=IssueSection.TASKS,
            )
        )
    return normalized, issues


def _shift_boundary(
    target_date: date,
    shifts: Sequence[VehicleShift],
    timezone: ZoneInfo,
    *,
    use_end: bool,
) -> datetime | None:
    candidates = [
        shift.end if use_end else shift.start
        for shift in shifts
        if (shift.end if use_end else shift.start).astimezone(timezone).date() == target_date
    ]
    if not candidates:
        return None
    return max(candidates) if use_end else min(candidates)


def _date_boundary_for_value(
    value: Any,
    shifts: Sequence[VehicleShift],
    timezone: ZoneInfo,
    *,
    use_end: bool,
) -> datetime | None:
    try:
        parsed = parse_datetime_input(value)
    except DateTimeNormalizationError:
        return None
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        return _shift_boundary(parsed, shifts, timezone, use_end=use_end)
    return None


def _parse_collection[ModelT: (Location, Vehicle)](
    values: Any,
    model_type: type[ModelT],
    label: str,
    section: IssueSection,
) -> tuple[list[tuple[int, ModelT]], list[ValidationIssue]]:
    """Parse list rows, returning each valid model with its row number."""
    parsed: list[tuple[int, ModelT]] = []
    issues: list[ValidationIssue] = []
    if not isinstance(values, list):
        return parsed, [
            _issue(ValidationCode.INVALID_VALUE, f"{label} must be a list.", section=section)
        ]
    for index, value in enumerate(values, start=2):
        try:
            parsed.append((index, model_type.model_validate(value)))
        except ValidationError as exc:
            issues.extend(
                _validation_issues(
                    exc,
                    row_number=index,
                    prefix=label,
                    section=section,
                    item_id=_row_id(value, section),
                )
            )
    return parsed, issues


def _geocode_freshness_issues(
    location_rows: Sequence[tuple[int, Location]],
    *,
    now: datetime,
    max_age_seconds: int,
) -> list[ValidationIssue]:
    """Warn about coordinates that no longer belong to their address or are too old.

    Coordinates without a fingerprint were supplied directly (Version 1.0 JSON) and are
    trusted as before; only address-derived coordinates carry provenance to check.
    """
    issues: list[ValidationIssue] = []
    max_age_days = max_age_seconds / 86_400
    for row_number, location in location_rows:
        if location.latitude is None:
            continue
        fingerprint = location.geocode_source_fingerprint
        if fingerprint is not None and not fingerprint_matches_address(
            fingerprint, location.address
        ):
            issues.append(
                _issue(
                    ValidationCode.STALE_GEOCODE,
                    f"Location {location.location_id} has coordinates that were found for a "
                    "different address. Resolve its address again before calculating "
                    "travel times.",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="locations.geocode_source_fingerprint",
                    section=IssueSection.LOCATIONS,
                    item_id=location.location_id,
                )
            )
            continue
        if location.geocoded_at is not None:
            if geocode_is_expired(location.geocoded_at, now, max_age_seconds):
                issues.append(
                    _issue(
                        ValidationCode.GEOCODE_EXPIRED,
                        f"Location {location.location_id} was resolved more than "
                        f"{max_age_days:g} days ago. Resolve its address again before "
                        "calculating travel times.",
                        severity=ValidationSeverity.WARNING,
                        row_number=row_number,
                        field="locations.geocoded_at",
                        section=IssueSection.LOCATIONS,
                        item_id=location.location_id,
                    )
                )
        elif fingerprint is not None:
            issues.append(
                _issue(
                    ValidationCode.GEOCODE_EXPIRED,
                    f"Location {location.location_id} has resolved coordinates without a "
                    "geocoded_at time, so their age cannot be checked. Resolve its address "
                    "again before calculating travel times.",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="locations.geocoded_at",
                    section=IssueSection.LOCATIONS,
                    item_id=location.location_id,
                )
            )
    return issues


def _parse_horizon(
    raw_horizon: Any,
    timezone_name: str,
) -> tuple[PlanningHorizon | None, list[ValidationIssue]]:
    if not isinstance(raw_horizon, Mapping):
        return None, [
            _issue(
                ValidationCode.INVALID_VALUE,
                "planning_horizon must be an object.",
                section=IssueSection.SCENARIO,
            )
        ]
    try:
        start = normalize_datetime(cast(DateTimeInput, raw_horizon.get("start")), timezone_name)
        end = normalize_datetime(cast(DateTimeInput, raw_horizon.get("end")), timezone_name)
        return PlanningHorizon(start=start, end=end, timezone=timezone_name), []
    except DateTimeNormalizationError as exc:
        return None, [
            _issue(exc.code, str(exc), field="planning_horizon", section=IssueSection.SCENARIO)
        ]
    except ValidationError as exc:
        return None, _validation_issues(
            exc, prefix="planning_horizon", section=IssueSection.SCENARIO
        )


def _parse_shifts(
    raw_shifts: Any,
    timezone_name: str,
    plant_location_id: str,
) -> tuple[list[VehicleShift], list[ValidationIssue]]:
    shifts: list[VehicleShift] = []
    issues: list[ValidationIssue] = []
    if not isinstance(raw_shifts, list):
        return shifts, [
            _issue(
                ValidationCode.INVALID_VALUE,
                "vehicle_shifts must be a list.",
                section=IssueSection.VEHICLE_SHIFTS,
            )
        ]
    for row_number, raw_shift in enumerate(raw_shifts, start=2):
        if not isinstance(raw_shift, Mapping):
            issues.append(
                _issue(
                    ValidationCode.INVALID_VALUE,
                    "Vehicle shift row must be an object.",
                    row_number=row_number,
                    section=IssueSection.VEHICLE_SHIFTS,
                )
            )
            continue
        shift_id = _row_id(raw_shift, IssueSection.VEHICLE_SHIFTS)
        values = dict(raw_shift)
        try:
            values["start"] = normalize_datetime(
                cast(DateTimeInput, values.get("start")), timezone_name
            )
            values["end"] = normalize_datetime(
                cast(DateTimeInput, values.get("end")), timezone_name
            )
        except DateTimeNormalizationError as exc:
            issues.append(
                _issue(
                    exc.code,
                    str(exc),
                    row_number=row_number,
                    field="vehicle_shift",
                    section=IssueSection.VEHICLE_SHIFTS,
                    item_id=shift_id,
                )
            )
            continue
        values.setdefault("start_location_id", plant_location_id)
        values.setdefault("end_location_id", plant_location_id)
        try:
            shifts.append(VehicleShift.model_validate(values))
        except ValidationError as exc:
            issues.extend(
                _validation_issues(
                    exc,
                    row_number=row_number,
                    prefix="vehicle_shift",
                    section=IssueSection.VEHICLE_SHIFTS,
                    item_id=shift_id,
                )
            )
    return shifts, issues


def _parse_tasks(
    raw_tasks: Any,
    timezone_name: str,
    timezone: ZoneInfo,
    shifts: Sequence[VehicleShift],
) -> tuple[list[Task], list[ValidationIssue], dict[str, int]]:
    tasks: list[Task] = []
    issues: list[ValidationIssue] = []
    rows_by_task_id: dict[str, int] = {}
    seen_po_rows: dict[str, int] = {}
    if not isinstance(raw_tasks, list):
        return (
            tasks,
            [
                _issue(
                    ValidationCode.INVALID_VALUE,
                    "tasks must be a list.",
                    section=IssueSection.TASKS,
                )
            ],
            rows_by_task_id,
        )

    for row_number, raw_task in enumerate(raw_tasks, start=2):
        if not isinstance(raw_task, Mapping):
            issues.append(
                _issue(
                    ValidationCode.INVALID_VALUE,
                    "Task row must be an object.",
                    row_number=row_number,
                    section=IssueSection.TASKS,
                )
            )
            continue
        try:
            mapped = map_task_import_row(raw_task)
        except ImportMappingError as exc:
            issues.append(
                _issue(
                    exc.code,
                    str(exc),
                    row_number=row_number,
                    field=exc.field,
                    section=IssueSection.TASKS,
                    item_id=_row_id(raw_task, IssueSection.TASKS),
                )
            )
            continue

        values = mapped.values
        task_id_value = values.get("task_id")
        task_id = str(task_id_value).strip() if task_id_value is not None else None
        for unknown_column in mapped.unknown_columns:
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_COLUMN,
                    f"Unknown task column was ignored: {unknown_column}",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field=unknown_column,
                    task_id=task_id,
                    section=IssueSection.TASKS,
                )
            )

        missing_fields = missing_required_task_columns(values)
        for missing_field in missing_fields:
            issues.append(
                _issue(
                    ValidationCode.MISSING_REQUIRED_FIELD,
                    f"Required task field is missing: {missing_field}",
                    row_number=row_number,
                    field=missing_field,
                    task_id=task_id,
                    section=IssueSection.TASKS,
                )
            )
        if missing_fields:
            continue

        if task_id is not None and task_id in rows_by_task_id:
            issues.append(
                _issue(
                    ValidationCode.DUPLICATE_TASK_ID,
                    f"Task ID duplicates row {rows_by_task_id[task_id]}: {task_id}",
                    row_number=row_number,
                    field="task_id",
                    task_id=task_id,
                    section=IssueSection.TASKS,
                )
            )
            continue

        po_number = str(values.get("po_number", "")).strip()
        if po_number in seen_po_rows:
            issues.append(
                _issue(
                    ValidationCode.DUPLICATE_PO_NUMBER,
                    f"PO number also appears on row {seen_po_rows[po_number]}: {po_number}",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="po_number",
                    task_id=task_id,
                    section=IssueSection.TASKS,
                )
            )
        else:
            seen_po_rows[po_number] = row_number

        ready_boundary = _date_boundary_for_value(
            values["ready_at"], shifts, timezone, use_end=False
        )
        due_boundary = _date_boundary_for_value(values["due_at"], shifts, timezone, use_end=True)
        ready_at, ready_issues = _normalize_required_datetime(
            values["ready_at"],
            timezone_name,
            boundary=ready_boundary,
            row_number=row_number,
            field="ready_at",
            task_id=task_id,
            normalized_code=ValidationCode.DATE_ONLY_READY_NORMALIZED,
        )
        due_at, due_issues = _normalize_required_datetime(
            values["due_at"],
            timezone_name,
            boundary=due_boundary,
            row_number=row_number,
            field="due_at",
            task_id=task_id,
            normalized_code=ValidationCode.DATE_ONLY_DEADLINE_NORMALIZED,
        )
        issues.extend(ready_issues)
        issues.extend(due_issues)
        if ready_at is None or due_at is None:
            continue
        if ready_at > due_at:
            issues.append(
                _issue(
                    ValidationCode.READY_AFTER_DUE,
                    "ready_at must not be after due_at.",
                    row_number=row_number,
                    field="ready_at",
                    task_id=task_id,
                    section=IssueSection.TASKS,
                )
            )
            continue

        values["ready_at"] = ready_at
        values["due_at"] = due_at
        try:
            task = Task.model_validate(values)
        except ValidationError as exc:
            issues.extend(
                _validation_issues(
                    exc,
                    row_number=row_number,
                    task_id=task_id,
                    prefix="task",
                    section=IssueSection.TASKS,
                )
            )
            continue
        tasks.append(task)
        rows_by_task_id[task.task_id] = row_number

    return tasks, issues, rows_by_task_id


def _parse_matrix(raw_matrix: Any) -> tuple[RoutingMatrix | None, list[ValidationIssue]]:
    if raw_matrix is None:
        return None, []
    if not isinstance(raw_matrix, Mapping):
        return None, [
            _issue(
                ValidationCode.INVALID_VALUE,
                "routing_matrix must be an object.",
                section=IssueSection.ROUTING_MATRIX,
            )
        ]
    values = dict(raw_matrix)
    if "location_ids" not in values and "location_order" in values:
        values["location_ids"] = values.pop("location_order")
    values.pop("fixture_version", None)
    try:
        return RoutingMatrix.model_validate(values), []
    except ValidationError as exc:
        return None, _validation_issues(
            exc, prefix="routing_matrix", section=IssueSection.ROUTING_MATRIX
        )


def _business_rule_issues(
    *,
    plant_location_id: str,
    locations: Sequence[Location],
    vehicles: Sequence[Vehicle],
    shifts: Sequence[VehicleShift],
    tasks: Sequence[Task],
    horizon: PlanningHorizon | None,
    rows_by_task_id: Mapping[str, int],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    location_ids = {location.location_id for location in locations}
    vehicle_ids = {vehicle.vehicle_id for vehicle in vehicles}

    for label, values, code, section in (
        (
            "location",
            [location.location_id for location in locations],
            ValidationCode.DUPLICATE_LOCATION_ID,
            IssueSection.LOCATIONS,
        ),
        (
            "vehicle",
            [vehicle.vehicle_id for vehicle in vehicles],
            ValidationCode.DUPLICATE_VEHICLE_ID,
            IssueSection.VEHICLES,
        ),
        (
            "shift",
            [shift.shift_id for shift in shifts],
            ValidationCode.DUPLICATE_SHIFT_ID,
            IssueSection.VEHICLE_SHIFTS,
        ),
    ):
        for duplicate, count in Counter(values).items():
            if count > 1:
                issues.append(
                    _issue(
                        code,
                        f"Duplicate {label} ID: {duplicate}",
                        section=section,
                        item_id=duplicate,
                    )
                )

    if plant_location_id not in location_ids:
        issues.append(
            _issue(
                ValidationCode.UNKNOWN_LOCATION,
                f"Plant location does not exist: {plant_location_id}",
                field="plant_location_id",
                section=IssueSection.SCENARIO,
            )
        )

    for shift in shifts:
        if shift.vehicle_id not in vehicle_ids:
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_VEHICLE,
                    f"Shift {shift.shift_id} references unknown vehicle {shift.vehicle_id}.",
                    field="vehicle_id",
                    section=IssueSection.VEHICLE_SHIFTS,
                    item_id=shift.shift_id,
                )
            )
        if shift.start_location_id not in location_ids or shift.end_location_id not in location_ids:
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_LOCATION,
                    f"Shift {shift.shift_id} references an unknown depot location.",
                    field="vehicle_shift",
                    section=IssueSection.VEHICLE_SHIFTS,
                    item_id=shift.shift_id,
                )
            )
        if horizon and not (horizon.start <= shift.start < shift.end <= horizon.end):
            issues.append(
                _issue(
                    ValidationCode.OUTSIDE_PLANNING_HORIZON,
                    f"Shift {shift.shift_id} is outside the planning period.",
                    field="start/end",
                    section=IssueSection.VEHICLE_SHIFTS,
                    item_id=shift.shift_id,
                )
            )
    issues.extend(_shift_overlap_issues(shifts))

    enabled_capacities = [vehicle.capacity for vehicle in vehicles if vehicle.enabled]
    maximum_capacity = max(enabled_capacities, default=Decimal(0))
    for task in tasks:
        row_number = rows_by_task_id.get(task.task_id)
        if (
            task.origin_location_id not in location_ids
            or task.destination_location_id not in location_ids
        ):
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_LOCATION,
                    f"Task {task.task_id} references an unknown location.",
                    row_number=row_number,
                    field="origin_location_id/destination_location_id",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
        mismatch = (
            (
                task.task_type is TaskType.PICKUP
                and (
                    task.origin_location_id == plant_location_id
                    or task.destination_location_id != plant_location_id
                )
            )
            or (
                task.task_type is TaskType.DROP
                and (
                    task.origin_location_id != plant_location_id
                    or task.destination_location_id == plant_location_id
                )
            )
            or (
                task.task_type is TaskType.PICKUP_DROP
                and (
                    task.origin_location_id == plant_location_id
                    or task.destination_location_id == plant_location_id
                )
            )
        )
        if mismatch:
            issues.append(
                _issue(
                    ValidationCode.TASK_TYPE_LOCATION_MISMATCH,
                    f"Task endpoints do not match task type {task.task_type}.",
                    row_number=row_number,
                    field="task_type",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
        if task.quantity > maximum_capacity:
            issues.append(
                _issue(
                    ValidationCode.CAPACITY_EXCEEDED,
                    f"Task quantity {task.quantity} exceeds maximum enabled capacity "
                    f"{maximum_capacity}.",
                    row_number=row_number,
                    field="quantity",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
        if horizon and not (horizon.start <= task.ready_at <= task.due_at <= horizon.end):
            issues.append(
                _issue(
                    ValidationCode.OUTSIDE_PLANNING_HORIZON,
                    "Task ready/due interval is outside the planning horizon.",
                    row_number=row_number,
                    field="ready_at/due_at",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
    return issues


def _shift_overlap_issues(shifts: Sequence[VehicleShift]) -> list[ValidationIssue]:
    """One truck cannot work two shifts at once."""
    issues: list[ValidationIssue] = []
    by_vehicle: dict[str, list[VehicleShift]] = {}
    for shift in shifts:
        by_vehicle.setdefault(shift.vehicle_id, []).append(shift)
    for vehicle_id, vehicle_shifts in by_vehicle.items():
        ordered = sorted(vehicle_shifts, key=lambda shift: (shift.start, shift.end))
        latest = ordered[0]
        for current in ordered[1:]:
            if latest.end > current.start:
                issues.append(
                    _issue(
                        ValidationCode.SHIFT_OVERLAP,
                        f"Shift {current.shift_id} overlaps shift {latest.shift_id} of "
                        f"truck {vehicle_id}.",
                        field="start/end",
                        section=IssueSection.VEHICLE_SHIFTS,
                        item_id=current.shift_id,
                    )
                )
            if current.end > latest.end:
                latest = current
    return issues


def _raw_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, Mapping)]


def _referenced_location_ids(
    payload: Mapping[str, Any], plant_location_id: str, shifts: Sequence[VehicleShift]
) -> set[str]:
    """Locations used by any task or shift row, including rows that failed to parse."""
    used = {plant_location_id}
    for shift in shifts:
        used.update((shift.start_location_id, shift.end_location_id))
    for raw_shift in _raw_rows(payload, "vehicle_shifts"):
        for field in ("start_location_id", "end_location_id"):
            used.add(str(raw_shift.get(field, plant_location_id)).strip())
    for raw_task in _raw_rows(payload, "tasks"):
        try:
            values = map_task_import_row(raw_task).values
        except ImportMappingError:
            values = dict(raw_task)
        for field in ("origin_location_id", "destination_location_id"):
            if values.get(field) is not None:
                used.add(str(values[field]).strip())
    return used


def _planner_warnings(
    payload: Mapping[str, Any],
    *,
    plant_location_id: str,
    locations: Sequence[Location],
    vehicles: Sequence[Vehicle],
    shifts: Sequence[VehicleShift],
    tasks: Sequence[Task],
    rows_by_task_id: Mapping[str, int],
) -> list[ValidationIssue]:
    """Non-blocking warnings for the Review page (plan §9.6)."""
    issues: list[ValidationIssue] = []
    for key in payload:
        if str(key) not in KNOWN_TOP_LEVEL_KEYS:
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_FIELD,
                    f"The field '{key}' is not used by the planner and was ignored. Check its "
                    "spelling.",
                    severity=ValidationSeverity.WARNING,
                    field=str(key),
                    section=IssueSection.SCENARIO,
                )
            )

    used = _referenced_location_ids(payload, plant_location_id, shifts)
    for location in locations:
        if location.location_id not in used:
            issues.append(
                _issue(
                    ValidationCode.UNUSED_LOCATION,
                    f"Location {location.location_id} is not used by any task or shift. It "
                    "still adds to the travel-time matrix; delete it if it is not needed.",
                    severity=ValidationSeverity.WARNING,
                    field="location_id",
                    section=IssueSection.LOCATIONS,
                    item_id=location.location_id,
                )
            )

    vehicles_with_shifts = {shift.vehicle_id for shift in shifts} | {
        str(raw_shift.get("vehicle_id", "")).strip()
        for raw_shift in _raw_rows(payload, "vehicle_shifts")
    }
    for vehicle in vehicles:
        if vehicle.enabled and vehicle.vehicle_id not in vehicles_with_shifts:
            issues.append(
                _issue(
                    ValidationCode.VEHICLE_WITHOUT_SHIFT,
                    f"Truck {vehicle.vehicle_id} has no shift, so it cannot be used. Add a "
                    "shift or disable the truck.",
                    severity=ValidationSeverity.WARNING,
                    field="vehicle_id",
                    section=IssueSection.VEHICLES,
                    item_id=vehicle.vehicle_id,
                )
            )

    enabled = [vehicle for vehicle in vehicles if vehicle.enabled]
    largest = max((vehicle.capacity for vehicle in enabled), default=Decimal(0))
    shifts_by_vehicle: dict[str, list[VehicleShift]] = {}
    for shift in shifts:
        shifts_by_vehicle.setdefault(shift.vehicle_id, []).append(shift)
    for task in tasks:
        row_number = rows_by_task_id.get(task.task_id)
        tagged = [
            vehicle for vehicle in enabled if task.required_vehicle_tags.issubset(vehicle.tags)
        ]
        able = [vehicle for vehicle in tagged if task.quantity <= vehicle.capacity]
        if not able:
            if task.quantity > largest:
                continue  # already an error: CAPACITY_EXCEEDED
            tags = ", ".join(sorted(task.required_vehicle_tags))
            message = (
                f"No enabled truck has the tags {tags}, so PO {task.po_number} cannot be planned."
                if not tagged
                else f"No enabled truck with the tags {tags} can carry {task.quantity}; the "
                f"largest holds {max(vehicle.capacity for vehicle in tagged)}."
            )
            issues.append(
                _issue(
                    ValidationCode.NO_COMPATIBLE_VEHICLE,
                    message,
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="required_vehicle_tags",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
            continue
        serving = [
            shift
            for vehicle in able
            for shift in shifts_by_vehicle.get(vehicle.vehicle_id, ())
            if shift.start < task.due_at and shift.end > task.ready_at
        ]
        if not serving:
            issues.append(
                _issue(
                    ValidationCode.TASK_WINDOW_OUTSIDE_SHIFTS,
                    f"PO {task.po_number} is ready and due outside every shift of the trucks "
                    "that can carry it, so it cannot be planned. Add a shift or move its times.",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="ready_at/due_at",
                    task_id=task.task_id,
                    section=IssueSection.TASKS,
                )
            )
    return issues


def validate_planning_payload(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    geocode_max_age_seconds: int = GEOCODE_MAX_AGE_SECONDS,
) -> ValidationResult:
    """Normalize a planning payload and return all actionable validation issues.

    ``now`` and ``geocode_max_age_seconds`` only affect the warnings about expired
    address-derived coordinates; they default to the current time and 30 days.
    """
    issues: list[ValidationIssue] = []
    timezone_name = str(payload.get("timezone", "America/Toronto"))
    try:
        timezone = get_timezone(timezone_name)
    except DateTimeNormalizationError as exc:
        return ValidationResult(
            valid=False,
            issues=(_issue(exc.code, str(exc), field="timezone", section=IssueSection.SCENARIO),),
        )

    horizon, horizon_issues = _parse_horizon(
        payload.get("planning_horizon", payload.get("horizon")),
        timezone_name,
    )
    issues.extend(horizon_issues)

    location_rows, location_issues = _parse_collection(
        payload.get("locations", []), Location, "locations", IssueSection.LOCATIONS
    )
    vehicle_rows, vehicle_issues = _parse_collection(
        payload.get("vehicles", []), Vehicle, "vehicles", IssueSection.VEHICLES
    )
    locations = [location for _, location in location_rows]
    vehicles = [vehicle for _, vehicle in vehicle_rows]
    issues.extend(location_issues)
    issues.extend(vehicle_issues)
    issues.extend(
        _geocode_freshness_issues(
            location_rows,
            now=(now or datetime.now(UTC)).astimezone(UTC),
            max_age_seconds=geocode_max_age_seconds,
        )
    )

    plant_location_id = str(payload.get("plant_location_id", "PLANT"))
    shifts, shift_issues = _parse_shifts(
        payload.get("vehicle_shifts", []),
        timezone_name,
        plant_location_id,
    )
    issues.extend(shift_issues)

    enabled_vehicle_ids = {vehicle.vehicle_id for vehicle in vehicles if vehicle.enabled}
    normalization_shifts = [shift for shift in shifts if shift.vehicle_id in enabled_vehicle_ids]
    tasks, task_issues, rows_by_task_id = _parse_tasks(
        payload.get("tasks", []),
        timezone_name,
        timezone,
        normalization_shifts,
    )
    issues.extend(task_issues)

    matrix, matrix_issues = _parse_matrix(payload.get("routing_matrix"))
    issues.extend(matrix_issues)
    issues.extend(
        _business_rule_issues(
            plant_location_id=plant_location_id,
            locations=locations,
            vehicles=vehicles,
            shifts=shifts,
            tasks=tasks,
            horizon=horizon,
            rows_by_task_id=rows_by_task_id,
        )
    )

    if matrix is not None and set(matrix.location_ids) != {
        location.location_id for location in locations
    }:
        issues.append(
            _issue(
                ValidationCode.MATRIX_LOCATION_MISMATCH,
                "Routing matrix locations must exactly match request locations.",
                field="routing_matrix.location_ids",
                section=IssueSection.ROUTING_MATRIX,
            )
        )
    issues.extend(
        _planner_warnings(
            payload,
            plant_location_id=plant_location_id,
            locations=locations,
            vehicles=vehicles,
            shifts=shifts,
            tasks=tasks,
            rows_by_task_id=rows_by_task_id,
        )
    )

    has_errors = any(issue.severity is ValidationSeverity.ERROR for issue in issues)
    if has_errors or horizon is None:
        return ValidationResult(valid=False, issues=tuple(issues))

    try:
        request = PlanningRequest(
            scenario_id=str(payload.get("scenario_id", "SCENARIO")),
            horizon=horizon,
            plant_location_id=plant_location_id,
            locations=tuple(locations),
            vehicles=tuple(vehicles),
            vehicle_shifts=tuple(shifts),
            tasks=tuple(tasks),
            routing_matrix=matrix,
        )
    except ValidationError as exc:
        issues.extend(
            _validation_issues(exc, prefix="planning_request", section=IssueSection.SCENARIO)
        )
        return ValidationResult(valid=False, issues=tuple(issues))
    return ValidationResult(valid=True, normalized_request=request, issues=tuple(issues))


def normalized_payload_for_display(result: ValidationResult) -> dict[str, Any] | None:
    """Return a JSON-compatible payload with local and UTC deadline readability."""
    if result.normalized_request is None:
        return None
    request = result.normalized_request
    timezone = ZoneInfo(request.horizon.timezone)
    payload = request.model_dump(mode="json")
    task_payloads = payload["tasks"]
    for task_payload, task in zip(task_payloads, request.tasks, strict=True):
        task_payload["ready_at_local"] = task.ready_at.astimezone(timezone).isoformat()
        task_payload["due_at_local"] = task.due_at.astimezone(timezone).isoformat()
        task_payload["ready_at_utc"] = task.ready_at.astimezone(UTC).isoformat()
        task_payload["due_at_utc"] = task.due_at.astimezone(UTC).isoformat()
    return payload
