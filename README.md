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

Fleet and task forms arrive in the next milestone; until then they are edited in Advanced JSON. The scenario is checked automatically whenever it changes, and the sidebar shows what is current.

Google travel times are not stored (decision D6): they are kept for the session only and are left out of saved scenarios and JSON downloads. At start-up the backend removes Google matrices that Version 1.0 cached or saved. Back up `data/route_optimizer.db` first if you want to keep a copy (see [SQLite backup and restore](docs/backup_restore.md)).

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
