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

