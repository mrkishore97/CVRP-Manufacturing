"""V1.1-M3 location import contract: header mapping and row checks (plan §9.5)."""

from __future__ import annotations

from backend.app.domain.enums import ValidationCode, ValidationSeverity
from backend.app.domain.location_import import (
    LOCATION_HEADER_MAP,
    ImportedLocation,
    preview_location_import,
)


def _codes(preview_rows: list[dict[str, object]]) -> list[tuple[str, int | None, str]]:
    preview = preview_location_import(preview_rows)
    return [(issue.code.value, issue.row_number, issue.severity.value) for issue in preview.issues]


def test_planner_headers_map_to_name_address_and_id() -> None:
    preview = preview_location_import(
        [
            {"Supplier": "Acme Steel", "Street Address": "1 Steel Rd, Hamilton", "Site ID": "ACME"},
            {"Supplier": "Bolt Co", "Street Address": "2 Bolt Ave, Brampton", "Site ID": None},
        ]
    )

    assert preview.valid
    assert preview.column_mapping == {
        "Supplier": "name",
        "Street Address": "address",
        "Site ID": "location_id",
    }
    assert preview.rows == (
        ImportedLocation(2, "Acme Steel", "1 Steel Rd, Hamilton", "ACME"),
        ImportedLocation(3, "Bolt Co", "2 Bolt Ave, Brampton", None),
    )
    assert preview.issues == ()


def test_every_alias_is_unambiguous() -> None:
    assert set(LOCATION_HEADER_MAP.values()) == {"name", "address", "location_id"}
    assert LOCATION_HEADER_MAP["customer"] == "name"
    assert LOCATION_HEADER_MAP["full_address"] == "address"


def test_a_missing_required_column_stops_the_import() -> None:
    preview = preview_location_import([{"Name": "Acme", "City": "Hamilton"}])

    assert not preview.valid
    assert preview.rows == ()
    assert preview.unknown_columns == ("City",)
    codes = {(issue.code, issue.field) for issue in preview.issues}
    assert (ValidationCode.MISSING_REQUIRED_FIELD, "address") in codes
    assert (ValidationCode.UNKNOWN_COLUMN, "City") in codes


def test_two_columns_meaning_the_same_field_are_refused() -> None:
    assert ("DUPLICATE_COLUMN", None, "ERROR") in _codes(
        [{"Name": "A", "Company": "B", "Address": "1 A St"}]
    )


def test_row_problems_are_reported_with_spreadsheet_row_numbers() -> None:
    codes = _codes(
        [
            {"name": "Good", "address": "1 Good St", "location_id": "GOOD"},
            {"name": "", "address": "2 No Name St", "location_id": None},
            {"name": "Bad ID", "address": "3 Bad St", "location_id": "bad id"},
            {"name": "Again", "address": "4 Again St", "location_id": "GOOD"},
            {"name": "good", "address": "5 Same Name St", "location_id": None},
            {"name": "Long", "address": "x" * 501, "location_id": None},
        ]
    )

    assert ("MISSING_REQUIRED_FIELD", 3, "ERROR") in codes
    assert ("INVALID_VALUE", 4, "ERROR") in codes
    assert ("DUPLICATE_LOCATION_ID", 5, "ERROR") in codes
    assert ("INVALID_VALUE", 6, "WARNING") in codes  # same name as row 2: imported anyway
    assert ("INVALID_VALUE", 7, "ERROR") in codes


def test_blank_rows_are_skipped_and_spreadsheet_numbers_lose_their_decimal() -> None:
    preview = preview_location_import(
        [
            {"name": "Depot", "address": "  10   Depot   Rd ", "location_id": 42.0},
            {"name": None, "address": "", "location_id": None},
        ]
    )

    assert preview.valid
    assert preview.rows == (ImportedLocation(2, "Depot", "10 Depot Rd", "42"),)


def test_a_file_without_location_rows_is_refused() -> None:
    preview = preview_location_import([{"name": None, "address": None}])

    assert not preview.valid
    assert [issue.severity for issue in preview.issues] == [ValidationSeverity.ERROR]
