"""Automatic validation: free, so it runs whenever the scenario changes (principle 9).

It runs at most once per distinct scenario. A failed attempt (backend down) is
remembered and not retried on every rerun; it is retried when the scenario changes or
the planner presses Revalidate.
"""

from __future__ import annotations

from frontend.api_client import BackendClient, BackendClientError
from frontend.state.workspace import (
    record_validation,
    record_validation_failure,
    validation_payload,
    validation_payload_fingerprint,
)
from frontend.views.components import get_workspace, set_workspace


def run_validation(client: BackendClient, *, force: bool = False) -> None:
    workspace = get_workspace()
    fingerprint = validation_payload_fingerprint(workspace)
    derived = workspace.derived
    if not force and fingerprint in (
        derived.validation_fingerprint,
        derived.validation_attempt_fingerprint,
    ):
        return
    try:
        response = client.validate_plan(validation_payload(workspace))
    except BackendClientError as exc:
        set_workspace(
            record_validation_failure(workspace, payload_fingerprint=fingerprint, message=str(exc))
        )
        return
    validation = response.raw.get("validation")
    if not isinstance(validation, dict):
        set_workspace(
            record_validation_failure(
                workspace,
                payload_fingerprint=fingerprint,
                message="The backend validation response had no validation object.",
            )
        )
        return
    set_workspace(
        record_validation(
            workspace,
            payload_fingerprint=fingerprint,
            validation=validation,
            request_id=response.request_id,
        )
    )
