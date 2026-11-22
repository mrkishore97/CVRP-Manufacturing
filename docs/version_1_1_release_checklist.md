# Version 1.1 release checklist

**Release:** `v1.1.0`
**Plan:** `project_plan_v1.1.md` (§14 V1.1-M7, §16 acceptance criteria)
**Evidence:** `build_log.md`, Build 021, and [requirements traceability](requirements_traceability_v1_1.md)
**Status:** ready for acceptance. `VERSION` is 1.1.0. The commit is tagged `v1.1.0` once the release is accepted.

## Acceptance criteria (plan §16)

Each row's tests and manual checks are listed under the same ID in the [traceability matrix](requirements_traceability_v1_1.md).

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | A planner creates a complete scenario and obtains a plan without opening JSON. | Pass | AC-01; README walkthrough in Build 021 |
| 2 | Every scenario field can be entered through a form. | Pass | AC-02 |
| 3 | JSON can be viewed, edited, uploaded, and downloaded, and always shows the same scenario as the forms. | Pass | AC-03 |
| 4 | Unmodified Version 1.0 JSON loads into the forms and solves with the same result. | Pass | AC-04; Build 021 in the browser |
| 5 | Invalid JSON never replaces a valid scenario. | Pass | AC-05 |
| 6 | No form contains a latitude or longitude input. | Pass | AC-06 |
| 7 | A location needs only a name and an address. | Pass | AC-07 |
| 8 | The backend resolves addresses and returns a per-location status. | Pass (offline provider and mocked Google HTTP) | AC-08; the live check is listed under skipped checks |
| 9 | Vague, partial, ambiguous, and far-away matches require confirmation before use. | Pass | AC-09 |
| 10 | One bad address does not block the others. | Pass | AC-10 |
| 11 | Editing an address invalidates only what depends on it. | Pass | AC-11 |
| 12 | Google is called only on an explicit action; repeated identical requests are served from cache (address lookups; travel times are reused within the session, decision D6). | Pass | AC-12 |
| 13 | Coordinates older than 30 days are not used. | Pass | AC-13 |
| 14 | Route-distance limits are enforced by the solver and re-checked by the validator. | Pass | AC-14 |
| 15 | Priority decides which tasks a partial plan keeps and never relaxes a hard rule. | Pass | AC-15; V11-F in the browser, Build 021 |
| 16 | With no options supplied, results match Version 1.0. | Pass | AC-16 |
| 17 | Each objective mode produces its documented effect on the comparison fixture. | Pass | AC-17 |
| 18 | Search effort makes the time limit meaningful. | Pass | AC-18; size measurements in Build 021 |
| 19 | The travel-time buffer is applied consistently and recorded on the plan. | Pass | AC-19 |
| 20 | Every returned plan passes independent validation of capacity, time, pairing, shifts, tags, duration, distance, and deadlines. | Pass | AC-20 |
| 21 | Results show local times, kilometres, location names, and PO numbers. | Pass | AC-21 |
| 22 | Task and location spreadsheets can be previewed and applied, all-or-nothing. | Pass | AC-22 |
| 23 | Scenarios can be listed, saved as, duplicated, and deleted; nothing is overwritten without confirmation. | Pass | AC-23 |
| 24 | Unsaved work survives a browser refresh. | Pass | AC-24 |
| 25 | Each solve is kept as a separate plan; recent plans can be compared. | Pass | AC-25 |
| 26 | The backend works without Streamlit; Streamlit imports no backend code. | Pass | AC-26 |
| 27 | No key or secret appears in forms, JSON, exports, logs, or tracked files. | Pass | AC-27; `scripts/validate_release.py` |
| 28 | Every Version 1.0 test still passes; every milestone has evidence in `build_log.md`. | Pass | AC-28; Builds 014 to 021 |

## Manual acceptance (plan §14, V1.1-M7)

Run on 2026-11-22 in the browser against the real backend on a scratch database, with an offline provider standing in for Google (Build 021).

| Check | Status | What was seen |
|---|---|---|
| A first-time user builds, resolves, solves, and exports a scenario from the README alone | Pass (offline provider) | Following README steps 4 and 5 only: the sample solved (1 of 6 truck-shifts, 216 km). A new scenario got a plant, two locations, a truck, a generated Monday shift, a pickup, and a drop. The addresses resolved, travel times were calculated after the cost was shown, and the solve planned 2 of 2 POs. Results offered the run sheets and the other exports, and the scenario saved. |
| Version 1.0 JSON still loads, solves, saves, and exports | Pass | Unmodified Version 1.0 Scenario A, pasted into Advanced JSON, applied with its travel times. It solved exactly as in Version 1.0 (1 of 6 truck-shifts, 216 km), offered every export, and saved as A. |
| An impossible workload gives a priority-aware partial plan with reasons | Pass | V11-F: two of six full-truck drops fit. The Critical and High POs were planned; the four left out were listed highest priority first (3, 2, 1, 1), each with its reason. |
| No secret in tracked files, logs, or exports | Pass | `scripts/validate_release.py` scans tracked and new files, `logs/`, `exports/`, and the database for Google keys: none found. Exports hold no key by construction (AC-27 tests). |

## Release gate

- **Every criterion in §16 passes:** yes. Criteria 8 and 12 rest on the offline provider and mocked Google HTTP; the live check is skipped, see below.
- **No open critical or high defect:** yes. Three defects found in M7 were fixed in M7 (Build 021):
  - A large scenario that ran out of time was shown as a partial plan blaming fleet time.
  - Google's reason for a rejection was dropped, leaving the HTTP 400 of M5 undiagnosable.
  - More than 100 addresses or travel-time locations failed with a contract error instead of a clear message.
- **Skipped checks documented:** yes, below.

## Skipped checks

| Check | Why it was not run | How to run it |
|---|---|---|
| Live Google check (the M3 manual check) | It makes billable Google calls, which need the project owner's go-ahead. | Configure the key, open the address-only sample, press **Resolve addresses** (7 Geocoding requests), confirm any match that needs review, then **Calculate travel times** (49 elements, 1 request) and solve. Alternatively run `scripts/live_smoke_m3.py` (2 Geocoding requests and 4 elements). |
| The HTTP 400 from Google Routes met in M5 | It needs the live key. Since M7 any rejection shows Google's own reason, and a past departure time is refused before sending. | Repeat the calculation that failed; the error now ends with "Google says: …". See [troubleshooting](troubleshooting.md#request-rejected-routing_invalid_request). |
| Clean install in a fresh environment | It downloads every dependency into a temporary environment. | `& .\.venv\Scripts\python.exe scripts/clean_install_check.py` |
| Google Maps links on a phone | No phone in the test setup. | Open a route's link on a phone; expect fewer stops per link. |

## Known lower-severity issues

None blocks the release. The ones planners meet are also in [troubleshooting](troubleshooting.md#known-limitations).

- No embedded Google map: links only, under decision D1.
- Google travel times are recalculated in each new session (D6).
- Shifts longer than 24 hours need Advanced JSON.
- The far-from-plant check at 500 km can pass the wrong city of the same region.
- Two tabs on one scenario share one kept draft; no restore offer while the backend is down.
- The first task, truck, or shift added to an empty list reopens the first tab once (M4).
- The Optimize summary shows the server's time limit for a Version 1.0 scenario (M5).
- Google's text attribution is plain "Google Maps" in the caption style; check it against Google's typography rules before a production deployment.
- OR-Tools/SWIG deprecation warnings appear in the test output (third-party).

## Release commands

From the project root:

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/validate_m0.py
& .\.venv\Scripts\python.exe scripts/review_m2_payloads.py
& .\.venv\Scripts\python.exe scripts/smoke_m1.py
& .\.venv\Scripts\python.exe scripts/validate_release.py
& .\.venv\Scripts\python.exe -m pip check
```

Set `DATABASE_PATH` to a scratch file before `smoke_m1.py` to keep the working database untouched.

## Sign-off

- Version sources agree on 1.1.0: yes (`validate_release.py`).
- Changelog, user guide, address and cost guide, objectives and priorities guide, troubleshooting, Google setup, deployment, and backup docs updated: yes.
- Google's policy pages re-read: 2026-11-22.
- Database backup before upgrading documented: yes.
- Tag `v1.1.0`: after acceptance.
