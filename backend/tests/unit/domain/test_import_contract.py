"""CSV/XLSX column-mapping contract tests."""

import pytest

from backend.app.domain.enums import DueEvent, TaskType, ValidationCode
from backend.app.domain.import_contract import (
    ImportMappingError,
    map_task_import_row,
    missing_required_task_columns,
)


def test_human_friendly_headers_and_values_map_to_canonical_fields() -> None:
    mapped = map_task_import_row(
        {
            "Task ID": "TASK-1",
            "PO Number": "PO-1",
            "Movement Type": "pickup delivery",
            "Pickup Location": "SUPPLIER_A",
            "Drop Location": "CUSTOMER_A",
            "Qty": 4,
            "Ready Date": "2026-06-22T08:00:00-04:00",
            "Deadline": "2026-06-22T12:00:00-04:00",
            "Deadline Applies To": "delivery",
            "Planner Color": "blue",
        }
    )

    assert mapped.values["task_type"] is TaskType.PICKUP_DROP
    assert mapped.values["due_event"] is DueEvent.DELIVERY_COMPLETE
    assert mapped.values["origin_location_id"] == "SUPPLIER_A"
    assert mapped.values["destination_location_id"] == "CUSTOMER_A"
    assert mapped.unknown_columns == ("Planner Color",)
    assert missing_required_task_columns(mapped.values) == ()


def test_two_aliases_for_one_canonical_column_are_rejected() -> None:
    with pytest.raises(ImportMappingError) as error:
        map_task_import_row({"quantity": 4, "qty": 5})

    assert error.value.code is ValidationCode.DUPLICATE_COLUMN
    assert error.value.field == "quantity"


def test_missing_required_columns_are_reported_canonically() -> None:
    mapped = map_task_import_row({"Task ID": "TASK-1", "PO Number": "PO-1"})

    assert missing_required_task_columns(mapped.values) == (
        "destination_location_id",
        "due_at",
        "origin_location_id",
        "quantity",
        "ready_at",
        "task_type",
    )
