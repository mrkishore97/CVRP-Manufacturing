# Version 1.0 compatibility fixtures (frozen)

These files are a frozen copy of what a Version 1.0 user has: the planning JSON for
canonical scenarios A–F exactly as the Version 1.0 interface placed it in its JSON editor
(locations and the travel-time matrix embedded, fixture metadata removed), plus the results
`POST /api/v1/plans/solve` returned for each of them with no options.

They were taken from tag `v1.0.0` on 2026-11-16 (milestone V1.1-M0).

## Rules

- **Never edit, reformat, or regenerate these files.** `sample_data/canonical/` may evolve
  during Version 1.1; this folder must not.
- `manifest.json` records a SHA-256 of each JSON file's content (sorted keys, compact
  separators, so line endings and indentation do not matter). A test fails if any file changes.
- If a Version 1.1 change legitimately alters a default result, that is a behaviour change:
  record it in `project_plan_v1.1.md` and `build_log.md` first, then add a *new* expectation
  file rather than editing this one.

## Files

| File | Content |
|---|---|
| `scenario_a.json` … `scenario_f.json` | Version 1.0 planning payloads |
| `expected_default_results.json` | Status, scheduled and unscheduled tasks, truck-shifts used, total distance, and diagnostic codes for each payload (B: the validation error) |
| `manifest.json` | Content hashes |

## Tests that use them

`backend/tests/integration/test_v1_0_characterization.py` posts each payload to the solve
endpoint and requires the recorded results. These are the default-option characterization
tests of plan §14 (V1.1-M0) and run in every milestone.
