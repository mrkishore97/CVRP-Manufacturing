# Manufacturing PO Route Optimizer

Plans truck routes for a manufacturing plant's purchase orders: pickups from suppliers, drops to customers, and pickup-drops between two places. It respects every truck's capacity and shifts, every PO's ready and due times, and truck tags and route limits. When not everything fits, it plans what it can, highest priority first, and says why the rest was left out.

Version 1.1 (see the [changelog](CHANGELOG.md)) is built for planners: every input has a form, a location needs only an address, and results use local times, kilometres, location names, and PO numbers. A FastAPI backend does the work; a Streamlit app in the browser is the user interface.

## Quick start

You need Windows with PowerShell and Python 3.12 (64-bit).

### 1. Install

In PowerShell, from this folder:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

### 2. Add a Google key (for your own addresses)

Turning addresses into places and calculating travel times needs a Google Maps Platform key with the Geocoding API and the Routes API enabled. [Google API setup](docs/google_api_setup.md) explains how to create and restrict one. Put it in `.env`:

```env
GOOGLE_MAPS_API_KEY=your-key
```

The key stays in the backend; the app never shows it. Without a key, the samples still work, because their travel times are included.

### 3. Start the app

```powershell
.\run_app.ps1
```

Open <http://127.0.0.1:8501> in a browser. The sidebar shows "Backend … connected" and whether Google Maps is configured. Stop the app with Ctrl+C in the PowerShell window.

### 4. Try a sample (no key needed)

1. The app opens on the **Scenario** page with the feasible sample. To open it again later, choose **Feasible sample** in the **Sample** list and press **Open sample**.
2. Go to **Optimize** and press **Solve route plan**.
3. **Results** shows the plan: trucks, routes with stop times, and the POs.
4. Under **Exports**, press **Download run sheets (XLSX)**: one printable sheet per truck.

### 5. Plan your own work

Work down the sidebar:

1. **Scenario:** press **Start a new empty scenario**, give it a name, set the planning period, and enter the plant's name and address.
2. **Locations:** add each supplier and customer with a name and an address, then press **Resolve addresses**. Confirm any match marked **Needs review**.
3. **Fleet:** add trucks with their capacity, then **Generate shifts** for the days they work.
4. **Tasks:** add each PO: the movement, the places, the quantity, and the ready and due times. A spreadsheet can be imported instead; download the template first.
5. **Review:** fix anything listed as an error. **Go to** opens the row.
6. **Travel times:** check the cost shown, then press **Calculate travel times**.
7. **Optimize:** keep the defaults or choose another objective, then press **Solve route plan**.
8. **Results:** read the plan, open routes in Google Maps, and download the run sheets.
9. Back on **Scenario**, press **Save scenario**.

Unsaved edits survive a browser refresh: the app offers to restore them.

## Guides

- [User guide](docs/user_guide.md): every page, in working order.
- [Addresses and Google costs](docs/addresses_and_costs.md): how addresses are matched, and what each Google action costs.
- [Objectives and priorities](docs/objectives_and_priorities.md): how the Optimize settings and task priorities shape a plan.
- [Troubleshooting and known limitations](docs/troubleshooting.md), including scenario size.
- [Google API setup](docs/google_api_setup.md): the key, its restrictions, and the Google terms the app follows.
- [Deployment and upgrading from Version 1.0](docs/deployment.md).
- [Backup and restore](docs/backup_restore.md).

## Running the services separately

The backend and the app can be started on their own, for example to watch the backend's log:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
& .\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

Health check: <http://127.0.0.1:8000/api/v1/health>. The API is documented at <http://127.0.0.1:8000/docs>.

## Architecture

```text
Streamlit app -> HTTP/JSON -> FastAPI backend -> validation, Google, OR-Tools solver, SQLite
```

- The backend never imports Streamlit and works on its own through its API.
- The app talks to the backend over HTTP only; it imports no solver or Google code.
- Google credentials stay in the backend's configuration.

## Configuration

Settings come from environment variables and the ignored local `.env` file. [`.env.example`](.env.example) lists and explains each one, and contains no secrets. The app finds the backend through `BACKEND_API_URL` (default `http://127.0.0.1:8000`).

The first start of Version 1.1 changes a Version 1.0 database: it adds tables and removes Google travel times and coordinates older than 30 days, as Google's terms require. Back up `data/route_optimizer.db` first; see [upgrading](docs/deployment.md#upgrading-from-version-10).

## Quality checks and release

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/validate_m0.py
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
& .\.venv\Scripts\python.exe scripts/validate_release.py
```

`validate_release.py` checks the release against `VERSION`: version sources, changelog, checklist, traceability, guides, and a scan for keys. The full list of release steps is the [Version 1.1 release checklist](docs/version_1_1_release_checklist.md), and [requirements traceability](docs/requirements_traceability_v1_1.md) maps every acceptance criterion to its tests. `scripts/clean_install_check.py` optionally checks a fresh install in a temporary environment.

## Project records

- `project_plan_v1.1.md`: the Version 1.1 plan, decisions, milestones, and acceptance criteria. `project_plan.md` is the Version 1.0 plan.
- `build_log.md`: the chronological record of every build, with its checks and evidence.
- `CHANGELOG.md`: what changed in each release.
- `sample_data/`: the Version 1.0 fixtures (`canonical/`, `v1_0_compat/`) and the Version 1.1 fixtures (`v1_1/`).
- `docs/reference_behavior_notes.md`: notes on the original reference app.
