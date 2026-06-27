"""Frontend CSV/XLSX task import preview helpers.

The backend remains the source of truth for validation. This module gives planners
fast, visible feedback on headers and blank required cells before they send a
scenario to the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

REQUIRED_TASK_COLUMNS = (
    "task_id",
    "po_number",
    "task_type",
    "origin_location_id",
    "destination_location_id",
    "quantity",
    "ready_at",
    "due_at",
)

OPTIONAL_TASK_COLUMNS = (
    "due_event",
    "pickup_service_minutes",
    "delivery_service_minutes",
    "priority",
    "required_vehicle_tags",
    "notes",
)

_HEADER_ALIASES: dict[str, str] = {
    "id": "task_id",
    "task_id": "task_id",
    "task id": "task_id",
    "po": "po_number",
    "po_number": "po_number",
    "po number": "po_number",
    "purchase_order": "po_number",
    "purchase order": "po_number",
    "purchase_order_number": "po_number",
    "purchase order number": "po_number",
    "type": "task_type",
    "task_type": "task_type",
    "movement_type": "task_type",
    "movement type": "task_type",
    "origin": "origin_location_id",
    "origin_location_id": "origin_location_id",
    "pickup_location": "origin_location_id",
    "pickup location": "origin_location_id",
    "from_location": "origin_location_id",
    "from location": "origin_location_id",
    "destination": "destination_location_id",
    "destination_location_id": "destination_location_id",
    "drop_location": "destination_location_id",
    "drop location": "destination_location_id",
    "to_location": "destination_location_id",
    "to location": "destination_location_id",
    "quantity": "quantity",
    "load": "quantity",
    "demand": "quantity",
    "qty": "quantity",
    "ready_at": "ready_at",
    "ready": "ready_at",
    "ready_date": "ready_at",
    "ready date": "ready_at",
    "ready_datetime": "ready_at",
    "ready datetime": "ready_at",
    "available_at": "ready_at",
    "available at": "ready_at",
    "due_at": "due_at",
    "due": "due_at",
    "due_date": "due_at",
    "due date": "due_at",
    "due_datetime": "due_at",
    "due datetime": "due_at",
    "deadline": "due_at",
    "due_event": "due_event",
    "deadline_event": "due_event",
    "deadline event": "due_event",
    "deadline_applies_to": "due_event",
    "deadline applies to": "due_event",
    "pickup_service_minutes": "pickup_service_minutes",
    "pickup_service": "pickup_service_minutes",
    "pickup service": "pickup_service_minutes",
    "pickup_minutes": "pickup_service_minutes",
    "pickup minutes": "pickup_service_minutes",
    "delivery_service_minutes": "delivery_service_minutes",
    "delivery_service": "delivery_service_minutes",
    "delivery service": "delivery_service_minutes",
    "drop_service": "delivery_service_minutes",
    "drop service": "delivery_service_minutes",
    "delivery_minutes": "delivery_service_minutes",
    "delivery minutes": "delivery_service_minutes",
    "priority": "priority",
    "task_priority": "priority",
    "task priority": "priority",
    "required_vehicle_tags": "required_vehicle_tags",
    "vehicle_tags": "required_vehicle_tags",
    "vehicle tags": "required_vehicle_tags",
    "required_tags": "required_vehicle_tags",
    "required tags": "required_vehicle_tags",
    "notes": "notes",
    "note": "notes",
    "comments": "notes",
}


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """One visible import-preview issue."""

    severity: str
    code: str
    message: str
    field: str | None = None
    row_number: int | None = None
    source_column: str | None = None


@dataclass(frozen=True, slots=True)
class ImportPreview:
    """Canonical task rows plus preview-only warnings/errors."""

    rows: tuple[dict[str, Any], ...]
    issues: tuple[ImportIssue, ...]

    @property
    def has_blocking_errors(self) -> bool:
        """Return whether the preview found errors requiring spreadsheet edits."""
        return any(issue.severity == "error" for issue in self.issues)

    def issue_rows(self) -> list[dict[str, Any]]:
        """Return issues in a table-friendly shape."""
        return [
            {
                "severity": issue.severity,
                "code": issue.code,
                "row_number": issue.row_number,
                "field": issue.field,
                "source_column": issue.source_column,
                "message": issue.message,
            }
            for issue in self.issues
        ]


def normalize_header(value: str) -> str:
    """Normalize a spreadsheet header to a stable comparison key."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold())
    return normalized.strip("_")


def _canonical_name(header: str) -> str | None:
    direct = _HEADER_ALIASES.get(header.strip().casefold())
    if direct is not None:
        return direct
    return _HEADER_ALIASES.get(normalize_header(header))


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def preview_task_import(frame: pd.DataFrame) -> ImportPreview:
    """Map a CSV/XLSX dataframe into canonical task rows and visible issues."""
    issues: list[ImportIssue] = []
    mapped_columns: dict[str, str] = {}
    canonical_to_source: dict[str, str] = {}

    for raw_column in frame.columns:
        source_column = str(raw_column)
        canonical = _canonical_name(source_column)
        if canonical is None:
            issues.append(
                ImportIssue(
                    severity="warning",
                    code="UNKNOWN_COLUMN",
                    source_column=source_column,
                    message=f"Column '{source_column}' is not used by the planner.",
                )
            )
            continue
        existing_source = canonical_to_source.get(canonical)
        if existing_source is not None:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="DUPLICATE_COLUMN",
                    field=canonical,
                    source_column=source_column,
                    message=(
                        f"Columns '{existing_source}' and '{source_column}' both map to "
                        f"'{canonical}'. Keep only one."
                    ),
                )
            )
            continue
        mapped_columns[source_column] = canonical
        canonical_to_source[canonical] = source_column

    for required_column in REQUIRED_TASK_COLUMNS:
        if required_column not in canonical_to_source:
            issues.append(
                ImportIssue(
                    severity="error",
                    code="MISSING_COLUMN",
                    field=required_column,
                    message=f"Required column '{required_column}' is missing.",
                )
            )

    rows: list[dict[str, Any]] = []
    for row_offset, (_index, row) in enumerate(frame.iterrows(), start=2):
        canonical_row: dict[str, Any] = {}
        for source_column, canonical in mapped_columns.items():
            value = row[source_column]
            canonical_row[canonical] = None if _is_blank(value) else value
        rows.append(canonical_row)
        for required_column in REQUIRED_TASK_COLUMNS:
            if _is_blank(canonical_row.get(required_column)):
                issues.append(
                    ImportIssue(
                        severity="error",
                        code="MISSING_REQUIRED_VALUE",
                        field=required_column,
                        row_number=row_offset,
                        source_column=canonical_to_source.get(required_column),
                        message=(
                            f"Row {row_offset} is missing required value '{required_column}'."
                        ),
                    )
                )

    return ImportPreview(rows=tuple(rows), issues=tuple(issues))
