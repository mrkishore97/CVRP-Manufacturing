# Changelog

Each release's plan and evidence are in `project_plan*.md` and `build_log.md`.

## 1.1.0

Version 1.1 makes the optimizer a planner's tool: every input has a form, locations need only an address, and every control does what it says. Plan: `project_plan_v1.1.md`. Evidence: builds 014 to 021 in `build_log.md`.

### Forms first

- Pages in the sidebar: Scenario, Locations, Fleet, Tasks, Review, Travel times, Optimize, Results, and Advanced JSON, with a live status of what is valid and current.
- A complete scenario is built and solved without opening JSON. JSON stays available and always shows the same scenario as the forms; invalid JSON never replaces a valid scenario.
- Trucks with tags and route time and distance limits; shifts one at a time or generated for many days and weekdays; tasks by movement (pickup, drop, pickup-drop) with the plant end filled in.
- Task and location import from CSV or Excel, previewed and applied all-or-nothing, with downloadable templates. Locations may be named instead of given by ID.
- Automatic validation, issues grouped by section with "Go to", and new warnings: unknown fields, unused locations, trucks without shifts, tasks no shift can serve, and tags or quantities no truck can take.

### Address only

- A location needs only a name and an address. The backend resolves addresses through Google, only on a button press, sending only new or changed addresses, each distinct address once, and answering repeats from a 30-day cache.
- Doubtful matches (partial, low precision, several candidates, far from the plant) need confirmation; one bad address does not block the others.
- Travel times are estimated before they are calculated, with a confirmation above 400 elements.
- Google's terms are followed: coordinates are kept at most 30 days and stripped from saved scenarios and drafts when older; Google travel times are not stored (decision D6); Google-derived routes are shown through Google Maps links rather than another map (decision D1); "Google Maps" is credited wherever its content appears.

### Controls that are real

- Route distance limits are enforced by the solver and checked by the validator.
- Task priority (1 Routine to 5 Critical) decides which POs a partial plan keeps, and never relaxes a rule.
- Objectives: fewest trucks (the default and Version 1.0's behaviour), least travel, and balanced workload. Search effort (standard or thorough), a time limit bounded by the server, a travel-time buffer, the cost of an extra truck, and balance strength.
- The independent validator also checks truck tags, route durations, and route distances.

### Results, plans, and scenarios

- Results in planner language: local times, kilometres, location names, and PO numbers; POs left out are listed by priority with a reason and a suggested action.
- Every solve is a separate plan with a unique ID; recent plans are compared side by side, with the inputs marked "Same" or "Different", and earlier plans can be reopened.
- Run sheets: one printable sheet per truck-shift. The plan workbook gains a settings sheet; diagnostics gain priority and a suggested action. Version 1.0 columns are unchanged.
- Save asks before replacing another saved scenario; Save as and Duplicate never overwrite; Delete removes a scenario with its plans.
- Unsaved edits are kept on the backend and offered back after a browser refresh.

### Fixes and hardening

- One version source: the health endpoint, OpenAPI, and the package all report `VERSION`.
- Per-operation client timeouts replace the 3-second limit; solves run in a worker process, so the backend answers during a solve.
- The httpx logger no longer writes Google request URLs, which carried the key, to the log.
- Google's own reason for rejecting a request is shown ("Google says: …"), with the key removed and never logged. A departure time in the past is refused before anything is sent.
- A large scenario that runs out of time is reported as running out of time, not as a partial plan blaming fleet time. A partial plan cut short by the time limit says that more POs may fit.
- Addresses are resolved in requests within the backend's limit; travel-time requests above 100 locations are explained before sending.
- `scripts/validate_release.py` validates a release against `VERSION`, replacing `scripts/validate_m9_release.py`.

### Compatibility

Version 1.0 JSON, saved scenarios, and API clients keep working. With no new options, plans are the same as Version 1.0's. The first start adds database tables and removes stored Google travel times and coordinates older than 30 days; back up the database first ([deployment guide](docs/deployment.md#upgrading-from-version-10)).

## 1.0.0

The first release: a FastAPI backend and a Streamlit frontend; Google geocoding and Routes travel times; a deadline-aware OR-Tools solver for pickup, drop, and pickup-drop tasks across trucks and shifts; infeasibility diagnostics and partial plans; SQLite persistence; maps; CSV and Excel exports. Plan: `project_plan.md`. Release record: [Version 1 release checklist](docs/version_1_release_checklist.md).
