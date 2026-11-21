"""Task spreadsheet import contract (plan §9.5, V1.1-M4).

The backend is the only definition of task columns and aliases: the import preview
and JSON validation map headers through the same table.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.domain.import_contract import TASK_HEADER_MAP, TASK_IMPORT_COLUMNS
from backend.app.domain.task_import import (
    IMPORT_TEMPLATES,
    LocationRef,
    TaskImportPreview,
    preview_task_import,
)

LOCATIONS = (
    LocationRef("PLANT", "Main plant"),
    LocationRef("ACME", "Acme Steel"),
    LocationRef("BOLT", "Bolt Customer"),
    LocationRef("TWIN-1", "Twin Yard"),
    LocationRef("TWIN-2", "Twin Yard"),
)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "PO Number": "PO-1",
        "Type": "pickup",
        "Origin": "Acme Steel",
        "Qty": 12,
        "Ready": "2026-12-07 08:00",
        "Due": "2026-12-07 14:00",
    }
    row.update(overrides)
    return {key: value for key, value in row.items() if value is not None}


def _preview(*rows: dict[str, Any], **kwargs: Any) -> TaskImportPreview:
    return preview_task_import(
        list(rows),
        locations=LOCATIONS,
        plant_location_id="PLANT",
        timezone=kwargs.pop("timezone", "America/Toronto"),
        **kwargs,
    )


def _codes(preview: TaskImportPreview) -> list[tuple[str, int | None, str | None]]:
    return [(issue.code.value, issue.row_number, issue.field) for issue in preview.issues]


def test_headers_map_through_the_shared_contract() -> None:
    preview = _preview(_row())

    assert preview.valid
    assert preview.column_mapping == {
        "PO Number": "po_number",
        "Type": "task_type",
        "Origin": "origin_location_id",
        "Qty": "quantity",
        "Ready": "ready_at",
        "Due": "due_at",
    }
    for header, canonical in preview.column_mapping.items():
        assert TASK_HEADER_MAP[header.strip().lower().replace(" ", "_")] == canonical


def test_a_pickup_row_becomes_a_canonical_task_with_the_plant_filled_in() -> None:
    [task] = _preview(_row(), default_pickup_service_minutes=20).rows

    assert task.row_number == 2
    assert task.task_id is None
    assert task.task_type.value == "PICKUP"
    assert (task.origin_location_id, task.destination_location_id) == ("ACME", "PLANT")
    assert task.ready_at == "2026-12-07T08:00:00"
    assert task.due_at == "2026-12-07T14:00:00"
    assert task.due_event.value == "DELIVERY_COMPLETE"
    assert task.pickup_service_minutes == 20
    assert task.delivery_service_minutes == 0
    assert task.priority == 1


def test_a_drop_row_may_leave_its_origin_empty() -> None:
    [task] = _preview(_row(Type="Delivery", Origin=None, Destination="bolt customer")).rows

    assert (task.origin_location_id, task.destination_location_id) == ("PLANT", "BOLT")


@pytest.mark.parametrize("cell", ["ACME", "acme", "Acme Steel", "  ACME   steel "])
def test_locations_match_by_id_or_exact_name(cell: str) -> None:
    [task] = _preview(_row(Origin=cell)).rows

    assert task.origin_location_id == "ACME"


def test_unknown_and_ambiguous_locations_block_the_import() -> None:
    preview = _preview(
        _row(Origin="Nowhere Inc"),
        _row(**{"PO Number": "PO-2", "Type": "pickup_drop", "Origin": "Twin Yard"}),
    )

    assert not preview.valid
    assert ("UNKNOWN_LOCATION", 2, "origin_location_id") in _codes(preview)
    assert ("AMBIGUOUS_LOCATION", 3, "origin_location_id") in _codes(preview)
    assert ("MISSING_REQUIRED_FIELD", 3, "destination_location_id") in _codes(preview)
    assert preview.rows == ()


def test_movement_and_plant_must_agree() -> None:
    preview = _preview(_row(Destination="BOLT"))

    assert ("TASK_TYPE_LOCATION_MISMATCH", 2, "task_type") in _codes(preview)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"Qty": "0"}, ("INVALID_VALUE", 2, "quantity")),
        ({"Qty": "1.2345"}, ("INVALID_VALUE", 2, "quantity")),
        ({"Qty": "lots"}, ("INVALID_VALUE", 2, "quantity")),
        ({"Ready": "07/12/2026"}, ("INVALID_DATETIME", 2, "ready_at")),
        ({"Due": "2026-12-07 06:00"}, ("READY_AFTER_DUE", 2, "ready_at")),
        ({"Ready": "2026-03-08 02:30"}, ("NONEXISTENT_LOCAL_TIME", 2, "ready_at")),
        ({"Priority": "urgent"}, ("INVALID_VALUE", 2, "priority")),
        ({"Pickup minutes": "7.5"}, ("INVALID_VALUE", 2, "pickup_service_minutes")),
        ({"Type": "teleport"}, ("INVALID_VALUE", 2, "task_type")),
        ({"Task ID": "bad id!"}, ("INVALID_VALUE", 2, "task_id")),
        ({"Deadline applies to": "whenever"}, ("INVALID_VALUE", 2, "due_event")),
    ],
)
def test_bad_cells_are_row_errors(overrides: dict[str, Any], expected: tuple[Any, ...]) -> None:
    preview = _preview(_row(**overrides))

    assert not preview.valid
    assert expected in _codes(preview)
    assert preview.rows == ()


def test_priority_accepts_numbers_and_labels_and_tags_are_normalised() -> None:
    preview = _preview(
        _row(Priority="Critical", **{"Vehicle tags": "reefer, Std ,reefer"}),
        _row(**{"PO Number": "PO-2", "Priority": 4}),
    )

    assert [task.priority for task in preview.rows] == [5, 4]
    assert preview.rows[0].required_vehicle_tags == ("REEFER", "STD")


def test_duplicate_task_ids_block_and_duplicate_po_numbers_warn() -> None:
    preview = _preview(
        _row(**{"Task ID": "T-1"}),
        _row(**{"Task ID": "T-1", "PO Number": "PO-2"}),
        _row(**{"Task ID": "T-3"}),
    )

    assert ("DUPLICATE_TASK_ID", 3, "task_id") in _codes(preview)
    assert ("DUPLICATE_PO_NUMBER", 4, "po_number") in _codes(preview)
    assert not preview.valid


def test_missing_and_duplicate_columns_and_unknown_columns() -> None:
    missing = preview_task_import(
        [{"PO": "1", "Type": "pickup"}], locations=LOCATIONS, plant_location_id="PLANT"
    )
    assert not missing.valid
    assert {issue.field for issue in missing.issues} >= {"quantity", "ready_at", "due_at"}

    duplicate = _preview(_row(quantity=3))
    assert ("DUPLICATE_COLUMN", None, "quantity") in _codes(duplicate)

    unknown = _preview(_row(Colour="red"))
    assert unknown.valid
    assert unknown.unknown_columns == ("Colour",)


def test_blank_rows_are_skipped_and_an_empty_file_is_an_error() -> None:
    preview = _preview(_row(), {"PO Number": None, "Type": "", "Qty": None})
    assert preview.valid
    assert len(preview.rows) == 1

    empty = preview_task_import(
        [{"PO Number": "", "Type": "", "Qty": "", "Ready": "", "Due": ""}],
        locations=LOCATIONS,
        plant_location_id="PLANT",
    )
    assert not empty.valid


def test_date_only_values_are_kept_for_the_shift_rule() -> None:
    [task] = _preview(_row(Ready="2026-12-07", Due="2026-12-07")).rows

    assert (task.ready_at, task.due_at) == ("2026-12-07", "2026-12-07")


def test_templates_come_from_the_same_contract() -> None:
    tasks = IMPORT_TEMPLATES["tasks"]
    assert [column.name for column in tasks.columns] == [
        spec.canonical_name for spec in TASK_IMPORT_COLUMNS
    ]
    assert {column.name: column.aliases for column in tasks.columns} == {
        spec.canonical_name: spec.aliases for spec in TASK_IMPORT_COLUMNS
    }
    required = {column.name for column in tasks.columns if column.required}
    assert required == {"po_number", "task_type", "quantity", "ready_at", "due_at"}
    [example] = tasks.example_rows
    assert set(example) == {spec.canonical_name for spec in TASK_IMPORT_COLUMNS}

    example_preview = preview_task_import(
        [dict(example)],
        locations=(LocationRef("PLANT", "Plant"), LocationRef("ACME-STEEL", "Acme Steel")),
        plant_location_id="PLANT",
        timezone="America/Toronto",
    )
    assert example_preview.valid, example_preview.issues

    locations = IMPORT_TEMPLATES["locations"]
    assert [column.name for column in locations.columns] == ["name", "address", "location_id"]
