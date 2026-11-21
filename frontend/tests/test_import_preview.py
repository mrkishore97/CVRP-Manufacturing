"""Reading spreadsheet files and writing import templates (V1.1-M4).

The frontend no longer maps task columns itself: the backend import contract is the
only definition (plan §9.5, finding F12). These tests cover what is left here.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

import frontend.import_preview as import_preview
from frontend.import_preview import read_table_rows, template_csv_bytes, template_xlsx_bytes

TEMPLATE = {
    "kind": "tasks",
    "columns": [
        {"name": "po_number", "required": True, "aliases": ["po"], "description": "PO."},
        {"name": "quantity", "required": True, "aliases": ["qty"], "description": "Load."},
        {"name": "notes", "required": False, "aliases": [], "description": "Notes."},
    ],
    "example_rows": [{"po_number": "PO-1001", "quantity": 12, "notes": "=HYPERLINK(1)"}],
}


def test_the_frontend_has_no_column_alias_table_of_its_own() -> None:
    names = set(vars(import_preview))
    assert not {"_HEADER_ALIASES", "REQUIRED_TASK_COLUMNS", "preview_task_import"} & names


def test_csv_rows_keep_their_own_headers_and_blank_cells_become_none() -> None:
    content = "PO Number,Qty,Notes\nPO-1,4,\nPO-2,2.5,rush\n".encode("utf-8-sig")

    rows = read_table_rows("tasks.csv", content)

    assert rows == [
        {"PO Number": "PO-1", "Qty": "4", "Notes": None},
        {"PO Number": "PO-2", "Qty": "2.5", "Notes": "rush"},
    ]


def test_xlsx_rows_keep_numbers() -> None:
    buffer = io.BytesIO()
    pd.DataFrame([{"PO": "PO-1", "Qty": 4}]).to_excel(buffer, index=False)

    rows = read_table_rows("tasks.xlsx", buffer.getvalue())

    assert rows == [{"PO": "PO-1", "Qty": 4}]


def test_unreadable_and_empty_files_are_reported() -> None:
    with pytest.raises(ValueError, match="no rows"):
        read_table_rows("tasks.csv", b"PO,Qty\n")
    with pytest.raises(ValueError, match="could not be read"):
        read_table_rows("tasks.xlsx", b"not a workbook")


def test_templates_have_the_backend_columns_and_an_escaped_example_row() -> None:
    csv_rows = read_table_rows("template.csv", template_csv_bytes(TEMPLATE))
    assert list(csv_rows[0]) == ["po_number", "quantity", "notes"]
    assert csv_rows[0]["po_number"] == "PO-1001"
    assert not str(csv_rows[0]["notes"]).startswith("=")

    workbook = pd.read_excel(io.BytesIO(template_xlsx_bytes(TEMPLATE)), sheet_name=None)
    assert list(workbook) == ["Template", "Columns"]
    assert list(workbook["Template"].columns) == ["po_number", "quantity", "notes"]
    assert workbook["Columns"]["Required"].tolist() == ["Yes", "Yes", "No"]
