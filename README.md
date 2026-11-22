# Manufacturing PO Route Optimizer

A deadline-aware route-planning application for manufacturing pickup, drop, and pickup–drop work. The project uses a standalone FastAPI backend and a replaceable Streamlit frontend.

## Current status

Version 1 / M9 is complete: the app has the separated FastAPI backend, replaceable Streamlit frontend, Google geocoding/Routes matrix integration, deadline-aware solver, scenario persistence, maps, exports, operational documentation, and release-hardening checks.

Version 1.1 is in progress on branch `v1.1` (plan: `project_plan_v1.1.md`). The app now has pages in the sidebar rather than tabs:

- **Build:** Scenario, Locations, Fleet, Tasks.
- **Plan:** Review, Travel times, Optimize, Results.
- **Advanced:** JSON.

Locations need only a name and an address; nobody types coordinates.

1. Press **Resolve addresses**. The backend looks them up through Google and sends only new or changed addresses.
2. Confirm or correct doubtful matches.
3. Calculate travel times. The cost estimate is shown first.

The address-only sample (`sample_data/v1_1/`) shows the whole flow.

Trucks, shifts, and PO tasks have forms too, so a complete scenario is built and solved without opening JSON:

- **Fleet:** trucks with capacity, tags, and optional route time and distance limits. Shifts can be added one at a time or generated for several days and weekdays at once.
- **Tasks:** pick the movement (pickup, drop, or pickup-drop) and the plant end fills itself. Each task has a priority from 1 Routine to 5 Critical; it only matters when not everything fits.
- **Spreadsheet import:** tasks and locations come from CSV or Excel files, with downloadable templates. Locations may be named rather than given by ID. An import applies all rows or none.
- **Review:** issues are grouped by section, and "Go to" opens the row that needs fixing.

The scenario is checked automatically whenever it changes, and the sidebar shows what is current. Advanced JSON remains available for integrations and troubleshooting.

The **Optimize** page decides how plans are made:

- **Objective:** fewest trucks (the default, as in Version 1.0), least travel, or balanced workload.
- **Search effort:** standard, or thorough, which keeps improving until the time limit.
- **Travel-time buffer:** plans every leg slower than Google's car times.

No setting relaxes a hard rule, and changing one needs no new travel-time calculation. Each solve is stored as a new plan; the last 20 per scenario are kept. Solves run in a separate worker process, so the backend stays responsive during a long one.

The **Results** page speaks the planner's language:

- **Overview:** the outcome in one sentence, trucks used, POs planned, distance, longest route, and tightest slack.
- **Routes:** every stop shows a location name and PO number, with plant-local times.
- **Not planned:** POs left out are listed highest priority first, each with a reason and a suggested action.
- **Google Maps:** each route opens there with one click. Longer routes are split into parts.
- **Compare plans:** earlier plans for the scenario sit side by side. The table says which were made from the same inputs, and any of them can be reopened.
- **Exports:** a run-sheet workbook has one printable sheet per truck-shift. The plan workbook gains a sheet of the settings the plan was made with.

**Scenarios** can be saved, saved under a new name (never overwriting), duplicated, and deleted. Save asks before replacing a different scenario with the same ID. While a scenario has unsaved edits, the app keeps them on the backend: after a browser refresh it offers to restore them.

Google travel times are not stored (decision D6): they are kept for the session only and are left out of saved scenarios, drafts, and JSON downloads. At start-up the backend removes Google matrices that Version 1.0 cached or saved, and coordinates older than 30 days (they are also removed when a scenario is opened). The first Version 1.1 start also adds tables for drafts and a schema version. Back up `data/route_optimizer.db` first if you want to keep a copy (see [SQLite backup and restore](docs/backup_restore.md)).

## Architecture boundary

```text
Streamlit frontend -> HTTP/JSON -> FastAPI backend -> application/domain services
```

- The backend never imports Streamlit.
- The frontend does not import OR-Tools or Google routing implementations.
- Google credentials will remain in backend environment configuration.

## Prerequisites

- Windows PowerShell
- Python 3.12 (64-bit)

## Local setup

From the project root:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

The `.env` file is ignored by source control. Do not put credentials in `.env.example`.

## Start the backend

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Health endpoint: `http://127.0.0.1:8000/api/v1/health`

## Start the frontend

In a second PowerShell window:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

The frontend reports backend availability, preserves planner edits across normal reruns, and starts without a Google API key. It displays controlled warnings if the backend is unavailable, validates payloads before matrix/solve actions, hides stale plans after inputs change, renders route maps, and exports route/diagnostic data.

## Start both services

```powershell
.\run_app.ps1
```

The script starts the backend as a hidden helper process and runs Streamlit in the current console. Stopping Streamlit also stops the helper backend process.

## Quality checks

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
& .\.venv\Scripts\python.exe scripts/validate_m9_release.py
```

M0 fixture validation remains available:

```powershell
& .\.venv\Scripts\python.exe scripts/validate_m0.py
```

## Configuration

Runtime settings are read from environment variables and an optional local `.env` file. The committed `.env.example` documents supported names and contains no secrets.

The frontend uses `BACKEND_API_URL`, defaulting to `http://127.0.0.1:8000`.

## Version 1 operation docs

- [Deployment and startup](docs/deployment.md)
- [Google API setup and restrictions](docs/google_api_setup.md)
- [SQLite backup and restore](docs/backup_restore.md)
- [Troubleshooting and known limitations](docs/troubleshooting.md)
- [Version 1 release checklist](docs/version_1_release_checklist.md)
- Optional clean install verification: `& .\.venv\Scripts\python.exe scripts/clean_install_check.py`

## Project records

- `project_plan.md`: architecture, milestones, gates, and acceptance criteria.
- `build_log.md`: chronological implementation and verification evidence.
- `docs/reference_behavior_notes.md`: assessment of the original reference app.
- `sample_data/canonical/`: deterministic acceptance fixtures.
