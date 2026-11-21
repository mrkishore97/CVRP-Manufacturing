# Manufacturing PO Route Optimizer — Version 1.1 Project Plan

**Plan revision:** 2 — rewritten from scratch; replaces the obsolete draft dated 2026-07-16  
**Date:** 2026-11-16  
**Status:** Decisions D1–D5 settled on 2026-11-16; D6 settled on 2026-11-18 (option a). V1.1-M0 (Build 014) to V1.1-M4 (Build 018) complete on branch `v1.1`; the M3 live-key manual check is still to run  
**Baseline:** tag `v1.0.0` (`2d93b2d`) — 143 automated tests passing when re-run on 2026-11-16  
**Related records:** `project_plan.md` (Version 1.0 plan, stays unchanged), `build_log.md`

---

## 1. Purpose

Version 1.0 is a working optimizer that only an engineer can drive: the whole scenario is one JSON text box, and travel times cannot be calculated unless somebody types latitude and longitude into that JSON.

Version 1.1 makes it a planner's tool. Three outcomes define the release:

1. **Forms first.** A planner builds a complete scenario — plant, locations, trucks, shifts, PO tasks, settings — through guided forms. JSON stays available as an advanced view of the *same* data, for import, export, integration, and troubleshooting.
2. **Address only.** The only location input is an address. The backend resolves it through Google, shows the matched address for confirmation, and manages coordinates as hidden, derived data. Nobody types or maintains latitude/longitude.
3. **Controls that are real.** Every field the forms expose does what it says. Fields that exist in Version 1.0 but are ignored by the solver (route-distance limit, task priority) are completed, and results are presented in planner language (local times, kilometres, location names).

Everything Version 1.0 does today keeps working, including existing JSON payloads and API clients.

## 2. What the Version 1.0 code review found

The plan is built on a review of the actual code, not on the Version 1.0 plan's intentions. Each finding below drives a work item. File references are to the `v1.0.0` baseline.

| # | Finding | Evidence | Version 1.1 action |
|---|---|---|---|
| F1 | The UI is a JSON editor. Fleet and task tabs are read-only tables. | `frontend/streamlit_app.py:381`, `:398-418` | Forms for every input area (§9) |
| F2 | The UI demands coordinates: "Every location needs location_id, latitude, and longitude before matrix calculation." It never calls geocoding, although the client method exists. | `frontend/streamlit_app.py:167-198`; `frontend/api_client.py:186` | Address-only workflow (§8) |
| F3 | The geocode endpoint cannot serve forms: it returns synthetic `GEO-<hash>` IDs instead of the caller's location IDs, one bad address fails the whole batch with HTTP 502, it takes Google's first candidate without checking match quality, has no region bias, and has no cache. | `backend/app/routing/google.py:192-328`; `backend/app/api/routes/routing.py:24` | New resolve endpoint, match-quality rules, geocode cache (§8) |
| F4 | `maximum_route_distance_meters` is accepted and then ignored by the solver and by the result validator. | `backend/app/domain/models.py:102`; no use in `solver.py` / `validator.py` | Enforce and validate (§10.5) |
| F5 | Task `priority` is accepted and then ignored: every dropped task costs the same. | `models.py:185`; `solver.py:685-686` | Priority-weighted partial plans (§10.4) |
| F6 | The solver time limit is only a ceiling. No local-search metaheuristic is set, so the solver stops at its first local optimum — Scenario A returns in 0.05 s under a 10 s limit. A "time limit" control on its own would be decorative. | `solver.py:712-717`; measured 2026-11-16 | "Search effort" option that actually uses the time (§10.3) |
| F7 | The fixed minimize-trucks objective puts all six Scenario A tasks on one truck (14 stops, 216 km) while two trucks sit idle. | Measured 2026-11-16 | Objective modes (§10.2) |
| F8 | The frontend uses a 3-second HTTP timeout for every backend call. Resolving many addresses, a matrix call, or any longer solve will be reported as "backend timed out". | `frontend/api_client.py:167`, `:179` | Per-operation timeouts (M0) |
| F9 | Every solve of a scenario is stored under the same plan ID `"<scenario_id>:M5"`, overwriting the previous plan. Long scenario IDs can exceed the 120-character ID limit. | `solver.py:784`, `:905` | Unique plan IDs, plan history (§10.8) |
| F10 | The independent result validator does not re-check vehicle-tag compatibility, route-duration limits, or route-distance limits. | `backend/app/optimization/validator.py` | Extend validator (§10.7) |
| F11 | Freshness fingerprints hash whole location objects, so writing geocoding results back into a location would invalidate its own matrix; the plan fingerprint includes the scenario ID, so a rename hides a valid plan. | `frontend/session_models.py:54-77` | Granular fingerprints (§12) |
| F12 | Spreadsheet import is preview-only, and the header-alias table is maintained twice (frontend and backend), which will drift. | `streamlit_app.py:420-438`; `frontend/import_preview.py` vs `backend/app/domain/import_contract.py` | Import-and-apply through one backend contract (§9.5) |
| F13 | Saved scenarios can only be loaded by typing their ID; there is no list. Saving silently overwrites. | `backend/app/api/routes/scenarios.py` | Scenario list, save-as, overwrite guard (§11.3) |
| F14 | Results show UTC ISO timestamps, seconds, metres, and location IDs. | `streamlit_app.py:224-254` | Planner-readable results and run sheets (§11.1) |
| F15 | Version drift: the health endpoint reports `0.1.0` while `VERSION` and `pyproject.toml` say `1.0.0`; the release script hard-codes `1.0.0`. | `backend/__init__.py`; `scripts/validate_m9_release.py` | Single version source (M0, M7) |
| F16 | The frontend/backend boundary test scans only `frontend/*.py`, so new frontend sub-packages would escape it. | `backend/tests/unit/test_package_boundaries.py:35` | Recursive scan (M0) |
| F17 | The solve endpoint runs the CPU-bound solver on the API event loop, freezing every other request (including health) during a solve. | `backend/app/api/routes/plans.py:143` | Run solves off the event loop (M5) |
| F18 | Google usage terms: geocoded coordinates may be cached for at most 30 days, and geocoding results shown on a map must be shown on a Google map. Version 1.1 makes every coordinate Google-derived, while the route map is Folium/OpenStreetMap. | Google policy pages (§13.4) | Decision D1/D2 (§4), TTL design (§8.6) |
| F19 | *Found in V1.1-M1.* httpx logs every request URL at INFO, and Geocoding URLs carry the API key and the raw address in the query string, so at the default `LOG_LEVEL=INFO` both reached the backend log. | `backend/app/routing/google.py` (query `key`); `backend/app/logging_config.py`; reproduced by a test on 2026-11-16 | Transport loggers limited to warnings (fixed in M1) |

## 3. Scope

### 3.1 Must have — the release is not Version 1.1 without these

- **M-1** Forms for scenario, plant, locations, vehicles, shifts, and PO tasks. A complete scenario can be built and solved without opening JSON.
- **M-2** JSON retained: view, edit, upload, download — all operating on the same scenario the forms edit. Version 1.0 JSON loads unchanged.
- **M-3** Address-only locations. Coordinates are never typed and never appear as form fields.
- **M-4** Explicit resolve → review → travel-time workflow with caching, so Google is called only on a button press.
- **M-5** No regression: the Version 1.0 test suite keeps passing and Version 1.0 API payloads stay valid.

### 3.2 Should have — planned for Version 1.1, sequenced after the must-haves

- **S-1** Route-distance limit enforced by solver and validator.
- **S-2** Priority-aware partial plans.
- **S-3** Objective modes (fewest trucks / balanced workload / least travel) and a search-effort option.
- **S-4** Travel-time buffer for truck speeds.
- **S-5** Spreadsheet import that applies rows (tasks and locations), with downloadable templates.
- **S-6** Scenario list, save-as, duplicate, delete, and refresh-safe drafts.
- **S-7** Planner-readable results, per-truck run sheets, plan history and comparison.
- **S-8** Fixes to existing code: F8, F9, F10, F15, F16, F17.

### 3.3 Could have — only if a milestone finishes early; never gates the release

- **C-1** Spreadsheet-style bulk grid editing (`st.data_editor`) for tasks and locations.
- **C-2** Incremental matrix refresh: when one address changes, request only that row and column from Google instead of the full matrix.
- **C-3** Clearly labelled demo routing provider so the full form workflow can be shown without a Google key.
- **C-4** Timeline (Gantt) chart per truck on the results page.

### 3.4 Will not do in Version 1.1

Multiple plants; live tracking or re-dispatch; driver app; ERP write-back; user accounts; manual map-pin placement; as-you-type address autocomplete; location opening hours and driver breaks; overtime or lateness pricing; maximum stops per route; time-of-day-dependent travel times; replacing FastAPI or adding a second frontend.

Location opening hours and driver breaks are the most valuable items on that list operationally and are the natural candidates for Version 1.2.

## 4. Decisions (settled 2026-11-16)

D1–D5 were settled on 2026-11-16 by accepting the proposed defaults; the last column records the outcome. D6 came out of the M0 terms review and was settled on 2026-11-18, when the go-ahead for M3 was given on the recommended option. They are listed first because two of them (D1, D2) concern Google's usage terms rather than engineering preference. Changing one later means updating this table before the code.

| # | Decision | Options | Decided |
|---|---|---|---|
| D1 | **Showing Google-derived locations on a map.** Google's Geocoding policy says results displayed on a map must be displayed on a Google map. Today's route map is Folium on OpenStreetMap, which was fine while coordinates were typed in JSON; in Version 1.1 they all come from Google. | (a) Google-derived locations are shown only through Google: a free "Open route in Google Maps" link per truck, plus an optional embedded Google map (Maps Embed API — free usage, needs a second, browser-restricted key). The Folium map remains for scenarios whose coordinates were supplied in JSON, such as the samples. (b) Keep Folium for everything and accept the policy risk. | (a), links only; embedded map added if you provide an embed key |
| D2 | **Retention of Google data.** Coordinates may be cached at most 30 days (place IDs indefinitely). Version 1.0 also caches matrices for 24 h and stores matrices inside saved scenarios; Routes API caching is described as restricted. | (a) Enforce the 30-day rule for coordinates now (§8.6) and review matrix persistence against the current terms in M0, changing it only if required. (b) Also stop storing matrices in saved scenarios immediately. | (a) |
| D3 | **Priority scale.** Labels and how strongly priority counts when not everything fits. | Proposed: 1 Routine (default), 2 Normal, 3 Important, 4 High, 5 Critical; omission weights 1 / 2 / 4 / 8 / 16 (one Critical task outweighs up to fifteen Routine ones). Alternative: strict ranking, where a higher priority is never dropped while a lower one is kept if avoidable. | Proposed scale and weights |
| D4 | **Local defaults.** Country bias for address matching and the label for load quantities. | Any country code; any unit word (pallets, kg, skids…). | Country `ca` (matches the default `America/Toronto` timezone); unit label "units" |
| D5 | **Default objective.** | (a) Keep "fewest trucks" as the default, exactly as Version 1.0 behaves. (b) Make "balanced workload" the default for new scenarios. | (a) |
| D6 | **Persistence of Google travel-time matrices** (raised by the M0 terms review under D2). No express permission to cache Routes API distances or durations was found, and the Routes policy page lists "distance matrix results" among content not to store outside the Services. Version 1.0 keeps a 24-hour matrix cache and saves matrices inside scenarios. | (a) Stop persisting Google-sourced matrices: no matrix in saved scenarios or drafts (only its fingerprint and request), no cross-session cache; travel times are recomputed on demand with the cost estimate shown first. Acceptance criterion 12 then covers geocodes only. (b) Keep Version 1.0 behaviour and accept the risk. (c) Keep Version 1.0 behaviour until legal review, then revisit. | **(a)**, settled 2026-11-18. M3: Google matrices are no longer written to the matrix cache, and the backend drops them from saved scenarios; existing cache rows and saved Google matrices are removed at start-up. The app leaves them out of saves and JSON downloads and keeps them only for the session. Matrices from JSON or the fake provider are unaffected. M6: drafts store only the matrix identity. |

## 5. Delivery principles

Carried forward from Version 1.0 and the earlier draft because they have proven right:

1. A milestone is complete only when its automated and manual gate checks pass and the evidence is in `build_log.md`.
2. The backend is the single authority for validation, time-zone rules, geocoding, routing, optimization, and result validation. Streamlit talks to it over HTTP only.
3. Forms and JSON are two views of one scenario object. There is never a second copy to drift.
4. Google is called only after an explicit button press, never as a side effect of a Streamlit rerun, and never for work the cache can answer.
5. A form control ships in the same milestone as the backend behaviour behind it. No decorative controls.
6. Hard constraints (capacity, deadlines, precedence, shifts, compatibility, route limits) are never relaxed by an objective mode, a priority, or a buffer.
7. API changes are additive. Omitting every new field reproduces Version 1.0 behaviour exactly.
8. Provider failures are reported; straight-line distance is never silently substituted.

New in this revision:

9. **Free checks run automatically; billable actions need a click.** Validation costs nothing, so the app re-validates whenever inputs change instead of making the planner press "Validate". Address resolution and matrix calculation stay explicit.
10. **Row-level problems are data; system problems are errors.** One unmatched address is a status on that row. A rejected API key stops the request.
11. **Derived data carries its provenance.** Every stored coordinate records which address text produced it and when, so stale data is detectable anywhere — forms, JSON, or a saved scenario.

## 6. Architecture

The dependency direction is unchanged:

```text
Streamlit (forms + JSON view) --HTTP /api/v1--> FastAPI --> application services
                                                              ├─ domain validation
                                                              ├─ routing provider + caches
                                                              ├─ OR-Tools solver + result validator
                                                              └─ SQLite persistence
```

### 6.1 Frontend restructure

`frontend/streamlit_app.py` is a single 782-line script. It becomes a thin shell over testable modules. Logic lives in pure functions under `state/` (no Streamlit import, unit-tested directly); `views/` only render.

```text
frontend/
├── streamlit_app.py        # page config, backend client, navigation, status sidebar
├── api_client.py           # new calls; per-operation timeouts
├── state/
│   ├── scenario_state.py   # the canonical scenario: create, load, CRUD, referential integrity
│   ├── fingerprints.py     # address / matrix-input / plan-input / saved fingerprints
│   ├── readiness.py        # per-location readiness and overall workflow status
│   ├── ids.py              # ID suggestion and uniqueness
│   ├── units.py            # km↔m, h:mm↔s
│   ├── timeutil.py         # local wall-clock ↔ ISO text; UTC → plant-local display
│   └── json_io.py          # clean export, export with derived data, import
├── views/
│   ├── scenario.py  locations.py  fleet.py  tasks.py
│   ├── review.py  travel_times.py  optimize.py  results.py  advanced_json.py
│   └── components.py       # shared tables, pickers, confirmations
├── import_preview.py       # reduced to reading files; column mapping moves to the backend
├── export_utils.py  route_map.py
└── tests/
```

`session_models.py` is superseded by `state/`. Its tests are migrated, not deleted: every Version 1.0 invalidation behaviour keeps an equivalent test.

Navigation is a single-script router, so pages can link to each other ("3 addresses need review → open Locations"). The current page is kept in session state and in the `?page=` URL parameter, so a browser refresh stays on the same page.

*Changed in M2 (2026-11-18).* The plan first chose `st.navigation` with `st.Page` callables, based on a spike on 2026-11-16. Re-checked in M2: under `AppTest` in the pinned 1.43.2, `st.switch_page` reaches the target page, but the next interaction on that page re-renders the default page, so multi-page workflows could not be tested. M2 therefore uses the fallback named in the risk register (§17). Page modules are unchanged by the choice.

As built in M2, `views/` holds `advanced_json`, `fleet` and `tasks` (read-only until M4), `review`, `travel_times`, `optimize` and `results`. It also holds `navigation` (page registry and sidebar), `status` (sidebar status), `validation` (automatic validation) and `components`. The sample loader moved to `frontend/samples.py`. `state/workspace.py` holds the scenario beside its derived results (§7.1) and the transitions between them.

As built in M3:

- **Navigation.** The sidebar groups the pages as Build (Scenario, Locations, Fleet, Tasks), Plan (Review, Travel times, Optimize, Results), and Advanced (JSON). The app opens on Scenario.
- **New views:** `scenario` and `locations`. Opening a scenario is shared by Scenario and Advanced JSON in `opening`, and saving in `saving`.
- **New state modules:**
  - `locations.py`: what to resolve, applying results, confirming, import merge, copy.
  - `settings.py`: identity, timezone, period, plant, planner defaults.

As built in M4:

- **New state modules:**
  - `fleet.py`: trucks, shifts, and the shift generator.
  - `tasks.py`: movements and their plant end, the task form's rules, filters, immediate warnings, and import apply.
- **Views.** `fleet` and `tasks` are now forms, and `review` groups issues with "Go to" links. `imports` holds the template downloads shared by Locations and Tasks.
- **Layout.** Add, Edit, Generate, and Import areas sit in tabs, because Streamlit does not nest expanders. One-off messages are drawn in a container that is always present. Otherwise the page below them would move when a message disappears, and Streamlit would reopen the first tab.
- **File reading.** `import_preview.py` only reads files and writes templates; its column table is gone (F12).

### 6.2 Backend additions

```text
backend/app/
├── api/routes/locations.py          # POST /locations/resolve
├── api/routes/imports.py            # import preview/mapping for tasks and locations
├── api/routes/system.py             # GET /config
├── application/location_service.py  # dedupe → cache → provider → classify → map back to IDs
├── application/planning_service.py  # applies options, buffer, plan identity and metadata
├── domain/options.py                # OptimizationOptions, RoutingOptions, priority weights
├── optimization/objective.py        # all objective and search settings in one place
├── persistence/geocode_cache.py     # 30-day address cache
└── routing/{base,google,fake}.py    # resolve_address with match-quality fields, region bias
```

### 6.3 API changes

| Endpoint | Change | Purpose |
|---|---|---|
| `POST /api/v1/locations/resolve` | New | Resolve addresses by location ID with per-row status (§8.3) |
| `POST /api/v1/locations/geocode` | Unchanged | Kept for Version 1.0 clients |
| `POST /api/v1/matrices/estimate` | New | Element count, request count, and whether the cache already has it — before any billable call. M3 adds `cache_enabled`: false for Google, whose matrices are not stored (D6) |
| `POST /api/v1/matrices/compute` | Unchanged contract | Frontend now also sends routing options. M3 adds `cache_enabled`; a Google matrix is never cached (D6) |
| `POST /api/v1/plans/validate` | Additive | Accepts `optimization_options` / `routing_options`; new warnings (§9.6). M4: every issue carries `section` and `item_id`; the details of a rejected payload carry `severity`, `section`, and `item_id` |
| `POST /api/v1/plans/solve` | Additive | Honours options; unique plan ID; runs off the event loop |
| `GET /api/v1/scenarios` | New (M3) | List saved scenarios (ID, name, updated, counts) |
| `POST /api/v1/scenarios` | Additive | `?if_exists=error` returns 409 instead of overwriting; default stays "replace" (M6). Since M3, POST and PUT drop an embedded Google matrix and report `routing_matrix_dropped` (D6) |
| `DELETE /api/v1/scenarios/{id}` | New | Delete a scenario and its plans |
| `PUT/GET/DELETE /api/v1/scenarios/{id}/draft` | New | Refresh-safe working copy (§11.3) |
| `GET /api/v1/scenarios/{id}/plans` | New | Plan history for comparison |
| `POST /api/v1/imports/tasks/preview`, `/imports/locations/preview` | New | One import contract, owned by the backend. Locations in M3, tasks in M4 |
| `GET /api/v1/imports/templates/{kind}` | New (M4) | Columns, aliases, and an example row for the `tasks` and `locations` templates |
| `GET /api/v1/config` | New | Non-secret settings the UI needs: default timezone, whether a Google key is configured, limits, region code |
| `GET /api/v1/health` | Fix | Reports the real version |

## 7. One scenario, two views: forms and JSON

### 7.1 The canonical scenario

`st.session_state["scenario"]` holds one dictionary in the public planning-payload shape — the same keys Version 1.0 JSON uses. Forms read and write parts of it through `state/scenario_state.py`. The Advanced JSON page renders it as text. There is no separately stored JSON string.

Derived artifacts — validation result, active matrix, plan, and the fingerprints they were produced from — live beside it in `st.session_state["derived"]`, never inside the editable scenario.

Additive top-level keys, all optional:

| Key | Owner | Meaning |
|---|---|---|
| `name` | Planner | Display name (Version 1.0 fixtures already carry it) |
| `routing_options` | Planner | Routing preference and departure time for the matrix |
| `optimization_options` | Planner | Objective, search effort, time limit, buffer (§10.1) |
| `planner_defaults` | Frontend | Default service minutes and the capacity unit label; ignored by the backend |

The backend currently ignores unknown top-level keys silently, so a typo such as `optimisation_options` would quietly fall back to defaults. Validation gains an `UNKNOWN_FIELD` **warning** for unrecognised top-level keys.

### 7.2 Forms → scenario

Saving a form runs a pure state function (`upsert_task`, `delete_location`, `rename_location_id`, …) that returns the updated scenario. These functions own referential integrity:

- Deleting a location, vehicle, or tag that is still referenced is refused with the list of dependants ("used by 3 tasks and 2 shifts"), with an explicit "delete these too" confirmation.
- Renaming an ID cascades to every reference.
- Changing an address clears that location's derived geocoding fields immediately.

### 7.3 JSON → scenario

1. Parse the text; syntax errors are shown with line and column and change nothing.
2. Send it to backend validation.
3. Show errors and warnings; errors block "Apply".
4. If the current scenario has unsaved changes, confirm replacement.
5. Replace the canonical scenario. An embedded `routing_matrix` becomes the active matrix when its locations match.
6. Forms re-render from the new scenario.

Invalid JSON can never replace a valid scenario.

As built in M2:

- **Edits versus replacements.** Applying text from the editor counts as an edit. Opening another scenario counts as a replacement: a sample, a saved scenario, an uploaded file, or an empty scenario. A replacement asks first ("Discard unsaved edits") when the scenario changed since it was last loaded or saved.
- **When errors block.** Validation errors block an apply only while the current scenario is valid, so an invalid scenario can still be fixed step by step. If the backend is unreachable, nothing replaces a valid scenario.
- **Clean and complete views.** The editor opens in the clean view, which hides derived geocoding fields. Applying clean JSON keeps the resolution of every location whose ID and address are unchanged. The complete view is applied literally.
- **Saving.** "Save scenario" stores the complete scenario plus the active matrix. Since M3 (decision D6), a matrix from Google is left out of saves and JSON downloads. It stays usable for the session, and the backend drops it too if a client sends one.

### 7.4 Dates and times

Forms use date and time pickers in the plant timezone and store **local wall-clock text without an offset** (`2026-06-22T07:00:00`). The backend already interprets offset-less values in the plant timezone and rejects ambiguous or non-existent daylight-saving times with row-level codes. This keeps time-zone rules in exactly one place; the frontend only converts UTC results to plant-local time for display. Values loaded from JSON with explicit offsets are preserved until edited. The one hour per year that is ambiguous on a clock can still be entered with an explicit offset in the JSON view.

### 7.5 Identifiers

Planners should not have to invent IDs. They are suggested and stay editable under an "Advanced" expander:

| Entity | Suggested ID | Example |
|---|---|---|
| Scenario | Slug of the name | `WEEK-26-INBOUND` |
| Plant | `PLANT` (the backend default) | `PLANT` |
| Location | Slug of the name, de-duplicated | `ACME-STEEL`, `ACME-STEEL-2` |
| Vehicle | Slug of the name | `TRUCK-1` |
| Shift | Vehicle ID + date (the fixture convention) | `TRUCK-1-20260622` |
| Task | Running number | `TASK-0007` |

All suggestions satisfy the backend ID pattern and 120-character limit. Dropdowns everywhere show the name first and the ID second.

### 7.6 Compatibility rules

- Every Version 1.0 key and value shape remains accepted.
- Version 1.0 JSON with coordinates and an embedded matrix still solves with no Google call — this is how the samples keep working without a key.
- JSON without coordinates is valid; the locations simply show as "not resolved yet".
- JSON export has two modes: **clean** (planner inputs only — safe to share, re-resolves on import) and **complete** (adds derived geocoding data and, optionally, the active matrix).
- Saved Version 1.0 scenarios open in the forms with defaults filled in visibly.

## 8. Address-only locations — the latitude/longitude fix

### 8.1 What the planner experiences

1. On the Locations page, enter a **name** and an **address**. Nothing else.
2. Press **Resolve addresses**. Only new or changed addresses are sent; the button shows how many.
3. Each row shows the address Google matched, with a status: **Resolved**, **Needs review**, or **Not found**.
4. A "Needs review" row shows the typed address beside the matched one and the reason. The planner confirms it or corrects the address.
5. When every location is resolved, travel times can be calculated.

Coordinates exist only as hidden derived data. They are visible solely in the "complete" JSON export.

### 8.2 Data model

`Location` already has `formatted_address`, `place_id`, `latitude`, `longitude`, `geocode_status`, and `geocode_warning` — unused by the Version 1.0 UI. Version 1.1 fills them in and adds optional fields:

| Field | Purpose |
|---|---|
| `geocode_status` | Gains the value `NEEDS_REVIEW` (existing: `PENDING`, `RESOLVED`, `FAILED`) |
| `geocode_source_fingerprint` | Hash of the normalised address (and region) that produced the coordinates — the provenance marker |
| `geocoded_at` | When Google returned the result; drives the 30-day rule |
| `geocode_location_type` | Google's precision: `ROOFTOP`, `RANGE_INTERPOLATED`, `GEOMETRIC_CENTER`, `APPROXIMATE` |
| `geocode_partial_match` | Google's partial-match flag |
| `geocode_confirmed` | The planner accepted a "Needs review" match |

A location is **ready for travel times** when it has coordinates, its status is `RESOLVED`, and either its fingerprint matches its current address (Google-derived and fresh) or it has no fingerprint at all (coordinates supplied in JSON by an integration — trusted as in Version 1.0 and badged "supplied coordinates"). Editing the address of either kind clears the coordinates.

### 8.3 Resolve endpoint

```http
POST /api/v1/locations/resolve
```

```json
{
  "locations": [
    {"location_id": "PLANT", "address": "100 Fixture Plant Road, Toronto, ON"},
    {"location_id": "ACME-STEEL", "address": "200 Supplier Avenue, Vaughan"}
  ],
  "plant_location_id": "PLANT",
  "region_code": "ca",
  "force_refresh": false
}
```

```json
{
  "request_id": "…",
  "results": [
    {
      "location_id": "ACME-STEEL",
      "status": "NEEDS_REVIEW",
      "reason_code": "PARTIAL_MATCH",
      "message": "Google matched only part of this address. Check the matched address.",
      "formatted_address": "200 Supplier Ave, Vaughan, ON L4K 0A1, Canada",
      "alternatives": ["200 Supplier Ave W, Vaughan, ON L4L 0B2, Canada"],
      "place_id": "…", "latitude": 43.82, "longitude": -79.5,
      "location_type": "RANGE_INTERPOLATED", "partial_match": true,
      "geocode_source_fingerprint": "9f2c…", "geocoded_at": "2026-11-16T15:04:05Z",
      "cache_hit": false
    }
  ],
  "summary": {"resolved": 1, "needs_review": 1, "failed": 0, "cache_hits": 1, "provider_calls": 1}
}
```

Service steps (`application/location_service.py`): normalise and fingerprint each address → collapse duplicates → answer from the cache → call the provider for the rest with bounded concurrency → classify → map every result back to the caller's location IDs, in request order.

As built in M1 (additive to the example above):

- **Request:** each row may carry `confirmed_place_id` (the place the planner already accepted). `plant_coordinates` may be sent when the plant is not in the batch, because only new or changed addresses are sent. `region_code` omitted means the server default; an empty string means no bias.
- **Result row:** `reason_codes` lists every applicable reason, primary first, and `reason_code` is the first of them. `duplicate_of` names the other location IDs at the same place. `distance_from_plant_km` and `geocode_confirmed` are included.
- **Summary:** adds `unique_addresses` and `plant_distance_checked`; the far-from-plant rule is skipped, and reported as skipped, when no plant coordinates are known.
- **Fingerprint format:** `v1:<region>:<sha256>`, self-describing, so validation can check it without knowing which region was used.
- **`/matrices/estimate`:** returns `element_count`, `request_count`, `cache_hit`, `billable_element_count`, `billable_request_count` (both zero on a cache hit), and `confirmation_required` (billable elements above `MATRIX_CONFIRM_ELEMENTS`).

### 8.4 Classification rules

| Google returns | Status | Reason code | Planner action |
|---|---|---|---|
| Exact or interpolated street address, not partial, one candidate | `RESOLVED` | — | None |
| `partial_match: true` | `NEEDS_REVIEW` | `PARTIAL_MATCH` | Confirm or correct |
| Precision `APPROXIMATE` or `GEOMETRIC_CENTER` (a town, postal area, or street with no number) | `NEEDS_REVIEW` | `LOW_PRECISION` | Confirm or add detail |
| Several candidates | `NEEDS_REVIEW` | `MULTIPLE_MATCHES` | Pick one of the listed alternatives or correct |
| Match is more than `GEOCODE_MAX_PLANT_DISTANCE_KM` (default 500) from the plant | `NEEDS_REVIEW` | `FAR_FROM_PLANT` | Confirm — catches the right street in the wrong city or country |
| No result | `FAILED` | `ADDRESS_NOT_FOUND` | Correct the address |
| Two location IDs resolve to the same place | `RESOLVED` + note | `DUPLICATE_PLACE` | Informational |
| Invalid key, quota exhausted, network or provider failure | Request fails with the existing stable error codes | — | Fix the system issue; results already obtained are cached, so the retry is cheap |

The plant-distance check uses straight-line distance purely as a sanity test; it is never used as a routing cost. Confirming a match sets `RESOLVED` and `geocode_confirmed`; a later re-resolve that returns the same place ID does not ask again.

Provider changes: `GoogleRoutingProvider` gains `resolve_address()` returning the precision, partial-match flag, and candidate list, and sends the `region` bias. The legacy `geocode()` keeps its behaviour by adapting from it. `FakeRoutingProvider` gains the same method with configurable partial, ambiguous, and not-found answers so every rule above is testable offline.

### 8.5 Geocode cache

New SQLite table `geocode_cache`, keyed by provider + region + normalised address + schema version. It stores the parsed result and timestamps only — no API key and no raw provider payload. Failed lookups are not cached. Expired rows are purged at backend start.

### 8.6 Thirty-day rule and staleness

- `GEOCODE_CACHE_TTL_SECONDS` defaults to 30 days and cannot be configured higher.
- A location whose `geocoded_at` is older than the limit is treated as not resolved: validation warns `GEOCODE_EXPIRED`, and the UI offers "Re-resolve N addresses".
- Saved scenarios have expired coordinates stripped when loaded and by a sweep at backend start; the address, place ID, and confirmation are kept, so re-resolving is one click.
- A location whose fingerprint does not match its address (for example, the address was edited in JSON) is treated as not resolved: warning `STALE_GEOCODE`.

### 8.7 Travel times from resolved locations

The Travel times page (replacing the Matrix tab) works from the hidden coordinates:

- Shows resolution status and blocks calculation until every location is ready.
- Calls `/matrices/estimate` and shows locations, billable elements, number of Google requests, and whether the cache already holds the answer.
- Requires a confirmation tick above `MATRIX_CONFIRM_ELEMENTS` (default 400 — twenty locations).
- "Calculate travel times" is the only billable matrix action; "Force refresh" sits under Advanced with its own confirmation.
- A matching embedded JSON matrix can be used instead.
- Deleting a location reuses the existing matrix by slicing it; no Google call.
- Validation warns about locations no task or shift uses (`UNUSED_LOCATION`), because each one inflates the matrix quadratically.

As built in M3:

- **Estimate.** It is asked for once per change of locations or routing options, never on a rerun. The cache figure reads "Cached", "Not cached", or "Not stored"; Google matrices are not stored (D6).
- **Calculate.** When the travel times are already current there is nothing to calculate. Recalculating anyway sits under Advanced, behind its own tick. Every tick starts unticked again after a calculation.
- **Routing options.** Routing preference and departure time are set in an Advanced form and stored as `routing_options`. The defaults remove the key, so the JSON stays as before.
- **Unused locations.** The page names the unused locations, worked out in the frontend. The backend `UNUSED_LOCATION` warning arrives with the other Review warnings in M4.
- **Map.** The Results page no longer draws address-resolved locations on the OpenStreetMap preview (D1). Google links come in M6.

### 8.8 Samples

Version 1.0 fixtures are untouched and keep solving without a key. One new address-only sample (`v11_a_address_only.json`) uses real public addresses so it can be resolved live in a demo; automated tests resolve it through the fake provider.

## 9. Form workflow

The sidebar lists the pages in working order with a live status beside each group — inputs valid, addresses resolved, travel times current, plan current, saved/unsaved.

```text
Build:    Scenario → Locations → Fleet → Tasks
Plan:     Review → Travel times → Optimize → Results
Advanced: JSON
```

Each list page follows one pattern: a table of rows, with **Add**, **Edit**, **Duplicate**, and **Delete**. Add and Edit open a form with proper widgets; nothing reruns until the form is submitted. Quantities carry the unit label; durations are entered as hours and minutes; distances in kilometres.

### 9.1 Scenario

| Field | Control | Notes |
|---|---|---|
| Scenario name | Text | ID suggested from it |
| Plant timezone | Searchable list of IANA zones | Default from backend config |
| Planning period | Start and end date/time pickers | "Fit to shifts and tasks" sets it automatically, removing the commonest validation error |
| Plant name and address | Text | Creates the plant location; pinned first on the Locations page |
| Default pickup / delivery service minutes | Number | Pre-fills new tasks |
| Capacity unit label | Text | Display only |

Actions: New, Open (picker over saved scenarios), Save, Save as, Duplicate, Delete, Load sample.

As built in M3:

- **Built:** New, Open (picker over `GET /scenarios`), Save, and Open sample.
- **M6:** Save as, Duplicate, Delete, and the overwrite guard.
- **Scenario ID.** A new scenario's ID follows its name until the planner chooses one.
- **Other plant.** "Use another location as the plant" is under Advanced.

### 9.2 Locations

Table: name, address as typed, matched address, status, used by. Form: **name** and **address** only, with the hint that company names, postal codes, and Plus Codes also work for hard-to-find sites.

Actions: Resolve addresses (N pending), Retry failed, Confirm match, Import locations from a spreadsheet (name, address), Copy locations from a saved scenario.

As built in M3:

- **Review rows.** They show the typed and matched addresses, the reason, the straight-line distance to the plant, and (in the session) Google's alternatives with "Use this address". Picking one only changes the address; resolving stays a separate click.
- **Import.** Rows update a location with the same ID, or the only location with the same name. Other rows are added.
- **Copy.** It skips addresses already present and keeps each copied location's provenance, so expired coordinates show as expired.
- **Delete.** Deleting a used location asks to delete its tasks and shifts too. The plant cannot be deleted.

### 9.3 Fleet

Vehicles: name, capacity (up to three decimals), enabled, tags, maximum route duration (h:mm, optional), maximum route distance (km, optional).

Shifts: vehicle, date, start time, end time, start location, end location (both default to the plant), optional shift duration limit.

**Shift generator:** choose vehicles, a date range, weekdays, and start/end times → preview the shifts with their IDs, overlaps and already-existing shifts flagged → apply. Building two weeks for three trucks takes one form instead of thirty.

As built in M4:

- **Trucks.** Tags are typed comma-separated. Clearing a limit removes it.
- **Shift times.** An end time at or before the start time ends on the next day.
- **Copying a shift.** "Copy to the next day" is the shift Duplicate.
- **Generator.** It also sets the start and end location and an optional route-time limit. A shift is "already exists" when the truck has one with the same start and end. Only new shifts are added, all or none.
- **Planning period.** Adding shifts or tasks outside the period extends it to whole days, and the message says so. Forms therefore never create the "outside the planning period" error. The period never shrinks on its own.

### 9.4 Tasks

| Field | Control | Notes |
|---|---|---|
| PO number | Text | |
| Movement | Pickup (supplier → plant) / Drop (plant → customer) / Pickup–drop (A → B) | Selecting it fills and locks the plant end |
| Origin, destination | Location pickers by name | |
| Quantity | Number + unit label | Warned immediately if no compatible truck can carry it |
| Ready, Due | Date + time | |
| Deadline applies to | Delivery complete (default) / Pickup complete | Explained in plain words |
| Pickup / delivery service minutes | Number | Pre-filled from scenario defaults |
| Priority | 1–5 with labels | Help text states exactly what priority does (§10.4) |
| Required truck tags | Multi-select from fleet tags | Warned if no enabled truck has them |
| Notes | Text | |

The task table filters by movement, location, and priority. Duplicate is one click — the same lane with a new PO is the commonest entry.

As built in M4:

- **Movement.** It is chosen above the form so the form changes at once. The plant end is shown as a disabled picker holding the plant; the other ends offer every location except the plant.
- **Duplicate.** It copies the lane, times, and load with a new ID, and marks the PO number "(copy)" for the planner to replace.
- **Immediate warnings.** No enabled truck has the required tags, or none that has them can carry the quantity. They appear after Add and Save and above the edit form.

### 9.5 Import

- **Tasks:** upload CSV/XLSX → the backend maps columns and returns canonical rows with row-level issues → choose Append, Update matching task IDs, or Replace all → apply. Application is all-or-nothing; a failed import changes nothing.
- Location columns accept a location **ID or exact name**, because planners' spreadsheets hold supplier names, not internal IDs.
- **Locations:** upload name + address → rows are added as "not resolved yet".
- **Templates:** downloadable CSV/XLSX templates with headers and one example row.
- The frontend alias table is deleted; the backend import contract becomes the only definition.

As built in M4:

- **Task preview.** `POST /imports/tasks/preview` receives the file's rows with the scenario's locations, plant, timezone, and default service minutes. Headers map through the same table as JSON validation.
- **What a spreadsheet may leave out.** `task_id` may be empty; new tasks are numbered. The plant end of a pickup or drop may be empty. Priority accepts 1–5 or the label.
- **Location cells.** They match a location ID, then a unique name, ignoring case and spacing. A name shared by two locations is a row error.
- **Times.** Local times are checked for daylight-saving gaps. Every row error blocks the import.
- **Apply.** Append refuses an ID that already exists; Update replaces matching IDs and adds the rest; Replace makes the file the whole task list. The app applies a valid preview all-or-nothing.
- **Templates.** `GET /imports/templates/{tasks|locations}` serves the columns, aliases, and an example row. The app writes them as CSV, or as Excel with a sheet explaining every column.
- **Not covered by automated tests.** `AppTest` cannot upload files, so the upload widget itself was checked in the browser; the steps after it are covered.

### 9.6 Review

Validation runs automatically when inputs change (principle 9). The page shows issues grouped by scenario, locations, fleet, shifts, and tasks, each with a "Go to" link to the offending row, plus normalised local/UTC times.

New non-blocking warnings, all computed by the backend: `UNKNOWN_FIELD`, `UNUSED_LOCATION`, `VEHICLE_WITHOUT_SHIFT`, `TASK_WINDOW_OUTSIDE_SHIFTS` (a task's ready–due window overlaps no shift of a compatible truck, so it cannot be served), `STALE_GEOCODE`, `GEOCODE_EXPIRED`.

As built in M4:

- **Another warning.** `NO_COMPATIBLE_VEHICLE` covers tags no enabled truck has, or a quantity only too-small tagged trucks could carry. It is a warning so that Version 1.0 payloads stay valid.
- **Clearer errors.** Overlapping shifts (`SHIFT_OVERLAP`) and shifts outside the period (`OUTSIDE_PLANNING_HORIZON`) are now named per shift. They used to be one generic error, and validity is unchanged.
- **Grouping and links.** Every issue names its section and row, so Review groups them (Scenario, Locations, Trucks, Shifts, Tasks, Travel times). "Go to" opens the row's form.
- **Fit the period.** When something is outside the planning period, Review offers "Fit the planning period to shifts and tasks".
- **Known fields.** `description` is accepted as a known top-level field. The canonical test fixtures' metadata keys are reported as `UNKNOWN_FIELD`, as intended.

### 9.7 Optimize

| Setting | Control | Default |
|---|---|---|
| Objective | Fewest trucks / Balanced workload / Least travel, each with a one-line explanation | Fewest trucks (D5) |
| Search effort | Standard (returns as soon as it finds a good plan) / Thorough (keeps improving until the time limit) | Standard |
| Time limit | Slider, bounded by the server | Server default (10 s) |
| Travel-time buffer | 0–100 % | 0 % |
| Advanced: cost of an extra truck | Kilometres | 1,000 km |
| Advanced: balance strength | Light / Medium / Strong | Medium |

A pre-flight checklist shows inputs valid, addresses resolved, travel times current. The page states that no setting relaxes a hard constraint.

### 9.8 Results and Advanced JSON

See §11.1 and §7.3.

## 10. Solver and planning changes

### 10.1 Options contract

```json
"optimization_options": {
  "objective_mode": "MINIMIZE_TRUCKS",
  "search_effort": "STANDARD",
  "time_limit_seconds": 10,
  "travel_time_factor": 1.0,
  "extra_truck_cost_km": 1000,
  "balance_strength": "MEDIUM"
}
```

Every field is optional. The defaults are the Version 1.0 constants, so a request without the object behaves exactly as today — locked by a regression test over fixtures A–F. The backend bounds every value; sending JSON directly cannot exceed server limits (`SOLVER_MAX_TIME_LIMIT_SECONDS`, default 120).

### 10.2 Objective modes

| Mode | Implementation | Effect |
|---|---|---|
| `MINIMIZE_TRUCKS` | Fixed cost per used truck-shift (`extra_truck_cost_km` × 1,000) + distance | Version 1.0 behaviour: consolidate onto as few trucks as possible |
| `MINIMIZE_TRAVEL` | No fixed cost; distance only | Uses another truck whenever that lowers total kilometres |
| `BALANCE_WORKLOAD` | No fixed cost; distance + a penalty on the longest route's working time (`SetGlobalSpanCostCoefficient` on the existing `RouteDuration` dimension) | Spreads work so no driver carries a disproportionate route; never dispatches an empty truck |

"Cost of an extra truck" is expressed in kilometres because the solver's cost unit is already metres: Version 1.0's opaque `1,000,000` is "a truck is worth dispatching only if it saves 1,000 km". Balance strength is offered as three presets rather than a raw weight; preset values are tuned in M5 against fixture V11-E and then frozen with regression tests. All weights live in `optimization/objective.py`.

### 10.3 Search effort

`STANDARD` keeps today's search. `THOROUGH` enables guided local search, which continues improving until the time limit — this is what gives the time-limit control a real effect (F6). Because a time-bounded search can differ between machines, tests for `THOROUGH` assert properties (valid plan, cost no worse than `STANDARD`) rather than exact routes.

Performance: travel-time and distance lookups are precomputed and registered as matrices (`RegisterTransitMatrix`, `RegisterUnaryTransitVector`) instead of Python callbacks, so a thorough search spends its time searching. Gate: identical results on all existing fixtures.

### 10.4 Priority

- When everything fits, priority changes nothing: all tasks are mandatory.
- When it does not all fit, the partial plan drops the cheapest set of tasks by weight (D3), so higher priorities are kept first.
- Pickup and delivery of a task are always kept or dropped together.
- Priority never overrides a hard constraint. A Critical task that is physically impossible is still reported as impossible.
- Unscheduled-task diagnostics and exports show the priority; the message says "not enough fleet time, capacity, or route allowance" instead of blaming time alone.

Weights are checked to stay far above any routing cost and far below overflow at the configured size limits.

As built in M4:

- **Penalty.** Leaving out one task node costs `dropped_task_penalty` × the task's weight (`domain/options.py`). With every priority at 1, the model is exactly Version 1.0's.
- **Diagnostics.** Every task diagnostic carries `priority`. The code `INSUFFICIENT_COMBINED_FLEET_TIME` is kept for existing consumers.
- **Proof.** In fixture V11-F only two of six identical POs fit; priorities 5 and 4 are kept.

### 10.5 Route-distance limit

A `RouteDistance` dimension with per-vehicle limits makes the existing field real. The per-task pre-check gains a distance test, so a task no truck can reach within its limit is reported individually as `ROUTE_DISTANCE_LIMIT_EXCEEDED` rather than as a generic fleet shortage.

As built in M4:

- **When the dimension is added.** Only when at least one active truck has a limit, so scenarios without one are solved by the Version 1.0 model.
- **Per-task check.** `ROUTE_DISTANCE_LIMIT_EXCEEDED` is reported when some truck could do the task alone, in time and within its shift, but only by exceeding its distance limit.

### 10.6 Travel-time buffer

Google's driving times are for cars. `travel_time_factor` (1.00–2.00) scales matrix durations before solving. It is applied once, in the planning service, to a copy of the matrix that the solver, the pre-checks, and the independent validator all use — so they cannot disagree. The cached Google matrix is untouched, changing the buffer costs no Google call, and the factor is recorded on the plan and printed on exports.

### 10.7 Independent validator

Added re-checks: vehicle tags satisfy task requirements; route duration within vehicle and shift limits; route distance within the vehicle limit. The existing corrupted-plan tests gain one case per new check.

As built in M4:

- **Route duration** is measured from the shift start to the arrival at the end depot, waiting included, which matches the solver's `Time` dimension.
- **Disabled trucks.** A route on a disabled truck is also rejected.

### 10.8 Plan identity and metadata

- Plan IDs become unique and independent of scenario ID length: `PLAN-<UTC timestamp>-<short hash>`. Existing stored plans remain readable.
- The last `PLAN_HISTORY_LIMIT` (default 20) plans per scenario are kept.
- `PlanResult` gains optional fields: `created_at`, effective options, matrix identity (source, preference, created), and metrics (truck-shifts used, longest and shortest route duration, load and time utilisation). Routes gain total duration.
- Solves run off the API event loop, one at a time, so health checks and other requests stay responsive.

### 10.9 Parameter inventory

No control is exposed before its row is complete. States verified against the code on 2026-11-16.

| Parameter | Version 1.0 state | Version 1.1 work | Milestone |
|---|---|---|---|
| Vehicle capacity, enabled | Enforced | Form | M4 |
| Vehicle tags / task required tags | Enforced by solver; **not re-validated** | Form; validator re-check | M4 |
| Vehicle / shift max route duration | Enforced by solver; **not re-validated** | Form (h:mm); validator re-check | M4 |
| Vehicle max route distance | **Declared, ignored** | Solver dimension, validator, pre-check, form (km) | M4 |
| Shift times and start/end location | Enforced | Form, generator | M4 |
| Task ready/due, due event, service minutes | Enforced | Form | M4 |
| Task priority | **Declared, ignored** | Weighted partial plans, diagnostics, form | M4 |
| Routing preference, departure time | In matrix contract; never sent by the UI | Advanced control on Travel times | M3 |
| Solver time limit | Environment only; ceiling only | Bounded request option + search effort | M5 |
| Truck fixed cost | Hard-coded constant | "Cost of an extra truck (km)" | M5 |
| Objective mode, balance strength | Absent | Option, presets | M5 |
| Travel-time buffer | Absent | Option, applied consistently | M5 |

Deliberately not exposed: raw OR-Tools strategies, penalty constants, retry counts, provider timeouts, cache keys.

## 11. Results, persistence, and scenarios

### 11.1 Results

- **Summary:** status in plain words, trucks used of available, total kilometres and driving time, tasks scheduled and unscheduled, tightest deadline slack, longest route.
- **Per truck:** shift date, start–end in plant-local time, kilometres, drive / service / wait time, peak load against capacity.
- **Stops:** sequence, action (Depart, Pick up, Deliver, Return), location **name**, PO, quantity, arrive / start / depart in local time, load after, slack, leg distance and time.
- **Unscheduled:** PO, priority, reason in plain language, due time, suggested action.
- **Compare:** recent plans for the scenario side by side — objective, trucks, kilometres, longest route, unscheduled count — so the effect of an objective mode or buffer is visible.
- **Map and links:** per decision D1.

### 11.2 Exports

Existing CSV/XLSX columns keep their names and order for anyone already consuming them. Added: a plan-settings sheet (objective, effort, buffer, matrix source), priority on diagnostics, and one human-readable **run sheet per truck-shift** (local times, location names and addresses, PO, action, quantity). Formula-injection escaping continues to apply to every new cell.

### 11.3 Scenarios and drafts

- Open from a list; Save as and Duplicate create a new ID and never overwrite; saving over an existing ID asks first; Delete removes the scenario and its plans after confirmation.
- **Refresh-safe drafts.** Streamlit loses session state on a browser refresh, which matters far more once planners type thirty tasks into forms. The current scenario ID is kept in the page URL, and each applied change is written to a draft slot on the backend. After a refresh or restart the app offers "Restore unsaved changes from 14:32" or "Discard". An explicit Save remains the only thing that changes the saved scenario.
- Schema changes are additive only (new tables `geocode_cache`, `scenario_drafts`, and an index on plans); a `schema_meta` table records the schema version for future migrations. A database backup before first Version 1.1 start is documented.

## 12. Freshness rules

Fingerprints are pure functions over the canonical scenario:

| Fingerprint | Built from |
|---|---|
| Address | Location IDs and address text |
| Matrix input | Location IDs, place IDs, rounded coordinates, routing options |
| Plan input | Timezone, period, plant, vehicles, shifts, tasks, optimization options, active matrix identity — excluding names and notes |
| Saved | The whole scenario |

| Change | Address status | Travel times | Plan |
|---|---|---|---|
| Scenario name or ID, location name, task notes, planner defaults | Keep | Keep | Keep |
| A location's address | That location → not resolved | Stale | Stale |
| Add a location | New one not resolved | Stale | Stale |
| Delete an unused location | Keep | Keep (sliced) | Stale |
| Routing preference or departure time | Keep | Stale | Stale |
| Vehicles, shifts, tasks, period, timezone, plant choice | Keep | Keep | Stale |
| Optimization options | Keep | Keep | Stale |
| New matrix calculated | — | — | Stale |
| Coordinates older than 30 days | Not resolved | Stale | Stale |

A stale plan is hidden and cannot be exported as current. Earlier plans remain available, clearly dated, in plan history.

As built in M2, the matrix-input fingerprint also includes each location's normalised address. Without it, editing an address would not make travel times stale for a location whose matrix came from JSON and which has no coordinates. Renaming a location ID keeps the matrix current by renaming it there too, and deleting an unused location slices the matrix.

## 13. Security, cost, and Google terms

### 13.1 Credentials

The server Google key stays in backend environment configuration only. No form, JSON field, export, log line, or error message carries it. If decision D1 adds an embedded Google map, that uses a **separate** key restricted to the Maps Embed API and to the app's web address — it is visible to the browser by design and must have no other API enabled.

### 13.2 Cost controls

- Resolve and Calculate are explicit buttons that state how many billable items they will send.
- The address cache (30 days) is consulted first, and cache hits are shown.
- Under D6, Google matrices are not cached. A current matrix is reused for the whole session, so it is never recalculated without a click. Matrices from the fake provider are still cached.
- Only new or changed addresses are resolved.
- Deleting a location and changing the buffer, objective, fleet, or tasks never call Google.
- Unused-location warnings keep matrices small.
- Tests assert provider call counts across Streamlit reruns.

### 13.3 Privacy and safety

Addresses appear in logs only as hashes, as today. Raw provider responses are not persisted. Uploaded spreadsheets are parsed as data only. Request-size and row-count limits apply to the new endpoints.

### 13.4 Google terms to honour

Checked on 2026-11-16 and re-read in M0 (2026-11-16); the M0 conclusions, including what could and could not be read directly, are in `docs/google_api_setup.md` → "Google usage terms that shape Version 1.1". Summary:

- Geocoding latitude/longitude may be cached for up to 30 consecutive days; place IDs indefinitely — [Geocoding API policies](https://developers.google.com/maps/documentation/geocoding/policies), [Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms).
- Geocoding results displayed on a map must be displayed on a Google map — same policy page. This is decision D1.
- Routes API content caching is restricted — [Routes API policies](https://developers.google.com/maps/documentation/routes/policies). Coordinates follow the same 30-day ceiling (D2). No express permission to cache distances or durations was found, so Google matrices are not stored (D6, settled 2026-11-18).
- Google Maps Content shown in the app needs Google attribution unless it is on a Google map that already shows it — both policy pages.
- Google Maps links carry at most nine waypoints (three in mobile browsers) and 2,048 characters — [Maps URLs](https://developers.google.com/maps/documentation/urls/get-started); longer routes are split into consecutive links.
- Maps Embed API usage is free and directions mode accepts up to 20 waypoints — [Embed usage and billing](https://developers.google.com/maps/documentation/embed/usage-and-billing).

This plan flags these terms and designs for them; it is not legal advice.

## 14. Milestones and gates

Eight milestones. The two must-have outcomes land in M3 (address-only) and M4 (forms complete), each leaving a usable application. Sizes are relative: S, M, L.

| Milestone | Outcome | Size | Status |
|---|---|---|---|
| V1.1-M0 | Baseline, decisions, safety net | S | Complete |
| V1.1-M1 | Backend address resolution | M | Complete |
| V1.1-M2 | Frontend foundation; JSON workflow on the new state model | M | Complete |
| V1.1-M3 | Scenario, plant, locations, travel times — address-only end to end | M | Complete (live-key manual check outstanding) |
| V1.1-M4 | Fleet, shifts, tasks, import, review — forms complete | L | Complete |
| V1.1-M5 | Optimization options and Optimize page | M | Pending |
| V1.1-M6 | Results, plan history, scenario management, exports | M | Pending |
| V1.1-M7 | Hardening, documentation, release | S | Pending |

### V1.1-M0 — Baseline, decisions, safety net

**Deliverables**

- This plan approved; decisions D1–D5 recorded in `build_log.md`.
- Branch `v1.1` created from `v1.0.0`; one commit per milestone gate.
- Version drift fixed: one version source, reported by the health endpoint (F15).
- Per-operation client timeouts: health 3 s, validate 15 s, geocode/resolve 60 s, matrix 120 s, solve 60 s (F8). From M5 the solve timeout is derived from the chosen time limit: 2 × limit + 20 s, covering the strict and the partial-plan attempt.
- Boundary test scans `frontend/` recursively (F16).
- Characterization tests freezing default-option results for fixtures A–F: status, scheduled set, truck-shifts used, total distance.
- Version 1.0 payloads copied to a frozen compatibility fixture folder.
- `tzdata` declared as an explicit dependency (currently present only through pandas).
- Google terms re-read; D1/D2 conclusions written into `docs/google_api_setup.md`.

**Automated checks:** format, lint, type-check, full test suite, `scripts/validate_m0.py`, new characterization and timeout tests.

**Manual checks:** load, solve, save, and export Scenario A in the current UI; confirm F1, F2, F4, F5 by observation; optional live Google smoke test with the restricted key.

**Gate:** baseline green; decisions recorded or defaults accepted; clean working tree.

### V1.1-M1 — Backend address resolution

**Deliverables:** `Location` field additions and `NEEDS_REVIEW` status; `resolve_address()` on the Google and fake providers with region bias; `location_service.py`; `geocode_cache.py` with TTL ceiling and start-up purge; `POST /locations/resolve`; `POST /matrices/estimate`; `GET /config`; new settings in `.env.example`.

**Automated checks (mocked HTTP, no key needed)**

- Results map to the caller's location IDs in request order.
- Duplicate addresses cause one provider call.
- Every row of the classification table (§8.4), including far-from-plant and duplicate-place.
- One unmatched address does not fail the batch; an invalid key or quota failure does, with the stable error code.
- Cache: miss then hit; expiry; TTL cannot exceed 30 days; failures not cached; force refresh bypasses.
- Address-only planning JSON validates; Version 1.0 JSON validates unchanged; stale and expired geocodes produce their warnings.
- No key in any response, log, or cache row.
- Legacy `/locations/geocode` behaves exactly as before.
- OpenAPI schema generates.

**Optional live check:** resolve a handful of public addresses; record only counts and statuses.

**Gate:** address-only resolution works end to end through the API with the fake provider; Version 1.0 API tests untouched and green.

### V1.1-M2 — Frontend foundation

**Deliverables:** `state/` modules; navigation shell with status sidebar; Advanced JSON page (view, edit, validate, apply, upload, download in clean and complete modes); API client methods for all new endpoints; automatic validation on change.

At the end of M2 the application does everything Version 1.0 does, on the new state model, with JSON as the only editor. This is a deliberate parity checkpoint before any form is built.

**Automated checks**

- State functions: create, upsert, delete with dependants refused, ID rename cascades, address edit clears derived fields.
- Every row of the freshness table (§12).
- JSON round-trip: export → import yields an equal scenario, in both modes.
- Invalid JSON cannot replace the current scenario.
- Version 1.0 fixtures load, validate, use the embedded matrix, and solve through `AppTest`.
- Unit conversions and local-time conversion round-trip, including a daylight-saving boundary.
- Migrated Version 1.0 frontend tests all pass.

**Manual checks:** repeat the M0 manual run on the new shell; compare results with M0.

**Gate:** Version 1.0 parity demonstrated; no frontend import of backend code. **Must-have M-2 delivered.**

### V1.1-M3 — Scenario, plant, locations, travel times

**Deliverables:** Scenario page; Locations page (name + address only); resolve, review, confirm, retry; location import and copy-from-scenario; Travel times page with estimate, confirmation, routing options, cache indicator, and matrix slicing; address-only sample.

**Automated checks**

- No form on any page exposes a latitude or longitude input (asserted over the widget tree).
- Add → resolve → confirm → calculate succeeds through `AppTest` with a fake client.
- Editing an address resets only that location and marks travel times stale; renaming a location changes nothing downstream.
- Rerunning or navigating pages makes zero provider calls.
- Travel times cannot be calculated while any location is unresolved, in review, or failed.
- Large-matrix confirmation is required above the threshold.

**Manual checks:** build a seven-location scenario from addresses with a live key; deliberately include a vague address and a wrong-city address and confirm both are caught; confirm cache hits on the second resolve.

**Gate:** a planner gets from typed addresses to a current travel-time matrix with no coordinate ever entered. **Must-have M-3/M-4 delivered.**

Status (Build 017): automated checks pass. The gate is shown end to end through the real app and backend with the offline provider. The manual run used the offline provider too. The live-key run waits for a go-ahead, because it makes billable Google calls.

### V1.1-M4 — Fleet, shifts, tasks, import, review

**Deliverables:** Fleet page with shift generator; Tasks page; task import-and-apply through the backend contract; templates; Review page with new warnings; backend completion of the fields these forms expose — route-distance limit, priority weights, validator re-checks (§10.4, §10.5, §10.7).

**Automated checks**

- Vehicles, shifts, and all three task movements created through forms validate on the backend.
- Shift generator: unique IDs, overlaps flagged, existing shifts skipped, multi-day and weekday selection.
- Movement selection fills and locks the plant end; backend rules agree.
- Import: append, update, replace; all-or-nothing on failure; locations matched by ID or name; frontend and backend can no longer disagree on aliases.
- Distance limit enforced by the solver, rejected by the validator when violated, reported per task when individually impossible.
- Priority: all tasks scheduled when feasible regardless of priority; in the shortage fixture, higher priorities are retained; weights monotonic; pairs dropped together.
- Validator rejects corrupted plans violating tags, duration, or distance.
- Default-option characterization tests from M0 still pass.

**Manual checks:** build three trucks, two days of shifts, and mixed tasks entirely through forms; apply a spreadsheet import and edit one imported row; solve.

**Gate:** a complete scenario is built and solved without opening JSON. **Must-have M-1 delivered.**

Status (Build 018): automated checks pass.

- **Gate test.** It starts from an empty scenario and drives the real app and backend, with the offline provider, to a feasible plan. The Advanced JSON page is never opened.
- **Manual run.** In the browser with the offline provider: three trucks, two days of generated shifts, mixed tasks through forms, a spreadsheet import, an edit of an imported row, and a feasible solve.

### V1.1-M5 — Optimization options

**Deliverables:** `optimization_options` contract and bounds; objective modes; search effort; travel-time buffer; precomputed transit matrices; off-event-loop solving; unique plan IDs, history, and metadata; Optimize page.

**Automated checks**

- No options → Version 1.0 results (characterization tests).
- Out-of-range values rejected with field-level errors; server maximum cannot be exceeded through JSON.
- Fixture V11-E: fewest-trucks uses the fewest truck-shifts; balanced uses more and has a lower longest-route duration; least-travel has total distance no greater than the other two.
- Every mode and effort level passes the independent validator on every fixture.
- Buffer: solver, pre-check, and validator agree; a deadline that holds at 1.0 and fails at 1.5 is diagnosed; no provider call on change.
- Thorough search returns within the time limit plus tolerance and is no worse than standard.
- Two solves produce two retrievable plans; health responds during a solve.
- Timeout is still distinguished from infeasibility.

**Manual checks:** solve Scenario A in each mode and compare trucks, kilometres, and longest route; confirm the explanations match what happens.

**Gate:** each option has deterministic regression evidence and none weakens a hard constraint.

### V1.1-M6 — Results, plan history, scenario management

**Deliverables:** results page in planner language; plan comparison; run sheets and updated exports; scenario list, save-as, duplicate, delete, overwrite guard; drafts and restore; map behaviour per D1; matrix persistence per D6 (drafts store only the matrix identity; the rest of D6 landed in M3); Google attribution wherever Google-derived addresses or travel times are shown.

**Automated checks:** local-time and unit formatting; location names resolved for every stop; exports contain settings, priority, and run sheets and remain formula-safe; empty and partial plans export; save/load round-trip is lossless; save-as never overwrites; draft restore after a simulated session loss; expired coordinates stripped on load; Version 1.0 saved scenario opens with defaults.

**Manual checks:** reconcile a run sheet against the stop table; refresh the browser mid-entry and restore; open a Google Maps link and compare stop order.

**Gate:** results are understandable without knowing any internal ID; no data loss on refresh.

### V1.1-M7 — Hardening, documentation, release

**Deliverables:** full regression pass; representative size test (form-built scenario at the documented limits); release validation script driven by `VERSION` instead of a hard-coded number; README, user guide by page, address-resolution and cost guide, objective and priority guide, updated troubleshooting, limitations, and Google setup; requirements traceability for Version 1.1; release checklist; version bump and tag `v1.1.0` after your acceptance.

**Manual acceptance:** a first-time user builds, resolves, solves, and exports a scenario from the README alone; Version 1.0 JSON still loads, solves, saves, exports; an impossible workload gives a priority-aware partial plan with reasons; no secret in tracked files, logs, or exports.

**Release gate:** every criterion in §16 passes; no open critical or high defect; skipped checks documented.

## 15. Test fixtures

Version 1.0 fixtures A–H stay unchanged. New fixtures live in `sample_data/v1_1/`. V11-A was added in M3, and V11-F to V11-I in M4. They reuse the canonical locations and travel times, trimmed to the locations each uses, so they solve offline.

| Fixture | Content | Proves |
|---|---|---|
| V11-A | Address-only plant, suppliers, customers; three trucks; mixed tasks | Addresses → matrix → valid plan |
| V11-B | Unmodified Version 1.0 Scenario A | Compatibility: loads into forms, solves identically |
| V11-C | Form-built scenario exported and re-imported | Lossless forms ↔ JSON |
| V11-D | Partial match, vague address, wrong-city address, unknown address, duplicate address | Every classification rule; one call per unique address |
| V11-E | Workload feasible on one truck with three available (Scenario A's shape) | Objective modes differ as documented |
| V11-F | Fleet shortage with priorities 1–5 | Priority-aware partial plan |
| V11-G | Refrigerated and standard trucks; matching and impossible tag requirements | Compatibility enforced and validated |
| V11-H | One truck with a duration limit, one with a distance limit | Both limits enforced and validated |
| V11-I | Multi-day generated shifts with a non-plant end location | Generator and shift depots |
| V11-J | Scripted edit sequence | Freshness table |

## 16. Acceptance criteria

Version 1.1 is complete when all of the following hold.

**Forms and JSON**

1. A planner creates a complete scenario and obtains a plan without opening JSON.
2. Every scenario field can be entered through a form.
3. JSON can be viewed, edited, uploaded, and downloaded, and always shows the same scenario as the forms.
4. Unmodified Version 1.0 JSON loads into the forms and solves with the same result.
5. Invalid JSON never replaces a valid scenario.

**Address only**

6. No form contains a latitude or longitude input.
7. A location needs only a name and an address.
8. The backend resolves addresses and returns a per-location status.
9. Vague, partial, ambiguous, and far-away matches require confirmation before use.
10. One bad address does not block the others.
11. Editing an address invalidates only what depends on it.
12. Google is called only on an explicit action; repeated identical requests are served from cache. Under D6 this covers address lookups; travel times are reused within the session instead.
13. Coordinates older than 30 days are not used.

**Controls are real**

14. Route-distance limits are enforced by the solver and re-checked by the validator.
15. Priority decides which tasks a partial plan keeps and never relaxes a hard rule.
16. With no options supplied, results match Version 1.0.
17. Each objective mode produces its documented effect on the comparison fixture.
18. Search effort makes the time limit meaningful.
19. The travel-time buffer is applied consistently and recorded on the plan.
20. Every returned plan passes independent validation of capacity, time, pairing, shifts, tags, duration, distance, and deadlines.

**Usability and safety**

21. Results show local times, kilometres, location names, and PO numbers.
22. Task and location spreadsheets can be previewed and applied, all-or-nothing.
23. Scenarios can be listed, saved as, duplicated, and deleted; nothing is overwritten without confirmation.
24. Unsaved work survives a browser refresh.
25. Each solve is kept as a separate plan; recent plans can be compared.
26. The backend works without Streamlit; Streamlit imports no backend code.
27. No key or secret appears in forms, JSON, exports, logs, or tracked files.
28. Every Version 1.0 test still passes; every milestone has evidence in `build_log.md`.

## 17. Risks

| Risk | Impact | Mitigation | Where |
|---|---|---|---|
| Google returns a plausible but wrong location | Truck sent to the wrong place | Match-quality rules, side-by-side confirmation, far-from-plant check, region bias. The M3 manual run showed the limit: at the default 500 km, a wrong city about 370 km away (Ottawa for a Mississauga plant) is accepted. The matched address is still shown beside the typed one. Regional fleets should lower `GEOCODE_MAX_PLANT_DISTANCE_KM` | M1, M3 |
| Forms and JSON drift apart | Lost or conflicting edits | One canonical scenario; round-trip tests | M2 |
| An address edit reuses old coordinates | Wrong matrix and routes | Provenance fingerprint on every coordinate; backend warning; freshness tests | M1, M2 |
| Streamlit reruns trigger billable calls | Unexpected cost | Explicit actions; call-count tests; caches | M1, M3 |
| Navigation change breaks UI testability | Untested pages | Occurred in M2: `AppTest` loses the page after `st.switch_page`; the single-script router fallback is in use | M2 |
| Form state lost on refresh | Planner re-enters everything | URL-held scenario ID and backend drafts | M6 |
| A new option silently changes default behaviour | Version 1.0 results shift | Characterization tests from M0 run in every milestone | M0–M7 |
| Priority read as a guarantee | Wrong expectations | Wording in form, guide, and diagnostics; explicit tests | M4 |
| Balanced mode adds kilometres unexpectedly | Higher cost | Plan comparison shows the trade-off; presets instead of raw weights | M5, M6 |
| Thorough search results vary between machines | Flaky tests, confused users | Property-based tests; plan records effort and time used | M5 |
| Buffer applied inconsistently | Validator rejects good plans or passes late ones | One buffered matrix shared by solver, pre-check, and validator | M5 |
| Long solves block the API | UI appears frozen | Off-event-loop solving; client timeout derived from the time limit | M0, M5 |
| Google terms on caching and map display | Compliance exposure | D1/D2; 30-day ceiling in configuration; terms re-read in M0 | M0, M1, M6 |
| Scope growth delays the must-haves | Late release | Must-haves complete by M4; "could" items never gate | All |
| Import partly applied | Corrupt task list | All-or-nothing apply | M4 |
| Deleting referenced data | Broken references | Refusal with dependants listed; backend validation | M2, M4 |

## 18. Verification commands

```powershell
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m mypy backend frontend
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts/validate_m0.py
```

Focused runs during a milestone:

```powershell
& .\.venv\Scripts\python.exe -m pytest backend/tests/unit/routing backend/tests/integration/routing -q
& .\.venv\Scripts\python.exe -m pytest backend/tests/unit/optimization -q
& .\.venv\Scripts\python.exe -m pytest frontend/tests -q
```

Release (added in M7): `scripts/validate_release.py`. Live Google checks remain separate, explicit, and optional.

## 19. Working rules

- `build_log.md` stays the chronological record; entries are labelled `V1.1-M0` … `V1.1-M7` and record scope, files changed, commands run with results, manual checks, decisions, known issues, and the gate decision.
- The status table in §14 changes only after passing evidence is in the build log.
- A change is done when: it belongs to the active milestone; its behaviour and its failure behaviour are tested; format, lint, type-check, and relevant tests pass; boundaries hold; freshness effects are tested where touched; no passive rerun can call Google; no secret is exposed; documentation and samples are updated when behaviour changes.
- `project_plan.md` is not edited.
- If a requirement changes, this plan is updated before the code.

## 20. What changed from the obsolete draft

### 20.1 Kept — good ideas carried forward

One canonical state behind forms and JSON; address-only entry with backend geocoding and a geocode cache; a location-aware resolve endpoint; confirmation of doubtful matches; granular freshness fingerprints; priority-aware partial plans; enforcement of the route-distance limit; objective modes; the parameter inventory; import with append/update/replace; the shift generator; ID suggestions; friendly units; save-as and duplicate; unsaved-change protection; additive API changes; milestone gates with build-log evidence.

### 20.2 Changed

| Draft | This revision | Why |
|---|---|---|
| Described what to build in general terms | Grounded in a code review with file references (§2) | The draft could not be executed or checked against the code |
| Nine milestones with forms spread across four | Eight milestones; address-only done by M3, forms by M4 | Must-haves land early and each milestone leaves a usable app |
| Manual "Validate" step kept | Validation runs automatically; only billable actions need a click | One less step in every loop |
| Raw "vehicle fixed cost" and "balance weight" numbers | "Cost of an extra truck (km)" and three balance presets | The draft's own risk register called the raw value confusing |
| Exposed a solver time limit | Time limit paired with a search-effort option | Alone, the limit has no effect (F6) |
| Frontend converts local times with its own time-zone logic | Forms send local wall-clock text; backend applies time-zone rules | One authority for daylight-saving rules |
| Unknown JSON fields "continue to fail" | Unknown top-level fields produce a warning | They are silently ignored today, not rejected |
| Re-run the Version 1.0 release script at release | New version-driven release script | The old script hard-codes `1.0.0` and would fail after the bump |

### 20.3 Added — brought to your notice

1. **Match-quality rules for addresses** (§8.4): partial, vague, ambiguous, and far-from-plant matches need confirmation. Address-only entry is only safe if a wrong match cannot slip through.
2. **Thirty-day handling of coordinates and the map-display question** (D1, D2, §8.6): Google usage terms the draft did not consider.
3. **Travel-time buffer** (§10.6): Google's times are for cars; a planner needs a truck allowance.
4. **Search effort** (§10.3) and faster solver lookups, so longer time limits buy better plans.
5. **Fix for the 3-second client timeout** (F8) — without it the new address and travel-time steps would fail in normal use.
6. **Unique plan IDs, plan history, and comparison** (§10.8, §11.1) — today each solve overwrites the last.
7. **Validator re-checks** for tags, route duration, and route distance (§10.7).
8. **Refresh-safe drafts** (§11.3) — forms make lost session state costly.
9. **Scenario list, delete, and overwrite guard** (§11.3).
10. **Readable results and per-truck run sheets** (§11.1, §11.2), plus a Google Maps link per route (D1).
11. **Automatic validation and early warnings** (§9.6): unused locations, trucks without shifts, tasks no shift can serve, unknown JSON fields.
12. **Matrix cost helpers** (§8.7): estimate before calling, confirmation for large matrices, reuse when a location is deleted.
13. **Location import, copy-from-scenario, import by location name, and templates** (§9.2, §9.5).
14. **Scenario-level defaults**: service minutes and capacity unit label (§9.1); "fit planning period" helper.
15. **Housekeeping fixes** to existing code: version drift, boundary test, event-loop blocking, explicit `tzdata`, single import contract (F12, F15–F17).
16. **`GET /config`** so the UI knows limits and whether a Google key is configured before the planner hits an error.

### 20.4 Dropped or deferred

Nothing requested was dropped. Bulk grid editing, incremental matrix refresh, a demo routing provider, and a timeline chart are listed as "could have" (§3.3). Location opening hours and driver breaks are recommended for Version 1.2 (§3.4).

## 21. Immediate next step

V1.1-M0 (Build 014) to V1.1-M4 (Build 018) are complete on branch `v1.1`. Both must-have outcomes are delivered: address-only locations (M3) and forms for every input (M4).

Next:

- The M3 live-key manual check, once there is a go-ahead for billable Google calls.
- **V1.1-M5**: optimization options and the Optimize page.
