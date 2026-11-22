"""Refresh-safe drafts: the working copy kept on the backend (plan §11.3).

Streamlit forgets everything on a browser refresh. The current scenario ID is kept in
the page URL (``?scenario=``), and while the scenario has unsaved edits each change is
written to the backend's draft slot for that ID. After a refresh the app offers to
restore it. An explicit Save is still the only thing that changes the saved scenario.

A draft holds what a save would hold: the scenario, plus the active travel times when
they may be stored. Google travel times may not (decision D6), so only their identity
goes into ``meta``, and the app asks for them to be calculated again after a restore.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from frontend.state.fingerprints import plan_input_fingerprint, stable_fingerprint
from frontend.state.workspace import (
    Workspace,
    has_unsaved_edits,
    load_document,
    matrix_is_storable,
    save_document,
)

JsonObject = dict[str, Any]
DRAFT_META_VERSION = 1


@dataclass(frozen=True, slots=True)
class DraftRecord:
    """The draft this session last wrote: which ID, and what it contained."""

    scenario_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class DraftSync:
    """What to do with the backend's draft slots after a change."""

    put: tuple[str, JsonObject, JsonObject] | None = None  # (scenario ID, payload, meta)
    delete: tuple[str, ...] = ()
    record: DraftRecord | None = None


def scenario_key(workspace: Workspace) -> str:
    return str(workspace.scenario.get("scenario_id") or "").strip()


def plan_is_current(workspace: Workspace) -> bool:
    derived = workspace.derived
    return derived.plan is not None and derived.plan_input_fingerprint == plan_input_fingerprint(
        workspace.scenario, derived.matrix
    )


def draft_meta(workspace: Workspace) -> JsonObject:
    """Small context kept beside the scenario; never a Google matrix."""
    derived = workspace.derived
    meta: JsonObject = {
        "version": DRAFT_META_VERSION,
        "baseline_fingerprint": derived.baseline_fingerprint,
        "saved_scenario_id": derived.saved_scenario_id,
        "loaded_from": derived.loaded_from,
    }
    matrix = derived.matrix
    if matrix is not None and not matrix_is_storable(matrix):
        meta["dropped_matrix"] = {
            "source": matrix.get("source"),
            "created_at": matrix.get("created_at"),
            "routing_preference": matrix.get("routing_preference"),
            "location_count": len(matrix.get("location_ids") or []),
        }
    if plan_is_current(workspace) and derived.plan is not None:
        meta["plan_id"] = derived.plan.get("plan_id")
    return meta


def plan_draft_sync(workspace: Workspace, last: DraftRecord | None) -> DraftSync:
    """Write the draft when there are unsaved edits that changed; delete it otherwise.

    A draft whose scenario ID changed (the planner renamed the ID) moves: the old slot
    is deleted. Nothing is written for a scenario without an ID.
    """
    key = scenario_key(workspace)
    if not key or not has_unsaved_edits(workspace):
        if last is None:
            return DraftSync()
        return DraftSync(delete=(last.scenario_id,), record=None)
    payload = save_document(workspace)
    meta = draft_meta(workspace)
    fingerprint = stable_fingerprint({"payload": payload, "meta": meta})
    if last is not None and last.scenario_id == key and last.fingerprint == fingerprint:
        return DraftSync(record=last)
    stale = (last.scenario_id,) if last is not None and last.scenario_id != key else ()
    return DraftSync(
        put=(key, payload, meta),
        delete=stale,
        record=DraftRecord(scenario_id=key, fingerprint=fingerprint),
    )


def restore_workspace(draft: Mapping[str, Any]) -> Workspace:
    """The workspace a draft describes, with its edits still counted as unsaved."""
    payload = draft.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("The draft has no scenario.")
    raw_meta = draft.get("meta")
    meta: Mapping[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    scenario_id = str(payload.get("scenario_id") or "")
    workspace = load_document(payload, source=f"restored draft of {scenario_id}")
    baseline = meta.get("baseline_fingerprint")
    saved_id = meta.get("saved_scenario_id")
    loaded_from = meta.get("loaded_from")
    return replace(
        workspace,
        derived=replace(
            workspace.derived,
            baseline_fingerprint=str(baseline) if isinstance(baseline, str) else None,
            saved_scenario_id=str(saved_id) if isinstance(saved_id, str) else None,
            loaded_from=str(loaded_from) if isinstance(loaded_from, str) else None,
        ),
    )


def dropped_matrix(draft: Mapping[str, Any]) -> JsonObject | None:
    """Identity of Google travel times the draft could not keep, if any."""
    meta = draft.get("meta")
    if not isinstance(meta, dict):
        return None
    dropped = meta.get("dropped_matrix")
    return dropped if isinstance(dropped, dict) else None


def draft_plan_id(draft: Mapping[str, Any]) -> str | None:
    meta = draft.get("meta")
    plan_id = meta.get("plan_id") if isinstance(meta, dict) else None
    return str(plan_id) if isinstance(plan_id, str) and plan_id else None
