# Troubleshooting and known limitations

## Quick health checks

Backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Frontend:

```powershell
Invoke-WebRequest http://127.0.0.1:8501/_stcore/health
```

Full smoke:

```powershell
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
```

## Common issues

### Backend unavailable in Streamlit

Cause: backend process is not running, `BACKEND_API_URL` is wrong, or the port is
blocked.

Recovery:

1. Start backend with the README command or `.\run_app.ps1`.
2. Confirm `BACKEND_API_URL` points to the backend.
3. Check the request ID shown in the UI and backend logs.

### Google key missing, invalid, or restricted incorrectly

Symptoms: matrix/geocoding action returns a controlled provider error.

Recovery:

1. Confirm `GOOGLE_MAPS_API_KEY` exists in backend environment.
2. Confirm the key is restricted to Geocoding API and Routes API.
3. Confirm the backend server's public egress IP is allowed.
4. Run `scripts/live_smoke_m3.py`.

See [google_api_setup.md](google_api_setup.md).

### Quota or rate limit reached

Recovery:

1. Wait for quota reset or reduce matrix calculations.
2. Reuse cached matrices where possible.
3. Review Google Cloud quota and billing alerts before raising limits.

### Payload too large

The backend rejects oversized requests before domain processing.

Recovery:

- Reduce task/location count.
- Raise `API_MAX_REQUEST_BYTES`, `API_MAX_LOCATIONS`, or `API_MAX_TASKS` only
  after performance testing.

### Solver timeout

The solver reports `TIMEOUT` separately from proven infeasibility.

Recovery:

- Increase `SOLVER_TIME_LIMIT_SECONDS` within the configured maximum.
- Split a large workload by day, zone, supplier group, or due-time window.
- Confirm deadlines and shifts are realistic.

### Saved scenario missing after restart

Recovery:

1. Confirm `DATABASE_PATH` points to the expected database.
2. Confirm the process has read/write access to the database folder.
3. Restore from backup if the file was replaced.

### Export opens with warnings

The app prefixes formula-like text with an apostrophe before CSV/XLSX export.
This is intentional spreadsheet-injection protection.

## Known Version 1 limitations

- Route-map lines are order-preview lines, not road-following polylines.
- Streamlit has a JSON editor workflow; richer grid editing can be added later.
- The frontend save/load UI retrieves scenarios by known ID; there is no scenario
  search/list page yet.
- The local SQLite database is suitable for a single plant/team deployment. For
  multi-user enterprise hosting, move persistence to a managed database behind
  the same repository interfaces.
- Traffic-aware routing depends on provider settings, quota, and cost policy.
- The app optimizes one scenario at a time; dispatch execution tracking is out
  of scope for Version 1.
