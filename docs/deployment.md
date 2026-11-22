# Deployment and startup guide

This project is intentionally split into a backend API and a replaceable
Streamlit frontend.

```text
Streamlit frontend -> HTTP/JSON -> FastAPI backend -> domain/routing/solver/persistence
```

## Supported environment

- Windows PowerShell
- Python 3.12, 64-bit
- Local SQLite database
- Backend and frontend running on the same workstation or Windows server

Linux hosting should work with equivalent commands, but Versions 1.0 and 1.1 have
been validated on Windows.

## Fresh setup

From `manufacturing_po_route_optimizer/`:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` for the deployment environment. Leave `GOOGLE_MAPS_API_KEY` blank
until a restricted backend-only key is ready.

## Start backend only

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

## Start frontend only

```powershell
$env:BACKEND_API_URL = "http://127.0.0.1:8000"
& .\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Open `http://127.0.0.1:8501`.

## Start both services

```powershell
.\run_app.ps1
```

The script starts the backend as a hidden helper process and runs Streamlit in
the current console. Stopping Streamlit stops the helper backend process.

## Recommended production settings

Set these through environment variables or a secure platform secret/configuration
mechanism:

```env
APP_ENV=production
LOG_LEVEL=INFO
PLANT_TIMEZONE=America/Toronto
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
BACKEND_API_URL=http://127.0.0.1:8000
DATABASE_PATH=data/route_optimizer.db
GOOGLE_MAPS_API_KEY=backend_only_secret
GEOCODE_REGION_CODE=ca
GEOCODE_CACHE_TTL_SECONDS=2592000
GEOCODE_MAX_PLANT_DISTANCE_KM=500
MATRIX_CONFIRM_ELEMENTS=400
SOLVER_TIME_LIMIT_SECONDS=10
SOLVER_MAX_TIME_LIMIT_SECONDS=120
SOLVER_IN_SUBPROCESS=true
PLAN_HISTORY_LIMIT=20
API_MAX_REQUEST_BYTES=2000000
API_MAX_LOCATIONS=200
API_MAX_TASKS=1000
API_MAX_GEOCODE_ADDRESSES=100
```

`.env.example` explains each setting. A regional fleet should lower
`GEOCODE_MAX_PLANT_DISTANCE_KM` (for example to 150), so that a match in the wrong city
of the same region needs review. Before raising the size limits, see
[Scenario size](troubleshooting.md#scenario-size).

Do not commit `.env`, `.streamlit/secrets.toml`, database files, logs, or
exports.

## Upgrading from Version 1.0

1. Stop the app and back up `data/route_optimizer.db` (see
   [Backup and restore](backup_restore.md)).
2. Update the code and run `pip install -e ".[dev]"` again.
3. Start the backend. Its first start changes the database, adding only:
   - new tables for the address cache, kept unsaved edits (drafts), and the schema version
     (version 2), plus an index on plans;
   - and, as Google's terms require, it removes Google travel times that Version 1.0 cached
     or saved inside scenarios (decision D6), and coordinates older than 30 days.
4. If a Version 1.0 backend ever ran with a real key at log level `INFO`, its log files hold
   the key and raw addresses (finding F19): delete them and consider rotating the key.

Version 1.0 JSON files, saved scenarios, and API clients keep working unchanged. A scenario
saved by Version 1.0 opens in the forms with the defaults filled in.

## Backend API independence

The backend can be used without Streamlit. Example:

```powershell
$payload = Get-Content sample_data/canonical/scenario_a_feasible_mixed.json -Raw |
    ConvertFrom-Json

Invoke-RestMethod `
    -Uri http://127.0.0.1:8000/api/v1/health `
    -Method GET
```

For solve calls, use the clean planning payload shape produced by the canonical
fixtures or by the Streamlit editor; fixture reference fields such as
`locations_ref` and `matrix_ref` are not API inputs.

## Release verification

Run:

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/validate_m0.py
& .\.venv\Scripts\python.exe scripts/review_m2_payloads.py
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe scripts/validate_release.py
```

The release checklist for the current version lists every step: [Version 1.1 release checklist](version_1_1_release_checklist.md).
