"""Task spreadsheet import contract: the only definition of task columns and aliases.

The frontend reads a CSV/XLSX file and sends its rows keyed by the original headers,
together with the scenario's locations. This module maps the headers through the same
column contract that JSON validation uses (``import_contract.TASK_IMPORT_COLUMNS``),
checks every row, and returns canonical task rows with row-level issues (plan §9.5).
Nothing is applied here: the app applies a valid preview all-or-nothing.

Spreadsheets are written by planners, so they get three conveniences over JSON:

- ``task_id`` may be left empty; the app numbers new tasks.
- Location cells hold a location **ID or exact name** (case and spacing ignored).
- The plant end of a pickup or a drop may be left empty; it is filled with the plant.

Row numbers are spreadsheet rows: the header is row 1, so the first data row is row 2.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.domain.enums import (
    DueEvent,
    TaskType,
    ValidationCode,
    ValidationSeverity,
)
from backend.app.domain.import_contract import (
    TASK_HEADER_MAP,
    TASK_IMPORT_COLUMNS,
    ImportColumnSpec,
    normalize_due_event,
    normalize_header,
    normalize_task_type,
)
from backend.app.domain.location_import import LOCATION_IMPORT_COLUMNS
from backend.app.domain.options import DEFAULT_PRIORITY, PRIORITY_LABELS
from backend.app.domain.results import ValidationIssue
from backend.app.domain.time_normalization import (
    DateTimeNormalizationError,
    normalize_datetime,
    parse_datetime_input,
)

FIRST_DATA_ROW = 2
MAX_ID_LENGTH = 120
MAX_SERVICE_MINUTES = 1_440
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SPREADSHEET_OPTIONAL_COLUMNS: frozenset[str] = frozenset(
    {"task_id", "origin_location_id", "destination_location_id"}
)
"""Required in JSON, optional in a spreadsheet (see the module docstring)."""
REQUIRED_SPREADSHEET_COLUMNS: tuple[str, ...] = tuple(
    column.canonical_name
    for column in TASK_IMPORT_COLUMNS
    if column.required and column.canonical_name not in SPREADSHEET_OPTIONAL_COLUMNS
)
_PRIORITY_BY_LABEL = {label.casefold(): value for value, label in PRIORITY_LABELS.items()}


@dataclass(frozen=True, slots=True)
class LocationRef:
    """A scenario location that a spreadsheet cell may name."""

    location_id: str
    name: str


@dataclass(frozen=True, slots=True)
class ImportedTask:
    """One canonical task row, ready to apply; times are as written (local or offset)."""

    row_number: int
    task_id: str | None
    po_number: str
    task_type: TaskType
    origin_location_id: str
    destination_location_id: str
    quantity: Decimal
    ready_at: str
    due_at: str
    due_event: DueEvent
    pickup_service_minutes: int
    delivery_service_minutes: int
    priority: int
    required_vehicle_tags: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True, slots=True)
class TaskImportPreview:
    rows: tuple[ImportedTask, ...]
    issues: tuple[ValidationIssue, ...]
    column_mapping: Mapping[str, str]
    unknown_columns: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)


class _RowError(ValueError):
    def __init__(self, code: ValidationCode, message: str, field: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _issue(
    code: ValidationCode,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    row_number: int | None = None,
    field: str | None = None,
    task_id: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        row_number=row_number,
        field=field,
        task_id=task_id,
    )


def _text(value: Any) -> str:
    """Cell text; whole-number floats from spreadsheets lose their ``.0``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _name_key(value: str) -> str:
    return " ".join(value.split()).casefold()


class _LocationMatcher:
    def __init__(self, locations: Sequence[LocationRef]) -> None:
        self._ids = {location.location_id for location in locations}
        self._ids_folded: dict[str, list[str]] = {}
        self._names: dict[str, list[str]] = {}
        for location in locations:
            self._ids_folded.setdefault(location.location_id.casefold(), []).append(
                location.location_id
            )
            self._names.setdefault(_name_key(location.name), []).append(location.location_id)

    def match(self, value: str, field: str) -> str:
        if value in self._ids:
            return value
        by_id = self._ids_folded.get(value.casefold(), [])
        if len(by_id) == 1:
            return by_id[0]
        by_name = self._names.get(_name_key(value), [])
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise _RowError(
                ValidationCode.AMBIGUOUS_LOCATION,
                f"Several locations are called '{value}'. Use the location ID instead.",
                field,
            )
        raise _RowError(
            ValidationCode.UNKNOWN_LOCATION,
            f"No location has the ID or name '{value}'. Add it on the Locations page first, "
            "or correct the spelling.",
            field,
        )


def preview_task_import(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    locations: Sequence[LocationRef],
    plant_location_id: str,
    timezone: str | None = None,
    default_pickup_service_minutes: int = 0,
    default_delivery_service_minutes: int = 0,
) -> TaskImportPreview:
    """Map headers and check every row against the scenario's locations."""
    headers: list[str] = []
    for raw_row in raw_rows:
        for header in raw_row:
            if str(header) not in headers:
                headers.append(str(header))

    issues: list[ValidationIssue] = []
    mapping: dict[str, str] = {}
    source_for: dict[str, str] = {}
    unknown: list[str] = []
    for header in headers:
        canonical = TASK_HEADER_MAP.get(normalize_header(header))
        if canonical is None:
            unknown.append(header)
            issues.append(
                _issue(
                    ValidationCode.UNKNOWN_COLUMN,
                    f"Column '{header}' is not used and was ignored.",
                    severity=ValidationSeverity.WARNING,
                    field=header,
                )
            )
            continue
        if canonical in source_for:
            issues.append(
                _issue(
                    ValidationCode.DUPLICATE_COLUMN,
                    f"Columns '{source_for[canonical]}' and '{header}' both mean "
                    f"'{canonical}'. Keep only one.",
                    field=canonical,
                )
            )
            continue
        mapping[header] = canonical
        source_for[canonical] = header

    missing = [column for column in REQUIRED_SPREADSHEET_COLUMNS if column not in source_for]
    for column in missing:
        issues.append(
            _issue(
                ValidationCode.MISSING_REQUIRED_FIELD,
                f"The file needs a '{column}' column.",
                field=column,
            )
        )
    if missing:
        return TaskImportPreview((), tuple(issues), mapping, tuple(unknown))

    matcher = _LocationMatcher(locations)
    defaults = {
        "pickup_service_minutes": default_pickup_service_minutes,
        "delivery_service_minutes": default_delivery_service_minutes,
    }
    rows: list[ImportedTask] = []
    rows_by_id: dict[str, int] = {}
    rows_by_po: dict[str, int] = {}
    for offset, raw_row in enumerate(raw_rows):
        row_number = offset + FIRST_DATA_ROW
        values = {canonical: _text(raw_row.get(source)) for source, canonical in mapping.items()}
        if not any(values.values()):
            continue
        task_id = values.get("task_id") or None
        row_issues: list[ValidationIssue] = []
        try:
            task = _parse_row(
                values,
                row_number=row_number,
                matcher=matcher,
                plant_location_id=plant_location_id,
                timezone=timezone,
                defaults=defaults,
                issues=row_issues,
            )
        except _RowError as exc:
            row_issues.append(
                _issue(exc.code, str(exc), row_number=row_number, field=exc.field, task_id=task_id)
            )
            task = None
        if task_id is not None and task_id in rows_by_id:
            row_issues.append(
                _issue(
                    ValidationCode.DUPLICATE_TASK_ID,
                    f"Row {row_number} repeats task ID {task_id} from row {rows_by_id[task_id]}.",
                    row_number=row_number,
                    field="task_id",
                    task_id=task_id,
                )
            )
            task = None
        po_number = values.get("po_number", "")
        if po_number and po_number in rows_by_po:
            row_issues.append(
                _issue(
                    ValidationCode.DUPLICATE_PO_NUMBER,
                    f"PO number also appears on row {rows_by_po[po_number]}: {po_number}",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="po_number",
                    task_id=task_id,
                )
            )
        issues.extend(row_issues)
        if task_id is not None:
            rows_by_id.setdefault(task_id, row_number)
        if po_number:
            rows_by_po.setdefault(po_number, row_number)
        if task is not None:
            rows.append(task)
    if not rows and not any(issue.severity is ValidationSeverity.ERROR for issue in issues):
        issues.append(_issue(ValidationCode.MISSING_REQUIRED_FIELD, "The file has no task rows."))
    return TaskImportPreview(tuple(rows), tuple(issues), mapping, tuple(unknown))


def _parse_row(
    values: Mapping[str, str],
    *,
    row_number: int,
    matcher: _LocationMatcher,
    plant_location_id: str,
    timezone: str | None,
    defaults: Mapping[str, int],
    issues: list[ValidationIssue],
) -> ImportedTask | None:
    """One row as a task, or ``None`` after recording its problems in ``issues``."""
    task_id = values.get("task_id") or None
    problems: list[_RowError] = []

    def attempt[T](parse: Callable[..., T], *args: Any) -> T | None:
        try:
            return parse(*args)
        except _RowError as exc:
            problems.append(exc)
            return None

    if task_id is not None and (len(task_id) > MAX_ID_LENGTH or not _ID_PATTERN.fullmatch(task_id)):
        problems.append(
            _RowError(
                ValidationCode.INVALID_VALUE,
                f"Task ID '{task_id}' may use only letters, digits, '.', '_', ':' and '-', "
                f"must start with a letter or digit, and be at most {MAX_ID_LENGTH} characters.",
                "task_id",
            )
        )
    po_number = values.get("po_number", "")
    if not po_number:
        problems.append(
            _RowError(ValidationCode.MISSING_REQUIRED_FIELD, "The PO number is empty.", "po_number")
        )
    task_type: TaskType | None = attempt(_task_type, values.get("task_type", ""))
    origin = destination = None
    if task_type is not None:
        origin = attempt(
            _endpoint,
            values.get("origin_location_id", ""),
            "origin_location_id",
            task_type is TaskType.DROP,
            matcher,
            plant_location_id,
        )
        destination = attempt(
            _endpoint,
            values.get("destination_location_id", ""),
            "destination_location_id",
            task_type is TaskType.PICKUP,
            matcher,
            plant_location_id,
        )
        if origin is not None and destination is not None:
            attempt(_check_movement, task_type, origin, destination, plant_location_id)
    quantity: Decimal | None = attempt(_quantity, values.get("quantity", ""))
    ready_at = attempt(_moment, values.get("ready_at", ""), "ready_at", timezone)
    due_at = attempt(_moment, values.get("due_at", ""), "due_at", timezone)
    if ready_at is not None and due_at is not None:
        attempt(_check_order, ready_at, due_at)
    due_event: DueEvent | None = attempt(_due_event, values.get("due_event", ""))
    pickup_minutes: int | None = attempt(
        _minutes, values.get("pickup_service_minutes", ""), "pickup_service_minutes", defaults
    )
    delivery_minutes: int | None = attempt(
        _minutes, values.get("delivery_service_minutes", ""), "delivery_service_minutes", defaults
    )
    priority: int | None = attempt(_priority, values.get("priority", ""))

    for problem in problems:
        issues.append(
            _issue(
                problem.code,
                str(problem),
                row_number=row_number,
                field=problem.field,
                task_id=task_id,
            )
        )
    if (
        problems
        or task_type is None
        or origin is None
        or destination is None
        or quantity is None
        or ready_at is None
        or due_at is None
        or due_event is None
        or pickup_minutes is None
        or delivery_minutes is None
        or priority is None
    ):
        return None
    tags = tuple(
        sorted(
            {
                tag.strip().upper()
                for tag in values.get("required_vehicle_tags", "").split(",")
                if tag.strip()
            }
        )
    )
    return ImportedTask(
        row_number=row_number,
        task_id=task_id,
        po_number=po_number,
        task_type=task_type,
        origin_location_id=origin,
        destination_location_id=destination,
        quantity=quantity,
        ready_at=ready_at[0],
        due_at=due_at[0],
        due_event=due_event,
        pickup_service_minutes=pickup_minutes,
        delivery_service_minutes=delivery_minutes,
        priority=priority,
        required_vehicle_tags=tags,
        notes=values.get("notes") or None,
    )


def _task_type(value: str) -> TaskType:
    if not value:
        raise _RowError(
            ValidationCode.MISSING_REQUIRED_FIELD,
            "The movement type is empty: use PICKUP, DROP, or PICKUP_DROP.",
            "task_type",
        )
    normalized = normalize_task_type(value)
    if not isinstance(normalized, TaskType):
        try:
            return TaskType(normalized)
        except ValueError:
            raise _RowError(
                ValidationCode.INVALID_VALUE,
                f"Movement type '{value}' is not PICKUP, DROP, or PICKUP_DROP.",
                "task_type",
            ) from None
    return normalized


def _endpoint(
    value: str,
    field: str,
    is_plant_end: bool,
    matcher: _LocationMatcher,
    plant_location_id: str,
) -> str:
    if not value:
        if is_plant_end:
            return plant_location_id
        side = "origin" if field == "origin_location_id" else "destination"
        raise _RowError(
            ValidationCode.MISSING_REQUIRED_FIELD,
            f"The {side} is empty. Enter a location ID or name.",
            field,
        )
    return matcher.match(value, field)


def _check_movement(task_type: TaskType, origin: str, destination: str, plant: str) -> None:
    if origin == destination:
        raise _RowError(
            ValidationCode.INVALID_VALUE,
            "The origin and destination are the same location.",
            "destination_location_id",
        )
    if task_type is TaskType.PICKUP and (origin == plant or destination != plant):
        message = "A pickup goes from a supplier to the plant."
    elif task_type is TaskType.DROP and (origin != plant or destination == plant):
        message = "A drop goes from the plant to a customer."
    elif task_type is TaskType.PICKUP_DROP and plant in (origin, destination):
        message = "A pickup-drop goes between two places other than the plant."
    else:
        return
    raise _RowError(ValidationCode.TASK_TYPE_LOCATION_MISMATCH, message, "task_type")


def _quantity(value: str) -> Decimal:
    if not value:
        raise _RowError(ValidationCode.MISSING_REQUIRED_FIELD, "The quantity is empty.", "quantity")
    try:
        quantity = Decimal(value)
    except InvalidOperation:
        raise _RowError(
            ValidationCode.INVALID_VALUE, f"Quantity '{value}' is not a number.", "quantity"
        ) from None
    exponent = quantity.normalize().as_tuple().exponent
    if not quantity.is_finite() or quantity <= 0:
        raise _RowError(
            ValidationCode.INVALID_VALUE, "The quantity must be more than zero.", "quantity"
        )
    if isinstance(exponent, int) and -exponent > 3:
        raise _RowError(
            ValidationCode.INVALID_VALUE,
            "The quantity may have at most three decimal places.",
            "quantity",
        )
    return quantity


def _moment(value: str, field: str, timezone: str | None) -> tuple[str, datetime | None]:
    """The time as stored text, plus the UTC instant when it can be fixed without shifts."""
    label = "ready time" if field == "ready_at" else "due time"
    if not value:
        raise _RowError(ValidationCode.MISSING_REQUIRED_FIELD, f"The {label} is empty.", field)
    try:
        parsed = parse_datetime_input(value)
    except DateTimeNormalizationError:
        raise _RowError(
            ValidationCode.INVALID_DATETIME,
            f"The {label} '{value}' is not a date and time such as 2026-12-07 08:00.",
            field,
        ) from None
    if not isinstance(parsed, datetime):
        assert isinstance(parsed, date)
        return parsed.isoformat(), None
    text = parsed.replace(microsecond=0).isoformat()
    if timezone is None:
        return text, None
    try:
        return text, normalize_datetime(parsed, timezone)
    except DateTimeNormalizationError as exc:
        raise _RowError(exc.code, f"The {label}: {exc}", field) from None


def _check_order(ready: tuple[str, datetime | None], due: tuple[str, datetime | None]) -> None:
    if ready[1] is not None and due[1] is not None and ready[1] > due[1]:
        raise _RowError(
            ValidationCode.READY_AFTER_DUE, "The ready time is after the due time.", "ready_at"
        )


def _due_event(value: str) -> DueEvent:
    normalized = normalize_due_event(value)
    if isinstance(normalized, DueEvent):
        return normalized
    try:
        return DueEvent(normalized)
    except ValueError:
        raise _RowError(
            ValidationCode.INVALID_VALUE,
            f"'{value}' is not PICKUP_COMPLETE or DELIVERY_COMPLETE.",
            "due_event",
        ) from None


def _minutes(value: str, field: str, defaults: Mapping[str, int]) -> int:
    if not value:
        return defaults[field]
    try:
        number = Decimal(value)
    except InvalidOperation:
        number = Decimal(-1)
    if number != number.to_integral_value() or not 0 <= number <= MAX_SERVICE_MINUTES:
        raise _RowError(
            ValidationCode.INVALID_VALUE,
            f"Service minutes must be a whole number from 0 to {MAX_SERVICE_MINUTES}.",
            field,
        )
    return int(number)


def _priority(value: str) -> int:
    if not value:
        return DEFAULT_PRIORITY
    if value.casefold() in _PRIORITY_BY_LABEL:
        return _PRIORITY_BY_LABEL[value.casefold()]
    if value.isdigit() and int(value) in PRIORITY_LABELS:
        return int(value)
    labels = ", ".join(f"{number} {label}" for number, label in PRIORITY_LABELS.items())
    raise _RowError(ValidationCode.INVALID_VALUE, f"Priority must be one of {labels}.", "priority")


# --- templates --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemplateColumn:
    name: str
    required: bool
    aliases: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class ImportTemplate:
    kind: str
    columns: tuple[TemplateColumn, ...]
    example_rows: tuple[Mapping[str, str | int], ...]


_TASK_COLUMN_NOTES = {
    "task_id": "Optional in a spreadsheet; new tasks are numbered when left empty.",
    "origin_location_id": (
        "Location ID or exact name. May be empty for a drop, which starts at the plant."
    ),
    "destination_location_id": (
        "Location ID or exact name. May be empty for a pickup, which ends at the plant."
    ),
    "task_type": "PICKUP (supplier to plant), DROP (plant to customer), or PICKUP_DROP.",
    "ready_at": "Plant-local date and time, such as 2026-12-07 08:00.",
    "due_at": "Plant-local date and time, such as 2026-12-07 14:00.",
    "pickup_service_minutes": "Whole minutes; the scenario default when empty.",
    "delivery_service_minutes": "Whole minutes; the scenario default when empty.",
    "priority": "1 Routine (default) to 5 Critical; the label also works.",
}


def _template_columns(
    specs: Sequence[ImportColumnSpec], optional: frozenset[str], notes: Mapping[str, str]
) -> tuple[TemplateColumn, ...]:
    return tuple(
        TemplateColumn(
            name=spec.canonical_name,
            required=spec.required and spec.canonical_name not in optional,
            aliases=spec.aliases,
            description=notes.get(spec.canonical_name, spec.description),
        )
        for spec in specs
    )


IMPORT_TEMPLATES: Mapping[str, ImportTemplate] = {
    "tasks": ImportTemplate(
        kind="tasks",
        columns=_template_columns(
            TASK_IMPORT_COLUMNS, SPREADSHEET_OPTIONAL_COLUMNS, _TASK_COLUMN_NOTES
        ),
        example_rows=(
            {
                "task_id": "",
                "po_number": "PO-1001",
                "task_type": "PICKUP",
                "origin_location_id": "Acme Steel",
                "destination_location_id": "",
                "quantity": 12,
                "ready_at": "2026-12-07 08:00",
                "due_at": "2026-12-07 14:00",
                "due_event": "DELIVERY_COMPLETE",
                "pickup_service_minutes": 15,
                "delivery_service_minutes": 15,
                "priority": 1,
                "required_vehicle_tags": "",
                "notes": "Example row: replace it with your own",
            },
        ),
    ),
    "locations": ImportTemplate(
        kind="locations",
        columns=_template_columns(LOCATION_IMPORT_COLUMNS, frozenset(), {}),
        example_rows=(
            {
                "name": "Acme Steel",
                "address": "100 Example Road, Toronto, ON",
                "location_id": "",
            },
        ),
    ),
}
