"""In-memory stand-in for ``BackendClient`` used by the ``AppTest`` page tests.

It records every call, so tests can assert exactly how many address lookups and
travel-time calculations a sequence of clicks, reruns, and page visits caused.
Address resolution answers from ``resolutions`` (address → status and reasons) and
otherwise returns a rooftop match with deterministic coordinates near Toronto.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from frontend import api_client
from frontend.state.readiness import geocode_fingerprint
from frontend.state.scenario_state import normalize_address

NOW_TEXT = "2026-11-18T12:00:00Z"
REVIEW_MESSAGES = {
    "PARTIAL_MATCH": "Google matched only part of this address. Check the matched address.",
    "LOW_PRECISION": "Google found only an approximate area for this address.",
    "MULTIPLE_MATCHES": "Google found several places for this address. Pick the right one.",
    "FAR_FROM_PLANT": "This match is far from the plant. Check the city and country.",
}


def coordinates_for(address: str) -> tuple[float, float]:
    """Deterministic coordinates within about 50 km of Toronto."""
    digest = hashlib.sha256(normalize_address(address).encode()).digest()
    return 43.65 + digest[0] / 600, -79.38 + digest[1] / 600


class FakeBackend:
    """Records every call; answers like the real backend's contracts."""

    def __init__(self) -> None:
        self.valid = True
        self.google_configured = False
        self.matrix_confirm_elements = 400
        self.matrix_source = "fake"
        self.cache_enabled = True
        self.resolutions: dict[str, dict[str, Any]] = {}
        self.validate_calls: list[dict[str, Any]] = []
        self.solve_calls: list[dict[str, Any]] = []
        self.matrix_calls: list[list[dict[str, Any]]] = []
        self.matrix_options: list[dict[str, Any] | None] = []
        self.estimate_calls: list[list[dict[str, Any]]] = []
        self.resolve_calls: list[list[dict[str, Any]]] = []
        self.resolve_requests: list[dict[str, Any]] = []
        self.import_calls: list[list[dict[str, Any]]] = []
        self.task_import_calls: list[list[dict[str, Any]]] = []
        self.extra_issues: list[dict[str, Any]] = []
        self.solve_time_limits: list[int | None] = []
        self.template_calls: list[str] = []
        self.list_calls = 0
        self.saved: dict[str, dict[str, Any]] = {}

    # --- configuration helpers -------------------------------------------------

    def answer(
        self,
        address: str,
        status: str,
        *,
        reasons: tuple[str, ...] = (),
        formatted_address: str | None = None,
        alternatives: tuple[str, ...] = (),
        place_id: str | None = None,
    ) -> None:
        """Configure the answer for one address (normalised like the backend)."""
        self.resolutions[normalize_address(address)] = {
            "status": status,
            "reasons": reasons,
            "formatted_address": formatted_address,
            "alternatives": alternatives,
            "place_id": place_id,
        }

    @property
    def provider_calls(self) -> int:
        """Billable calls: one per address sent for resolution, plus each matrix."""
        return sum(len(call) for call in self.resolve_calls) + len(self.matrix_calls)

    # --- BackendClient surface -------------------------------------------------

    def get_health(self) -> api_client.HealthStatus:
        return api_client.HealthStatus(
            status="ok", service="backend", version="test", environment="test"
        )

    def get_config(self) -> api_client.BackendConfig:
        return api_client.BackendConfig(
            default_timezone="America/Toronto",
            google_maps_configured=self.google_configured,
            geocode_region_code="ca",
            geocode_cache_ttl_seconds=2_592_000,
            geocode_max_plant_distance_km=500.0,
            matrix_confirm_elements=self.matrix_confirm_elements,
            solver_time_limit_seconds=10,
            limits={},
            solver_max_time_limit_seconds=120,
        )

    def _validation(self, payload: dict[str, Any]) -> dict[str, Any]:
        problems = []
        if not payload.get("vehicles"):
            problems.append({"severity": "ERROR", "code": "INVALID_VALUE", "message": "No trucks."})
        if payload.get("scenario_id") == "INVALID-SCENARIO" or not self.valid:
            problems.append(
                {"severity": "ERROR", "code": "CAPACITY_EXCEEDED", "message": "Too heavy."}
            )
        problems.extend(deepcopy(self.extra_issues))
        return {
            "valid": not any(problem["severity"] == "ERROR" for problem in problems),
            "issues": problems,
            "normalized_request": None
            if any(problem["severity"] == "ERROR" for problem in problems)
            else {"tasks": payload.get("tasks", [])},
        }

    def validate_plan(self, payload: dict[str, Any]) -> api_client.WorkflowResponse:
        self.validate_calls.append(deepcopy(payload))
        raw = {"validation": self._validation(payload)}
        return api_client.WorkflowResponse(raw=raw, request_id="req-validate")

    def solve_plan(
        self, payload: dict[str, Any], *, time_limit_seconds: int | None = None
    ) -> api_client.WorkflowResponse:
        self.solve_calls.append(deepcopy(payload))
        self.solve_time_limits.append(time_limit_seconds)
        raw = {
            "validation": self._validation(payload),
            "plan": {
                "plan_id": f"PLAN-{len(self.solve_calls)}",
                "status": "FEASIBLE",
                "optimization_options": deepcopy(payload.get("optimization_options")),
                "scheduled_task_ids": [task["task_id"] for task in payload.get("tasks", [])],
                "unscheduled_task_ids": [],
                "diagnostics": [],
                "routes": [],
            },
        }
        return api_client.WorkflowResponse(raw=raw, request_id="req-solve")

    def resolve_locations(
        self,
        locations: list[dict[str, Any]],
        *,
        plant_location_id: str | None = None,
        plant_coordinates: dict[str, float] | None = None,
        region_code: str | None = None,
        force_refresh: bool = False,
    ) -> api_client.ApiResult:
        self.resolve_calls.append(deepcopy(locations))
        self.resolve_requests.append(
            {
                "plant_location_id": plant_location_id,
                "plant_coordinates": plant_coordinates,
                "region_code": region_code,
                "force_refresh": force_refresh,
            }
        )
        results = [self._resolve_one(row) for row in locations]
        summary = {
            "resolved": sum(result["status"] == "RESOLVED" for result in results),
            "needs_review": sum(result["status"] == "NEEDS_REVIEW" for result in results),
            "failed": sum(result["status"] == "FAILED" for result in results),
            "cache_hits": 0,
            "provider_calls": len(results),
            "unique_addresses": len({normalize_address(row["address"]) for row in locations}),
            "plant_distance_checked": True,
        }
        return api_client.ApiResult(
            payload={"request_id": "req-resolve", "results": results, "summary": summary}
        )

    def _resolve_one(self, row: dict[str, Any]) -> dict[str, Any]:
        address = str(row["address"])
        configured = self.resolutions.get(normalize_address(address), {})
        status = str(configured.get("status", "RESOLVED"))
        reasons = tuple(configured.get("reasons", ()))
        place_id = configured.get("place_id") or f"place-{normalize_address(address)[:24]}"
        if status == "FAILED":
            return {
                "location_id": row["location_id"],
                "status": "FAILED",
                "reason_code": "ADDRESS_NOT_FOUND",
                "reason_codes": ["ADDRESS_NOT_FOUND"],
                "message": "Google did not find this address. Correct it and try again.",
                "formatted_address": None,
                "alternatives": [],
                "place_id": None,
                "latitude": None,
                "longitude": None,
                "location_type": None,
                "partial_match": None,
                "geocode_source_fingerprint": None,
                "geocoded_at": None,
                "geocode_confirmed": False,
                "duplicate_of": [],
                "distance_from_plant_km": None,
                "cache_hit": False,
            }
        confirmed = row.get("confirmed_place_id") == place_id
        if status == "NEEDS_REVIEW" and confirmed:
            status = "RESOLVED"
        latitude, longitude = coordinates_for(address)
        message = REVIEW_MESSAGES.get(reasons[0], "Check the match.") if reasons else "Resolved."
        return {
            "location_id": row["location_id"],
            "status": status,
            "reason_code": reasons[0] if reasons else None,
            "reason_codes": list(reasons),
            "message": message,
            "formatted_address": configured.get("formatted_address") or f"{address}, Canada",
            "alternatives": list(configured.get("alternatives", ())),
            "place_id": place_id,
            "latitude": latitude,
            "longitude": longitude,
            "location_type": "ROOFTOP" if not reasons else "APPROXIMATE",
            "partial_match": "PARTIAL_MATCH" in reasons,
            "geocode_source_fingerprint": geocode_fingerprint(address, "ca"),
            "geocoded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geocode_confirmed": confirmed,
            "duplicate_of": [],
            "distance_from_plant_km": 512.0 if "FAR_FROM_PLANT" in reasons else 12.0,
            "cache_hit": False,
        }

    def estimate_matrix(
        self,
        locations: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
    ) -> api_client.ApiResult:
        del options
        self.estimate_calls.append(deepcopy(locations))
        size = len(locations)
        elements = size * size
        return api_client.ApiResult(
            payload={
                "request_id": "req-estimate",
                "location_count": size,
                "element_count": elements,
                "request_count": 1,
                "maximum_elements_per_request": 625,
                "cache_hit": False,
                "cache_key": "matrix:test",
                "billable_element_count": elements,
                "billable_request_count": 1,
                "confirmation_threshold_elements": self.matrix_confirm_elements,
                "confirmation_required": elements > self.matrix_confirm_elements,
                "cache_enabled": self.cache_enabled,
            }
        )

    def compute_matrix(
        self,
        locations: list[dict[str, Any]],
        *,
        force_refresh: bool = False,
        options: dict[str, Any] | None = None,
    ) -> api_client.ApiResult:
        del force_refresh
        self.matrix_calls.append(deepcopy(locations))
        self.matrix_options.append(deepcopy(options))
        size = len(locations)
        matrix = {
            "location_ids": [location["location_id"] for location in locations],
            "distance_meters": [[0 if r == c else 1_000 for c in range(size)] for r in range(size)],
            "duration_seconds": [[0 if r == c else 60 for c in range(size)] for r in range(size)],
            "source": self.matrix_source,
            "created_at": NOW_TEXT,
        }
        return api_client.ApiResult(
            payload={"matrix": matrix, "cache_hit": False, "cache_enabled": self.cache_enabled}
        )

    def save_scenario(self, payload: dict[str, Any]) -> api_client.ApiResult:
        stored = deepcopy(payload)
        dropped = False
        matrix = stored.get("routing_matrix")
        if isinstance(matrix, dict) and matrix.get("source") == "google_routes":
            del stored["routing_matrix"]
            dropped = True
        self.saved[str(payload["scenario_id"])] = stored
        return api_client.ApiResult(
            payload={"scenario_id": payload["scenario_id"], "routing_matrix_dropped": dropped}
        )

    def load_scenario(self, scenario_id: str) -> api_client.ApiResult:
        if scenario_id not in self.saved:
            raise api_client.BackendApiError(
                status_code=404, code="SCENARIO_NOT_FOUND", message="Not found.", request_id="r"
            )
        return api_client.ApiResult(
            payload={"scenario_id": scenario_id, "payload": deepcopy(self.saved[scenario_id])}
        )

    def list_scenarios(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [
            {
                "scenario_id": scenario_id,
                "name": payload.get("name"),
                "created_at": NOW_TEXT,
                "updated_at": NOW_TEXT,
                "location_count": len(payload.get("locations", [])),
                "vehicle_count": len(payload.get("vehicles", [])),
                "shift_count": len(payload.get("vehicle_shifts", [])),
                "task_count": len(payload.get("tasks", [])),
            }
            for scenario_id, payload in self.saved.items()
        ]

    def preview_location_import(self, rows: list[dict[str, Any]]) -> api_client.ApiResult:
        self.import_calls.append(deepcopy(rows))
        mapped = []
        issues = []
        for offset, row in enumerate(rows):
            lowered = {str(key).strip().casefold(): value for key, value in row.items()}
            name, address = lowered.get("name"), lowered.get("address")
            if not name or not address:
                issues.append(
                    {
                        "severity": "ERROR",
                        "code": "MISSING_REQUIRED_FIELD",
                        "row_number": offset + 2,
                        "field": "name" if not name else "address",
                        "message": "Missing value.",
                    }
                )
                continue
            mapped.append(
                {
                    "row_number": offset + 2,
                    "name": str(name),
                    "address": str(address),
                    "location_id": lowered.get("location_id") or None,
                }
            )
        return api_client.ApiResult(
            payload={
                "request_id": "req-import",
                "valid": not issues,
                "rows": mapped,
                "issues": issues,
                "column_mapping": {},
                "unknown_columns": [],
            }
        )

    def import_template(self, kind: str) -> api_client.ApiResult:
        self.template_calls.append(kind)
        columns = {
            "tasks": ["task_id", "po_number", "task_type", "origin_location_id", "quantity"],
            "locations": ["name", "address", "location_id"],
        }[kind]
        return api_client.ApiResult(
            payload={
                "request_id": "req-template",
                "kind": kind,
                "columns": [
                    {"name": name, "required": name != "task_id", "aliases": [], "description": ""}
                    for name in columns
                ],
                "example_rows": [{name: "" for name in columns}],
            }
        )

    def preview_task_import(
        self,
        rows: list[dict[str, Any]],
        *,
        locations: list[dict[str, str]],
        plant_location_id: str,
        timezone: str | None = None,
        default_pickup_service_minutes: int = 0,
        default_delivery_service_minutes: int = 0,
    ) -> api_client.ApiResult:
        """A small stand-in for the backend contract: canonical headers, IDs or names."""
        del timezone
        self.task_import_calls.append(deepcopy(rows))
        by_key = {
            location["location_id"].casefold(): location["location_id"] for location in locations
        }
        by_key.update(
            {location["name"].casefold(): location["location_id"] for location in locations}
        )
        mapped: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for offset, row in enumerate(rows):
            row_number = offset + 2
            kind = str(row.get("task_type", "")).upper()
            ends = {}
            for field, plant_end in (
                ("origin_location_id", kind == "DROP"),
                ("destination_location_id", kind == "PICKUP"),
            ):
                cell = str(row.get(field) or "").strip()
                if not cell and plant_end:
                    ends[field] = plant_location_id
                elif cell.casefold() in by_key:
                    ends[field] = by_key[cell.casefold()]
                else:
                    issues.append(
                        {
                            "severity": "ERROR",
                            "code": "UNKNOWN_LOCATION",
                            "row_number": row_number,
                            "field": field,
                            "message": f"No location '{cell}'.",
                        }
                    )
            if len(ends) < 2:
                continue
            mapped.append(
                {
                    "row_number": row_number,
                    "task_id": row.get("task_id") or None,
                    "po_number": str(row["po_number"]),
                    "task_type": kind,
                    **ends,
                    "quantity": float(row["quantity"]),
                    "ready_at": str(row["ready_at"]).replace(" ", "T"),
                    "due_at": str(row["due_at"]).replace(" ", "T"),
                    "due_event": "DELIVERY_COMPLETE",
                    "pickup_service_minutes": default_pickup_service_minutes,
                    "delivery_service_minutes": default_delivery_service_minutes,
                    "priority": int(row.get("priority") or 1),
                    "required_vehicle_tags": [],
                    "notes": None,
                }
            )
        return api_client.ApiResult(
            payload={
                "request_id": "req-task-import",
                "valid": not issues,
                "rows": mapped,
                "issues": issues,
                "column_mapping": {},
                "unknown_columns": [],
            }
        )


def install(monkeypatch: pytest.MonkeyPatch) -> FakeBackend:
    """Make ``BackendClient.from_environment`` return a new ``FakeBackend``."""
    fake = FakeBackend()
    monkeypatch.setattr(api_client.BackendClient, "from_environment", classmethod(lambda cls: fake))
    return fake
