# Task CSV/XLSX Import Contract

**Version:** 1.0  
**Milestone:** M2

CSV and XLSX adapters will pass row dictionaries through the same format-neutral mapping contract. File-reading libraries are deliberately outside the domain layer.

## Canonical columns

| Column | Required | Rule |
|---|---:|---|
| `task_id` | Yes | Unique movement-line ID using letters, numbers, `.`, `_`, `:`, or `-`. |
| `po_number` | Yes | Business PO reference. Multiple task lines may share one PO; later rows receive a warning. |
| `task_type` | Yes | `PICKUP`, `DROP`, or `PICKUP_DROP`. |
| `origin_location_id` | Yes | Existing location ID. Pickup starts away from plant; drop starts at plant. |
| `destination_location_id` | Yes | Existing location ID. Pickup ends at plant; drop ends away from plant. |
| `quantity` | Yes | Positive number with at most three decimal places. Never enter a negative demand. |
| `ready_at` | Yes | ISO datetime. A date-only value uses the earliest shift start that day and produces a warning. |
| `due_at` | Yes | ISO datetime. A date-only value uses the latest shift end that day and produces a warning. |
| `due_event` | No | `PICKUP_COMPLETE` or `DELIVERY_COMPLETE`; defaults to delivery completion. |
| `pickup_service_minutes` | No | Nonnegative integer, default `0`. |
| `delivery_service_minutes` | No | Nonnegative integer, default `0`. |
| `priority` | No | Integer `1` through `5`, default `1`. |
| `required_vehicle_tags` | No | Comma-separated compatibility tags. |
| `notes` | No | Optional planner notes. |

Headers are case-insensitive. Spaces, hyphens, and underscores normalize consistently. Human-friendly aliases such as `PO Number`, `Pickup Location`, `Drop Location`, `Qty`, `Ready Date`, and `Deadline` are accepted.

If two source columns map to one canonical field—for example `quantity` and `qty` in the same file—the row is rejected as ambiguous. Unknown columns are ignored with a row-level warning.

## Datetime rules

- The selected plant IANA timezone controls naive values.
- Aware values are converted to UTC internally.
- Ambiguous and nonexistent daylight-saving times are rejected.
- Normalized local and UTC timestamps are available for confirmation.
- Deadline enforcement applies to completion after service, not arrival alone.

## Quantity policy

User values are always positive. The backend expands each task into a pickup node with positive load and a delivery node with equal negative load. This internal sign convention is never required in a CSV/XLSX file.


## Spreadsheet import in the app (Version 1.1, M4)

The column table above is the only definition of task columns and aliases. The app has no copy of its own. It sends each file's rows to the backend and applies the result.

### Preview endpoint

`POST /api/v1/imports/tasks/preview` receives:

- the rows, keyed by the file's own headers;
- the scenario's locations (ID and name) and plant;
- the plant timezone;
- the default pickup and delivery service minutes.

It returns canonical task rows and row-level issues. Row numbers are spreadsheet rows: the header is row 1. Nothing is stored.

A spreadsheet may leave out three things that JSON requires:

| Column | In a spreadsheet |
|---|---|
| `task_id` | May be empty. The app numbers new tasks `TASK-NNNN`. |
| `origin_location_id` | Location ID or exact name. May be empty for a drop, which starts at the plant. |
| `destination_location_id` | Location ID or exact name. May be empty for a pickup, which ends at the plant. |

Other rules:

- **Location names.** They match regardless of case and repeated spaces. A name shared by two locations is an error (`AMBIGUOUS_LOCATION`); use the ID instead. An unknown name or ID is `UNKNOWN_LOCATION`.
- **Priority.** `1`–`5` or the label: Routine, Normal, Important, High, Critical.
- **Service minutes.** Empty cells take the scenario's defaults.
- **Times.** Plant-local values such as `2026-12-07 08:00` are stored as wall-clock text. A daylight-saving gap or overlap is a row error. A ready time after the due time is a row error too.
- **Errors block the import.** Every error blocks it; warnings, such as an unknown column or a repeated PO number, do not.

### Applying

The app applies a valid preview all-or-nothing, in one of three modes:

| Mode | Effect |
|---|---|
| Append | Every row is a new task; an ID that already exists is refused. |
| Update | Rows whose ID matches replace that task in place; the others are added. |
| Replace | The imported rows become the whole task list. |

If any row would break the scenario, nothing changes. Times outside the planning period extend it to whole days.

### Templates

`GET /api/v1/imports/templates/tasks` and `/templates/locations` return the columns, whether each is required, its aliases, a description, and one example row. The app offers them as CSV, and as Excel with a second sheet explaining every column.
