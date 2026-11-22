# Troubleshooting and known limitations

Errors from the backend show a code (such as `ROUTING_AUTH_ERROR`), a message, and a request ID. Quote the request ID when asking for help; never paste the API key.

## Quick health checks

Backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Frontend:

```powershell
Invoke-WebRequest http://127.0.0.1:8501/_stcore/health
```

Whether the backend has a Google key (the key itself is never shown):

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/v1/config).google_maps_configured
```

The sidebar's **Status** says the same: "Google Maps configured" or "not configured".

## Backend and setup

### Backend unavailable

The sidebar says "Backend unavailable".

1. Start the backend with `.\run_app.ps1` or the README command.
2. Check that `BACKEND_API_URL` points to it (default `http://127.0.0.1:8000`).
3. Check the port is free: another program on port 8000 stops the backend from starting.

Editing still works while the backend is down, but nothing is checked, resolved, solved, or saved.

### Google Maps not configured (`ROUTING_CONFIGURATION_ERROR`)

The backend has no key. Put `GOOGLE_MAPS_API_KEY` in the backend's `.env` (see [Google API setup](google_api_setup.md)) and restart the backend. Scenarios whose coordinates and travel times came with the JSON, such as the samples, still work without a key.

## Google errors

Since Version 1.1 the message ends with **"Google says: …"**, Google's own reason, with any key removed. Read it first; it usually names the fix.

### Key rejected (`ROUTING_AUTH_ERROR`)

Google refused the key. Typical reasons:

- **"This IP, site or mobile application is not authorized…"**: the key's IP restriction does not include the backend's public IP. The message names the IP Google saw; add it to the key's restrictions. Home and office IPs change; see [Restrict by IP address](google_api_setup.md#restrict-by-ip-address).
- **"…API has not been used in project … or it is disabled"**: enable the Geocoding API and the Routes API in that Google Cloud project.
- **"API key not valid"**: the key in `.env` is wrong or was deleted. Copy it again and restart the backend.
- **Billing not enabled** on the Google Cloud project.

### Request rejected (`ROUTING_INVALID_REQUEST`)

Google refused what was sent.

- **A departure time in the past.** Google accepts only a future departure time for driving. The Travel times page now says so before sending; clear the time or choose a later one under **Advanced: routing options and recalculation**.
- **Something else:** the "Google says" part explains it. If it names a location, check that location's address and match.

### Quota or rate limit (`ROUTING_RATE_LIMIT`)

Google's quota for the key or project is used up. Wait for it to reset, or raise the quota in Google Cloud after checking the billing. Addresses resolved before the error are kept and cached, so resolving again costs only the rest.

### Network or timeout (`ROUTING_NETWORK_ERROR`, `ROUTING_TIMEOUT`)

The backend could not reach Google after three tries. Check the backend's internet access, proxy, or firewall, then try again.

## Addresses and travel times

### An address is not found or needs review

See [Addresses and Google costs](addresses_and_costs.md#statuses): it explains each status and reason, and how to make a hard-to-find address work.

### "Older than 30 days — resolve again"

Google allows coordinates to be kept for 30 days at most. Press **Resolve addresses**; the address, place, and your confirmation are kept, so it is one click and a confirmed match is not asked about again.

### Travel times are gone after a restart or when reopening a scenario

This is intended. Google's terms give no permission to store travel times, so they last for the session only (decision D6). Calculate them again; the cost is shown first. Travel times that came with the JSON are kept.

### "Travel times can be calculated for at most 100 locations at a time"

One calculation takes at most 100 locations. Delete locations that no task or shift uses (the Travel times page names them), or split the scenario, for example by region or by week.

## Solving

### Some POs were not planned

The Results page lists each PO left out with the reason and a suggested action. [Objectives and priorities](objectives_and_priorities.md#reading-the-reasons) explains the reasons and how priority decides which POs are kept.

### "The search ran out of time"

The solver did not find a plan within the time limit, or (for a partial plan) stopped while it was still fitting POs in.

- Raise the **time limit** on the Optimize page, up to the server's maximum (`SOLVER_MAX_TIME_LIMIT_SECONDS`, default 120 s).
- Split a large scenario, for example one per day; see [Scenario size](#scenario-size).
- Check the Review page: tasks whose windows overlap no shift make the search harder for nothing.

Before Version 1.1 (M7), a large scenario that ran out of time could be shown as a partial plan blaming "not enough fleet time". It is now reported as running out of time.

### A solve takes a long time

The solve can take up to twice the time limit when not everything fits, because the solver makes a second attempt for the partial plan. Thorough search always uses the whole limit. The backend keeps answering during a solve, and the first solve after the backend starts takes about 2 s longer.

## Saving and refresh

### Unsaved edits were not offered after a refresh

- The backend must be running when the page reloads. If it was down, the sample opened instead, but the edits are still kept on the backend. Start the backend, then open `http://127.0.0.1:8501/?scenario=<scenario ID>` in a new tab: the app offers them again.
- The page address must still carry `?scenario=<ID>`.
- Two browser tabs on the same scenario share one kept copy; the later change wins.

### Saved scenario missing after restart

1. Check `DATABASE_PATH` points to the expected database.
2. Check the backend can read and write the database folder.
3. Restore from a backup if the file was replaced (see [Backup and restore](backup_restore.md)).

### Export opens with warnings

Cells that start like a formula (`=`, `+`, `-`, `@`) get an apostrophe in CSV and Excel exports, so a spreadsheet never runs them. This is intended.

### "Payload contains more than … locations" or "… tasks"

A request is over the backend's limits; see [Scenario size](#scenario-size). Raise `API_MAX_LOCATIONS`, `API_MAX_TASKS`, or `API_MAX_REQUEST_BYTES` only after checking that solving at the larger size is practical.

## Scenario size

**Limits the backend enforces** (configurable in `.env`):

| What | Limit | Setting |
|---|---|---|
| Locations in one travel-time calculation | 100 | fixed by the API |
| Addresses per resolve request | 100 (the app sends more in several requests) | `API_MAX_GEOCODE_ADDRESSES` |
| Locations per scenario | 200 | `API_MAX_LOCATIONS` |
| Tasks per scenario | 1,000 | `API_MAX_TASKS` |
| Request size | 2 MB | `API_MAX_REQUEST_BYTES` |

A scenario with Google travel times is therefore limited to 100 locations. 200 locations are possible only with travel times supplied in the JSON.

**How long solving takes.** Measured in V1.1-M7 on the development workstation with the default settings (fewest trucks, standard search), 100 locations within about 50 km of the plant, 20 trucks on 06:00–18:00 shifts, and POs ready at 06:00 and due at 17:00:

| Scenario | Time limit | Result |
|---|---|---|
| One day: 20 truck-shifts, 200 POs | 10 s (default) | All planned, in about 12 s |
| One week: 100 truck-shifts, 300 POs | 10 s (default) | All planned, in about 13 s |
| One week: 100 truck-shifts, 500 POs | 30 s | Ran out of time |
| One week: 100 truck-shifts, 500 POs | 120 s (maximum) | All planned, in about 2 minutes |
| One week: 100 truck-shifts, 1,000 POs | 120 s (maximum) | Ran out of time |

So:

- **Up to about 300 POs** plan within the default time limit.
- **Larger scenarios** need a longer time limit, and above about 500 POs the 120 s maximum is not enough.
- **Split large workloads by day.** When each PO is ready and due on the same day, one scenario per day loses nothing, and 200 POs in a day plan in about 12 s.

Tighter time windows, longer distances, or many tags and route limits make the search harder; looser ones make it easier. The automated size test (`backend/tests/integration/test_v1_1_m7_size.py`) builds the one-week, 300-PO scenario through the forms' own functions, then resolves, calculates, solves, and exports it.

## Known limitations

- **Map.** Routes whose addresses Google matched open in Google Maps through links; there is no embedded map (decision D1 allows one only with a separate, browser-restricted embed key). The OpenStreetMap preview remains for coordinates supplied in JSON, and its lines are straight lines in stop order, not roads.
- **Google Maps links** carry at most nine stops between start and end, so a longer route gets several links. Phones may show fewer stops per link.
- **Travel times are recalculated each session** (decision D6), which costs a Google calculation each time a saved scenario is reopened.
- **Shifts longer than 24 hours** cannot be entered in the forms; use Advanced JSON.
- **Far-from-plant check.** At the default 500 km, a match in the wrong city of the same region can pass. The matched address is always shown; regional fleets should lower `GEOCODE_MAX_PLANT_DISTANCE_KM`.
- **One kept draft per scenario.** Two tabs on the same scenario share it; the later change wins.
- **No restore offer when the backend is down** at the moment the page reloads; the edits stay on the backend.
- **One plant per scenario;** no location opening hours, driver breaks, or maximum stops per route (planned for a later version).
- **Single site, single user.** SQLite suits one plant or team on one machine. For shared hosting, move persistence to a managed database behind the same repository interfaces.
- **Scenario size:** see above.
