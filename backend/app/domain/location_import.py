"""Location spreadsheet import contract: a name and an address, optionally an ID.

The frontend reads the CSV/XLSX file and sends its rows keyed by the original headers;
this module maps the headers, checks every row, and returns canonical rows with
row-level issues (plan §9.5). Imported locations carry no coordinates: they are added
as "not resolved yet" and resolved like any other address.

Row numbers are spreadsheet rows: the header is row 1, so the first data row is row 2.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.app.domain.enums import ValidationCode, ValidationSeverity
from backend.app.domain.import_contract import ImportColumnSpec, normalize_header
from backend.app.domain.results import ValidationIssue

MAX_NAME_LENGTH = 200
MAX_ADDRESS_LENGTH = 500
MAX_ID_LENGTH = 120
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
FIRST_DATA_ROW = 2

LOCATION_IMPORT_COLUMNS: tuple[ImportColumnSpec, ...] = (
    ImportColumnSpec(
        "name",
        True,
        (
            "location name",
            "location",
            "site",
            "site name",
            "company",
            "company name",
            "supplier",
            "customer",
        ),
        "How planners know the place, for example the supplier's name.",
    ),
    ImportColumnSpec(
        "address",
        True,
        ("street address", "full address", "location address", "site address"),
        "Street address, postal code, or Plus Code; resolved by the backend.",
    ),
    ImportColumnSpec(
        "location_id",
        False,
        ("id", "location id", "site id", "location code", "code"),
        "Optional identifier; suggested from the name when omitted.",
    ),
)


def _build_header_map() -> dict[str, str]:
    header_map: dict[str, str] = {}
    for specification in LOCATION_IMPORT_COLUMNS:
        for header in (specification.canonical_name, *specification.aliases):
            normalized = normalize_header(header)
            existing = header_map.get(normalized)
            if existing is not None and existing != specification.canonical_name:
                raise RuntimeError(f"location import alias collision: {header}")
            header_map[normalized] = specification.canonical_name
    return header_map


LOCATION_HEADER_MAP = _build_header_map()
REQUIRED_LOCATION_COLUMNS = tuple(
    column.canonical_name for column in LOCATION_IMPORT_COLUMNS if column.required
)


@dataclass(frozen=True, slots=True)
class ImportedLocation:
    """One canonical location row from the file."""

    row_number: int
    name: str
    address: str
    location_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocationImportPreview:
    """Mapped rows, row-level issues, and how the headers were read."""

    rows: tuple[ImportedLocation, ...]
    issues: tuple[ValidationIssue, ...]
    column_mapping: Mapping[str, str]
    unknown_columns: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not any(issue.severity is ValidationSeverity.ERROR for issue in self.issues)


def _issue(
    code: ValidationCode,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    row_number: int | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity, code=code, message=message, row_number=row_number, field=field
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


def preview_location_import(raw_rows: Sequence[Mapping[str, Any]]) -> LocationImportPreview:
    """Map headers and check every row; nothing is applied here."""
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
        canonical = LOCATION_HEADER_MAP.get(normalize_header(header))
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

    missing = [column for column in REQUIRED_LOCATION_COLUMNS if column not in source_for]
    for column in missing:
        issues.append(
            _issue(
                ValidationCode.MISSING_REQUIRED_FIELD,
                f"The file needs a '{column}' column.",
                field=column,
            )
        )
    if missing:
        return LocationImportPreview(
            rows=(), issues=tuple(issues), column_mapping=mapping, unknown_columns=tuple(unknown)
        )

    rows: list[ImportedLocation] = []
    rows_by_id: dict[str, int] = {}
    rows_by_name: dict[str, int] = {}
    for offset, raw_row in enumerate(raw_rows):
        row_number = offset + FIRST_DATA_ROW
        values = {canonical: _text(raw_row.get(source)) for source, canonical in mapping.items()}
        if not any(values.values()):
            continue
        row_issues = _row_issues(values, row_number)
        location_id = values.get("location_id") or None
        if location_id is not None and location_id in rows_by_id:
            row_issues.append(
                _issue(
                    ValidationCode.DUPLICATE_LOCATION_ID,
                    f"Row {row_number} repeats location ID {location_id} from row "
                    f"{rows_by_id[location_id]}.",
                    row_number=row_number,
                    field="location_id",
                )
            )
        name_key = values["name"].casefold()
        if name_key and name_key in rows_by_name:
            row_issues.append(
                _issue(
                    ValidationCode.INVALID_VALUE,
                    f"Row {row_number} has the same name as row {rows_by_name[name_key]}; "
                    "both are imported.",
                    severity=ValidationSeverity.WARNING,
                    row_number=row_number,
                    field="name",
                )
            )
        issues.extend(row_issues)
        if location_id is not None:
            rows_by_id.setdefault(location_id, row_number)
        if name_key:
            rows_by_name.setdefault(name_key, row_number)
        if not any(issue.severity is ValidationSeverity.ERROR for issue in row_issues):
            rows.append(
                ImportedLocation(
                    row_number=row_number,
                    name=values["name"],
                    address=values["address"],
                    location_id=location_id,
                )
            )
    if not rows and not any(issue.severity is ValidationSeverity.ERROR for issue in issues):
        issues.append(
            _issue(ValidationCode.MISSING_REQUIRED_FIELD, "The file has no location rows.")
        )
    return LocationImportPreview(
        rows=tuple(rows),
        issues=tuple(issues),
        column_mapping=mapping,
        unknown_columns=tuple(unknown),
    )


def _row_issues(values: Mapping[str, str], row_number: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for column in REQUIRED_LOCATION_COLUMNS:
        if not values.get(column):
            issues.append(
                _issue(
                    ValidationCode.MISSING_REQUIRED_FIELD,
                    f"Row {row_number} has no {column}.",
                    row_number=row_number,
                    field=column,
                )
            )
    if len(values.get("name", "")) > MAX_NAME_LENGTH:
        issues.append(
            _issue(
                ValidationCode.INVALID_VALUE,
                f"Row {row_number}: the name is longer than {MAX_NAME_LENGTH} characters.",
                row_number=row_number,
                field="name",
            )
        )
    if len(values.get("address", "")) > MAX_ADDRESS_LENGTH:
        issues.append(
            _issue(
                ValidationCode.INVALID_VALUE,
                f"Row {row_number}: the address is longer than {MAX_ADDRESS_LENGTH} characters.",
                row_number=row_number,
                field="address",
            )
        )
    location_id = values.get("location_id")
    if location_id and (len(location_id) > MAX_ID_LENGTH or not _ID_PATTERN.fullmatch(location_id)):
        issues.append(
            _issue(
                ValidationCode.INVALID_VALUE,
                f"Row {row_number}: location ID '{location_id}' may use only letters, "
                "digits, '.', '_', ':' and '-', must start with a letter or digit, and "
                f"be at most {MAX_ID_LENGTH} characters.",
                row_number=row_number,
                field="location_id",
            )
        )
    return issues
