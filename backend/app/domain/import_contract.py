"""Format-neutral CSV/XLSX task-column mapping contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.domain.enums import DueEvent, TaskType, ValidationCode


@dataclass(frozen=True, slots=True)
class ImportColumnSpec:
    """One canonical task column and accepted human-friendly aliases."""

    canonical_name: str
    required: bool
    aliases: tuple[str, ...]
    description: str


TASK_IMPORT_COLUMNS: tuple[ImportColumnSpec, ...] = (
    ImportColumnSpec("task_id", True, ("id", "task id"), "Unique movement-line ID."),
    ImportColumnSpec(
        "po_number",
        True,
        ("po", "po number", "purchase order", "purchase order number"),
        "Business PO reference; duplicates are allowed with a warning.",
    ),
    ImportColumnSpec("task_type", True, ("type", "movement type"), "Pickup/drop behavior."),
    ImportColumnSpec(
        "origin_location_id",
        True,
        ("origin", "pickup location", "pickup_location", "from location"),
        "Origin location ID from the location table.",
    ),
    ImportColumnSpec(
        "destination_location_id",
        True,
        ("destination", "drop location", "drop_location", "to location"),
        "Destination location ID from the location table.",
    ),
    ImportColumnSpec("quantity", True, ("load", "demand", "qty"), "Positive load quantity."),
    ImportColumnSpec(
        "ready_at",
        True,
        ("ready", "ready date", "ready datetime", "available at"),
        "Earliest pickup/service datetime.",
    ),
    ImportColumnSpec(
        "due_at",
        True,
        ("due", "due date", "due datetime", "deadline"),
        "Hard completion deadline.",
    ),
    ImportColumnSpec(
        "due_event",
        False,
        ("deadline event", "deadline applies to"),
        "PICKUP_COMPLETE or DELIVERY_COMPLETE; defaults to delivery completion.",
    ),
    ImportColumnSpec(
        "pickup_service_minutes",
        False,
        ("pickup service", "pickup minutes"),
        "Minutes spent completing pickup service.",
    ),
    ImportColumnSpec(
        "delivery_service_minutes",
        False,
        ("delivery service", "drop service", "delivery minutes"),
        "Minutes spent completing delivery service.",
    ),
    ImportColumnSpec("priority", False, ("task priority",), "Priority from 1 through 5."),
    ImportColumnSpec(
        "required_vehicle_tags",
        False,
        ("vehicle tags", "required tags"),
        "Comma-separated compatibility tags.",
    ),
    ImportColumnSpec("notes", False, ("note", "comments"), "Optional planner notes."),
)


def normalize_header(value: str) -> str:
    """Normalize CSV/XLSX headers consistently without depending on pandas."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold())
    return normalized.strip("_")


def _build_header_map() -> dict[str, str]:
    header_map: dict[str, str] = {}
    for specification in TASK_IMPORT_COLUMNS:
        for header in (specification.canonical_name, *specification.aliases):
            normalized = normalize_header(header)
            existing = header_map.get(normalized)
            if existing is not None and existing != specification.canonical_name:
                raise RuntimeError(f"import alias collision: {header}")
            header_map[normalized] = specification.canonical_name
    return header_map


TASK_HEADER_MAP = _build_header_map()


class ImportMappingError(ValueError):
    """A row contains columns that cannot be mapped unambiguously."""

    def __init__(self, code: ValidationCode, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


@dataclass(frozen=True, slots=True)
class MappedImportRow:
    """Canonical values plus unknown source columns for warning display."""

    values: dict[str, Any]
    unknown_columns: tuple[str, ...]


TASK_TYPE_ALIASES: dict[str, TaskType] = {
    "pickup": TaskType.PICKUP,
    "pick_up": TaskType.PICKUP,
    "inbound": TaskType.PICKUP,
    "drop": TaskType.DROP,
    "delivery": TaskType.DROP,
    "outbound": TaskType.DROP,
    "pickup_drop": TaskType.PICKUP_DROP,
    "pickup_delivery": TaskType.PICKUP_DROP,
    "pair": TaskType.PICKUP_DROP,
}

DUE_EVENT_ALIASES: dict[str, DueEvent] = {
    "pickup": DueEvent.PICKUP_COMPLETE,
    "pickup_complete": DueEvent.PICKUP_COMPLETE,
    "pickup_completed": DueEvent.PICKUP_COMPLETE,
    "delivery": DueEvent.DELIVERY_COMPLETE,
    "drop": DueEvent.DELIVERY_COMPLETE,
    "delivery_complete": DueEvent.DELIVERY_COMPLETE,
    "delivery_completed": DueEvent.DELIVERY_COMPLETE,
}


def normalize_task_type(value: Any) -> Any:
    if isinstance(value, TaskType):
        return value
    if isinstance(value, str):
        normalized = normalize_header(value)
        return TASK_TYPE_ALIASES.get(normalized, value.strip().upper())
    return value


def normalize_due_event(value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return DueEvent.DELIVERY_COMPLETE
    if isinstance(value, DueEvent):
        return value
    if isinstance(value, str):
        normalized = normalize_header(value)
        return DUE_EVENT_ALIASES.get(normalized, value.strip().upper())
    return value


def map_task_import_row(row: Mapping[str, Any]) -> MappedImportRow:
    """Map one CSV/XLSX-like row to canonical task field names."""
    mapped: dict[str, Any] = {}
    unknown: list[str] = []
    for original_header, value in row.items():
        normalized_header = normalize_header(str(original_header))
        canonical_header = TASK_HEADER_MAP.get(normalized_header)
        if canonical_header is None:
            unknown.append(str(original_header))
            continue
        if canonical_header in mapped:
            raise ImportMappingError(
                ValidationCode.DUPLICATE_COLUMN,
                f"Multiple columns map to {canonical_header}.",
                canonical_header,
            )
        mapped[canonical_header] = value

    mapped["task_type"] = normalize_task_type(mapped.get("task_type"))
    mapped["due_event"] = normalize_due_event(mapped.get("due_event"))
    mapped.setdefault("pickup_service_minutes", 0)
    mapped.setdefault("delivery_service_minutes", 0)
    mapped.setdefault("priority", 1)
    mapped.setdefault("required_vehicle_tags", frozenset())
    return MappedImportRow(values=mapped, unknown_columns=tuple(sorted(unknown)))


def missing_required_task_columns(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return required canonical fields absent or blank after mapping."""
    required = {
        specification.canonical_name
        for specification in TASK_IMPORT_COLUMNS
        if specification.required
    }
    return tuple(
        sorted(
            field
            for field in required
            if field not in row or row[field] is None or str(row[field]).strip() == ""
        )
    )
