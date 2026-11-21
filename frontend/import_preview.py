"""Reading spreadsheet files and writing import templates.

Since V1.1-M4 the frontend has no column table of its own (plan §9.5, finding F12):
the backend's import contract maps headers and checks rows for tasks and locations.
This module only turns an uploaded CSV/XLSX file into rows keyed by its own headers,
and turns the backend's template description into downloadable CSV and XLSX files.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

import pandas as pd

from frontend.export_utils import escape_spreadsheet_value


def read_table_rows(file_name: str, content: bytes) -> list[dict[str, Any]]:
    """Rows of a CSV or XLSX file keyed by its headers; cells are text or numbers."""
    try:
        if file_name.lower().endswith(".xlsx"):
            frame = pd.read_excel(io.BytesIO(content), dtype=object)
        else:
            frame = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8-sig")
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"The file could not be read: {exc}") from exc
    records: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        records.append({str(key): _cell(value) for key, value in record.items()})
    if not records:
        raise ValueError("The file has no rows.")
    return records


def _cell(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _template_frames(template: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [column for column in template.get("columns", []) if isinstance(column, dict)]
    names = [str(column["name"]) for column in columns]
    examples = [row for row in template.get("example_rows", []) if isinstance(row, dict)]
    example_frame = pd.DataFrame(
        [{name: escape_spreadsheet_value(row.get(name, "")) for name in names} for row in examples],
        columns=names,
    )
    guide_frame = pd.DataFrame(
        [
            {
                "Column": column["name"],
                "Required": "Yes" if column.get("required") else "No",
                "Also accepted as": ", ".join(str(alias) for alias in column.get("aliases", [])),
                "What to enter": column.get("description", ""),
            }
            for column in columns
        ],
        columns=["Column", "Required", "Also accepted as", "What to enter"],
    )
    return example_frame, guide_frame


def template_csv_bytes(template: Mapping[str, Any]) -> bytes:
    """Headers and the example row; Excel opens the UTF-8 file correctly."""
    example_frame, _ = _template_frames(template)
    text: str = example_frame.to_csv(index=False)
    return text.encode("utf-8-sig")


def template_xlsx_bytes(template: Mapping[str, Any]) -> bytes:
    """A workbook with the template sheet and a sheet explaining every column."""
    example_frame, guide_frame = _template_frames(template)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        example_frame.to_excel(writer, sheet_name="Template", index=False)
        guide_frame.to_excel(writer, sheet_name="Columns", index=False)
    return output.getvalue()
