"""Frontend import-preview mapping tests."""

import pandas as pd

from frontend.import_preview import preview_task_import


def test_import_preview_maps_aliases_and_visible_row_errors() -> None:
    frame = pd.DataFrame(
        [
            {
                "Task ID": "TASK-1",
                "PO": "PO-1",
                "Type": "pickup",
                "Origin": "SUPPLIER_A",
                "Destination": "PLANT",
                "Qty": 4,
                "Ready": "2026-06-22T07:00:00-04:00",
                "Deadline": "",
                "Planner Comment": "not a canonical column",
            }
        ]
    )

    preview = preview_task_import(frame)

    assert preview.rows[0]["po_number"] == "PO-1"
    assert preview.rows[0]["quantity"] == 4
    issue_rows = preview.issue_rows()
    assert {(issue["code"], issue["field"], issue["row_number"]) for issue in issue_rows} >= {
        ("UNKNOWN_COLUMN", None, None),
        ("MISSING_REQUIRED_VALUE", "due_at", 2),
    }
    assert preview.has_blocking_errors


def test_import_preview_reports_duplicate_mapped_columns() -> None:
    frame = pd.DataFrame(
        [["TASK-1", "PO-1", "PO-DUP", "PICKUP", "SUPPLIER_A", "PLANT", 4, "ready", "due"]],
        columns=[
            "task_id",
            "po",
            "po_number",
            "task_type",
            "origin_location_id",
            "destination_location_id",
            "quantity",
            "ready_at",
            "due_at",
        ],
    )

    preview = preview_task_import(frame)

    assert any(
        issue.code == "DUPLICATE_COLUMN" and issue.field == "po_number" for issue in preview.issues
    )
    assert preview.has_blocking_errors
