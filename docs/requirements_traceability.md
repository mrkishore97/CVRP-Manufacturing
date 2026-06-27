# Requirements and Acceptance Traceability

**Version:** 1.0  
**Date:** 2026-06-21

This matrix maps each Version 1 acceptance criterion in `project_plan.md` to its implementation milestone and planned evidence. Scenario letters refer to fixtures under `sample_data/canonical/`.

| ID | Requirement | Milestone(s) | Planned evidence |
|---|---|---|---|
| AC-01 | New app remains under its own project folder. | M1, M9 | Scaffold path check and clean release audit. |
| AC-02 | Reference project remains unchanged. | M0, M9 | M0 reference inventory and final source-control/workspace comparison. |
| AC-03 | Streamlit communicates with backend through HTTP only. | M1, M6, M7 | Dependency-boundary test and frontend API-client smoke test. |
| AC-04 | Backend solves without importing Streamlit. | M1, M4, M6 | Backend import test and API solver integration suite. |
| AC-05 | Planner can configure three trucks and mixed tasks. | M2, M4, M7 | Scenario A contract, solver, and UI tests. |
| AC-06 | Every task has normalized ready and due datetimes. | M2, M5 | Scenario H timezone/date-only tests plus validation preview test. |
| AC-07 | Google road matrices can be calculated and cached. | M3 | Mocked provider/cache tests and optional restricted-key smoke test. |
| AC-08 | Streamlit reruns do not cause billable matrix calls. | M3, M7 | Explicit-action and state-fingerprint test with HTTP call count assertion. |
| AC-09 | Pickup–delivery precedence and capacity are enforced. | M4 | Scenarios A, B, and E plus independent result validation. |
| AC-10 | Truck shifts and multi-day availability are enforced. | M5 | Scenario F and shift-overlap tests. |
| AC-11 | Feasible plans contain no task completed after deadline. | M5 | Scenarios A and C plus independent deadline validation. |
| AC-12 | Infeasible workloads identify affected POs and reasons. | M5, M7 | Scenarios B, C, D, and G in diagnostics and UI tests. |
| AC-13 | Partial feasible plan is shown when possible. | M5, M7 | Scenario D relaxed-solve and presentation tests. |
| AC-14 | Every route is independently validated. | M4, M5 | Corrupted-result rejection tests and successful result-validation metadata. |
| AC-15 | Results show truck, stops, ETA, load, deadline, slack, distance, and duration. | M5, M7 | Scenario A API snapshot and UI route-table test. |
| AC-16 | Route and infeasibility data can be exported. | M8 | Scenario A and D CSV/XLSX content tests. |
| AC-17 | Saved scenarios survive restart. | M6, M8 | Repository round-trip and process-restart manual check. |
| AC-18 | Missing/invalid Google credentials and quota failures are controlled. | M3, M7 | Scenario G mocked failures and frontend recovery messages. |
| AC-19 | Automated tests cover canonical scenarios. | M2–M9 | Manifest-driven A–H regression suite. |
| AC-20 | Setup, configuration, operation, limits, and troubleshooting are documented. | M1, M9 | Fresh-environment README acceptance check. |

## User requirement coverage

| User need | Design element | Fixture/evidence |
|---|---|---|
| Use the existing app as a reference. | `docs/reference_behavior_notes.md` documents retained/replaced behavior. | M0 review. |
| New Streamlit application in a subfolder. | Dedicated project root with `frontend/streamlit_app.py`. | AC-01, AC-03. |
| Backend separate from frontend. | FastAPI backend and HTTP-only Streamlit client. | AC-03, AC-04. |
| Google distance matrix. | Google Geocoding plus Routes Compute Route Matrix and cache. | AC-07, AC-08, AC-18, Scenario G. |
| Example fleet of three trucks. | General fleet model; three-truck canonical scenarios. | Scenario A and D, AC-05. |
| Pickup, drop, and pickup–drop rows. | Unified task model and internal pair expansion. | Scenario A and E, AC-05, AC-09. |
| Due date on every line. | Required normalized `due_at` and `due_event`. | Scenario A, C, H, AC-06, AC-11. |
| Message when deadline is not feasible. | Layered diagnostics and relaxed partial solve. | Scenario C and D, AC-12, AC-13. |

## Traceability rule

A requirement is not considered implemented until its planned evidence exists and passes. If a contract or requirement changes, update this matrix, the affected fixture, and the project plan before marking a milestone complete.
