"""Refresh-safe drafts (V1.1-M6): when they are written, moved, and restored."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from frontend.samples import load_sample_payload
from frontend.state.drafts import (
    DraftRecord,
    draft_plan_id,
    dropped_matrix,
    plan_draft_sync,
    restore_workspace,
)
from frontend.state.workspace import (
    Workspace,
    edit,
    has_unsaved_edits,
    load_document,
    mark_saved,
    record_matrix,
    record_plan,
    save_replaces_own_copy,
)


def _sample() -> Workspace:
    return load_document(load_sample_payload("A"), source="sample A")


def _renamed(workspace: Workspace, name: str) -> Workspace:
    scenario = deepcopy(workspace.scenario)
    scenario["name"] = name
    return edit(workspace, scenario)


def test_nothing_is_written_without_unsaved_edits() -> None:
    assert plan_draft_sync(_sample(), None).put is None
    assert plan_draft_sync(_sample(), None).delete == ()


def test_an_edit_writes_the_draft_once_per_change() -> None:
    edited = _renamed(_sample(), "Edited")
    first = plan_draft_sync(edited, None)
    assert first.put is not None
    scenario_id, payload, meta = first.put
    assert scenario_id == "A"
    assert payload["name"] == "Edited"
    assert payload["routing_matrix"]["location_ids"]  # sample travel times may be kept
    assert meta["saved_scenario_id"] is None
    assert meta["baseline_fingerprint"] == _sample().derived.baseline_fingerprint

    again = plan_draft_sync(edited, first.record)
    assert again.put is None and again.delete == ()
    assert again.record == first.record
    changed = plan_draft_sync(_renamed(edited, "Edited twice"), first.record)
    assert changed.put is not None


def test_changing_the_scenario_id_moves_the_draft() -> None:
    edited = _renamed(_sample(), "Edited")
    first = plan_draft_sync(edited, None)
    scenario = deepcopy(edited.scenario)
    scenario["scenario_id"] = "WEEK-26"
    moved = plan_draft_sync(edit(edited, scenario), first.record)
    assert moved.put is not None and moved.put[0] == "WEEK-26"
    assert moved.delete == ("A",)


def test_saving_or_undoing_the_edits_removes_the_draft() -> None:
    edited = _renamed(_sample(), "Edited")
    record = plan_draft_sync(edited, None).record
    saved = mark_saved(edited, saved_id="A")
    after_save = plan_draft_sync(saved, record)
    assert after_save.delete == ("A",) and after_save.put is None and after_save.record is None


def test_google_travel_times_are_not_kept_only_their_identity() -> None:
    workspace = _renamed(_sample(), "Edited")
    google = deepcopy(workspace.derived.matrix) or {}
    google["source"] = "google_routes"
    google["created_at"] = "2026-11-21T14:00:00Z"
    workspace = record_matrix(workspace, google, origin="calculated")
    sync = plan_draft_sync(workspace, None)
    assert sync.put is not None
    _, payload, meta = sync.put
    assert "routing_matrix" not in payload
    assert meta["dropped_matrix"] == {
        "source": "google_routes",
        "created_at": "2026-11-21T14:00:00Z",
        "routing_preference": google.get("routing_preference"),
        "location_count": len(google["location_ids"]),
    }
    assert dropped_matrix({"meta": meta}) == meta["dropped_matrix"]


def test_restoring_keeps_the_edits_unsaved_and_the_saved_copy_it_belongs_to() -> None:
    opened = load_document(load_sample_payload("A"), source="saved scenario A", saved_id="A")
    edited = _renamed(opened, "Edited")
    edited = record_plan(edited, plan={"plan_id": "PLAN-7"}, validation=None, request_id=None)
    sync = plan_draft_sync(edited, None)
    assert sync.put is not None
    _, payload, meta = sync.put
    assert meta["plan_id"] == "PLAN-7"
    draft = {"scenario_id": "A", "payload": payload, "meta": meta}

    restored = restore_workspace(draft)
    assert restored.scenario["name"] == "Edited"
    assert has_unsaved_edits(restored)
    assert restored.derived.saved_scenario_id == "A"
    assert save_replaces_own_copy(restored)
    assert restored.derived.matrix is not None  # sample travel times came back
    assert draft_plan_id(draft) == "PLAN-7"


def test_a_stale_plan_is_not_remembered_in_the_draft() -> None:
    edited = _renamed(_sample(), "Edited")
    with_plan = record_plan(edited, plan={"plan_id": "PLAN-1"}, validation=None, request_id=None)
    scenario = deepcopy(with_plan.scenario)
    scenario["tasks"] = scenario["tasks"][:-1]
    stale = edit(with_plan, scenario)
    sync = plan_draft_sync(stale, None)
    assert sync.put is not None and "plan_id" not in sync.put[2]


def test_a_draft_of_a_never_saved_scenario_restores_as_unsaved() -> None:
    edited = _renamed(_sample(), "Edited")
    sync = plan_draft_sync(edited, None)
    assert sync.put is not None
    _, payload, meta = sync.put
    restored = restore_workspace(
        {"payload": payload, "meta": {**meta, "baseline_fingerprint": None}}
    )
    assert has_unsaved_edits(restored)
    assert restored.derived.saved_scenario_id is None
    assert not save_replaces_own_copy(restored)


def test_save_replaces_only_the_copy_this_session_opened_or_saved() -> None:
    workspace = _sample()
    assert not save_replaces_own_copy(workspace)
    saved = mark_saved(workspace, saved_id="A")
    assert save_replaces_own_copy(saved)
    renamed = deepcopy(saved.scenario)
    renamed["scenario_id"] = "OTHER"
    assert not save_replaces_own_copy(replace(saved, scenario=renamed))
    assert DraftRecord("A", "x") != DraftRecord("A", "y")
