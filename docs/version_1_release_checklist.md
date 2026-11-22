# Version 1 release checklist

Release baseline: `v1.0.0`

> This is the record of the v1.0.0 release, kept as it was. Later releases have their own
> checklists, such as the [Version 1.1 release checklist](version_1_1_release_checklist.md),
> and are validated by `scripts/validate_release.py`. The `scripts/validate_m9_release.py`
> named below was retired in V1.1-M7; it remains in the `v1.0.0` tag.

Because this workspace is not currently a Git repository, the Version 1 baseline
is recorded by this checklist and the root `VERSION` file. If the project is
later imported into Git, tag the passing commit as `v1.0.0`.

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | App exists under `manufacturing_po_route_optimizer/`. | Pass | Project folder and M0 plan. |
| 2 | Original reference project is unchanged. | Pass | New project created beside reference zip/folder. |
| 3 | Streamlit communicates through HTTP only. | Pass | Boundary tests and frontend client. |
| 4 | Backend starts and solves without Streamlit. | Pass | API tests and smoke checks. |
| 5 | Planner can configure three trucks and mixed task types. | Pass | Canonical Scenario A and UI workflow. |
| 6 | Every task has normalized ready/due datetimes. | Pass | M2 validation and UI normalized preview. |
| 7 | Google road matrices can be calculated and cached. | Pass | M3 provider/cache tests and live smoke script. |
| 8 | Streamlit reruns do not make billable matrix calls. | Pass | Explicit matrix buttons and state tests. |
| 9 | Pickup-delivery precedence and capacity are enforced. | Pass | M4/M5 solver tests. |
| 10 | Truck shifts and multi-day availability are enforced. | Pass | M5 tests. |
| 11 | Feasible plans meet hard deadlines. | Pass | Solver validator and canonical tests. |
| 12 | Infeasible workloads identify affected POs and reasons. | Pass | Scenario C/D diagnostics. |
| 13 | Partial feasible plans are shown when diagnostics can produce one. | Pass | Scenario D. |
| 14 | Every returned route passes independent validation. | Pass | Optimization validator tests. |
| 15 | Results show stop order, ETA, departure, load, deadline, slack, distance, and duration. | Pass | Results table/export tests. |
| 16 | Route and infeasibility data can be exported. | Pass | M8 export tests. |
| 17 | Saved scenarios survive restart. | Pass | SQLite scenario persistence and smoke path. |
| 18 | Missing/invalid Google credentials and quota failures are controlled. | Pass | Routing provider error tests and troubleshooting guide. |
| 19 | Automated tests cover canonical scenarios. | Pass | M0/M2/M4/M5/M6 suites. |
| 20 | Setup, operation, limitations, and troubleshooting are documented. | Pass | README and M9 docs. |

## Release commands

Run all commands from the project root:

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/validate_m0.py
& .\.venv\Scripts\python.exe scripts/review_m2_payloads.py
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
& .\.venv\Scripts\python.exe scripts/validate_m9_release.py
& .\.venv\Scripts\python.exe -m pip check
```

Optional, when a Google key is configured:

```powershell
& .\.venv\Scripts\python.exe scripts/live_smoke_m3.py
```

## Release sign-off

- No critical or high-severity defects open: yes.
- No real credentials in committed configuration/docs/tests: yes.
- Known lower-severity limitations documented: yes.
- Backup/restore path documented: yes.
- Version baseline recorded: yes.
