"""Streamlit planning workflow smoke tests."""

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from frontend import api_client
from frontend.streamlit_app import load_sample_payload

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeWorkflowClient:
    """Small fake API client used by Streamlit AppTest."""

    def get_health(self) -> api_client.HealthStatus:
        return api_client.HealthStatus(
            status="ok",
            service="backend",
            version="test",
            environment="test",
        )

    def validate_plan(self, payload: dict[str, Any]) -> api_client.WorkflowResponse:
        raw = {
            "validation": {
                "valid": True,
                "issues": [],
                "normalized_request": {"tasks": payload.get("tasks", [])},
            }
        }
        return api_client.WorkflowResponse(
            raw=raw,
            request_id="req-validate",
            validation=api_client.ValidationSummary.from_response(raw),
        )

    def solve_plan(self, payload: dict[str, Any]) -> api_client.WorkflowResponse:
        raw = {
            "validation": {
                "valid": True,
                "issues": [],
                "normalized_request": {"tasks": payload.get("tasks", [])},
            },
            "plan": {
                "plan_id": "plan-1",
                "status": "FEASIBLE",
                "scheduled_task_ids": ["TASK-PICK-001"],
                "unscheduled_task_ids": [],
                "diagnostics": [],
                "routes": [],
            },
        }
        return api_client.WorkflowResponse(
            raw=raw,
            request_id="req-solve",
            validation=api_client.ValidationSummary.from_response(raw),
            plan=api_client.PlanSummary.from_response(raw),
        )


def _button_disabled(app: AppTest, label: str) -> bool:
    for button in app.button:
        if button.label == label:
            return bool(button.disabled)
    raise AssertionError(f"Button not found: {label}")


def _click_button(app: AppTest, label: str) -> None:
    for index, button in enumerate(app.button):
        if button.label == label:
            app.button[index].click().run(timeout=8)
            return
    raise AssertionError(f"Button not found: {label}")


def test_streamlit_app_handles_unavailable_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:9")
    app = AppTest.from_file(str(PROJECT_ROOT / "frontend" / "streamlit_app.py"))

    app.run(timeout=8)

    assert not app.exception
    assert any("backend is unavailable" in warning.value.casefold() for warning in app.warning)


def test_streamlit_app_starts_with_m8_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_API_URL", "http://127.0.0.1:9")
    app = AppTest.from_file(str(PROJECT_ROOT / "frontend" / "streamlit_app.py"))

    app.run(timeout=8)

    assert not app.exception
    assert any("Manufacturing PO Route Optimizer" in title.value for title in app.title)
    assert any(button.label == "Validate payload" for button in app.button)
    assert any(button.label == "Compute matrix from locations" for button in app.button)
    assert any(button.label == "Solve route plan" for button in app.button)
    assert any(button.label == "Save scenario" for button in app.button)
    assert any(button.label == "Load saved scenario" for button in app.button)


def test_streamlit_workflow_unlocks_validate_matrix_and_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_client.BackendClient,
        "from_environment",
        classmethod(lambda cls: FakeWorkflowClient()),
    )
    app = AppTest.from_file(str(PROJECT_ROOT / "frontend" / "streamlit_app.py"))

    app.run(timeout=8)
    assert not app.exception
    assert _button_disabled(app, "Compute matrix from locations")
    assert _button_disabled(app, "Solve route plan")

    _click_button(app, "Validate payload")
    assert not _button_disabled(app, "Compute matrix from locations")
    assert _button_disabled(app, "Solve route plan")

    _click_button(app, "Use routing matrix from payload")
    assert not _button_disabled(app, "Solve route plan")

    _click_button(app, "Solve route plan")
    assert not app.exception
    assert any(
        metric.label == "Plan status" and metric.value == "FEASIBLE" for metric in app.metric
    )


def test_sample_loader_returns_clean_planning_payload() -> None:
    payload = load_sample_payload("A")

    assert payload["scenario_id"] == "A"
    assert "locations_ref" not in payload
    assert "matrix_ref" not in payload
    assert "expected" not in payload
    assert payload["locations"]
    assert payload["routing_matrix"]
