# Manufacturing PO Route Optimizer — Build Log

**Purpose:** Chronological implementation and verification record  
**Project plan:** `project_plan.md` (Version 1.0); `project_plan_v1.1.md` (Version 1.1, from Build 014)  
**Started:** 2026-06-21  
**Current milestone:** Version 1.1 — V1.1-M6 complete on branch `v1.1` (M3 live-key manual check outstanding); next V1.1-M7

## Logging rules

1. Add an entry during every implementation session before handoff.
2. Keep entries chronological and append new entries at the end.
3. Do not mark a check as passed unless it was actually executed.
4. Record checks not run and the reason.
5. Include relevant commands or test-suite names so results are reproducible.
6. Record user-approved requirement or architecture changes.
7. Record known issues even when they do not block the current milestone.
8. A milestone is complete only when its gate evidence appears here and its status is updated in `project_plan.md`.
9. Never include API keys, credentials, private PO data, or sensitive provider responses.

## Entry template

```text
## YYYY-MM-DD — Build NNN — M# — Short title

### Scope

- Work intended for this build.

### Changes

- File or component: concise description.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Command or manual check | PASS/FAIL/NOT RUN | Relevant output or reason |

### Decisions and assumptions

- Decisions made or “None.”

### Known issues

- Open issue or “None.”

### Gate status

- Current milestone gate status and remaining items.

### Next action

- Next gated implementation step.
```

---

## 2026-06-21 — Build 001 — M0 — Project plan approved

### Scope

- Establish the project directory and implementation control documents.
- Convert the approved application design into milestone gates and verification requirements.
- Establish the build-log process requested by the project owner.

### Changes

- `project_plan.md`: Added the complete architecture, data contracts, solver design, Google routing strategy, ten implementation milestones, stage gates, canonical tests, risk register, and Version 1 acceptance criteria.
- `project_plan.md`: Linked milestone completion evidence to this build log.
- `build_log.md`: Created the append-only build and verification record with a reusable entry template.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Project plan exists in the new project folder | PASS | File created under `manufacturing_po_route_optimizer/`. |
| Required plan sections present | PASS | Architecture, domain, routing, optimization, diagnostics, milestones, tests, acceptance criteria, risks, and next step were detected. |
| Milestone section count | PASS | M0 through M9: 10 milestone sections. |
| Reference application changed | PASS | No reference-project file was edited during planning. |
| Application tests | NOT RUN | No application code exists yet. |

### Decisions and assumptions

- The project plan was approved by the project owner on 2026-06-21.
- Build history will be maintained in this file throughout implementation.
- M0 remains active until reference behavior notes and canonical acceptance fixtures are created and checked.

### Known issues

- None at the planning-document level.
- A live Google API smoke test will require a restricted developer key in M3; offline development will use a fake provider and mocked HTTP.

### Gate status

- M0 is in progress.
- Passed: approved plan and documented working assumptions.
- Remaining: reference behavior notes, canonical sample fixtures, requirement-to-test traceability check, and M0 gate review.

### Next action

- Create the M0 reference behavior notes and canonical feasible/infeasible sample fixtures, then execute and record the M0 gate review.

---

## 2026-06-21 — Build 002 — M0 — Baseline and acceptance fixtures complete

### Scope

- Complete the remaining M0 deliverables.
- Document reference behavior and replacement decisions.
- Create deterministic acceptance fixtures for canonical Scenarios A–H.
- Map every Version 1 acceptance criterion to milestone evidence.
- Execute and record the M0 quality gate.

### Changes

- `docs/reference_behavior_notes.md`: Documented the reference workflow, retained concepts, replaced behavior, and implementation risks not to reproduce.
- `docs/reference_baseline.json`: Captured SHA-256 hashes for the three original reference files so later milestones can verify that the reference project remains unchanged.
- `docs/requirements_traceability.md`: Mapped AC-01 through AC-20 and each original user need to milestones and planned test evidence.
- `sample_data/canonical/README.md`: Documented fixture purpose, safety rules, files, and validation command.
- `sample_data/canonical/manifest.json`: Registered required Scenarios A–H.
- `sample_data/canonical/shared_locations.json`: Added seven fictional, non-sensitive locations.
- `sample_data/canonical/shared_matrix.json`: Added deterministic asymmetric road-distance and travel-duration test matrices.
- `sample_data/canonical/scenario_a_feasible_mixed.json`: Added the three-truck, mixed-task feasible acceptance case.
- `sample_data/canonical/scenario_b_capacity_impossible.json`: Added the capacity precheck case.
- `sample_data/canonical/scenario_c_deadline_impossible.json`: Added the individually impossible deadline and calculated earliest-completion case.
- `sample_data/canonical/scenario_d_collective_shortage.json`: Added the individually feasible but collectively infeasible three-truck case.
- `sample_data/canonical/scenario_e_pair_precedence.json`: Added same-vehicle pickup-before-delivery expectations.
- `sample_data/canonical/scenario_f_multiday_shifts.json`: Added one physical truck represented by two dated shifts.
- `sample_data/canonical/scenario_g_routing_failures.json`: Added authentication, rate-limit, server, partial-response, unreachable, and timeout cases.
- `sample_data/canonical/scenario_h_timezone_boundaries.json`: Added date-only, aware, invalid-order, and daylight-saving boundary cases.
- `scripts/validate_m0.py`: Added a standard-library-only validator for documents, traceability, hashes, JSON structure, matrix integrity, scenario semantics, and scenario-specific expectations.
- `project_plan.md`: Marked M0 completed after all gate checks passed.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python scripts/validate_m0.py` | PASS | 672 checks executed; Scenarios A–H loaded; AC-01 through AC-20 found; reference notes present. |
| `python -m py_compile scripts/validate_m0.py` | PASS | Validator has valid Python syntax. Generated bytecode cache was removed after the check. |
| JSON syntax and duplicate-key validation | PASS | Manifest, shared data, baseline, and all eight scenarios loaded through the M0 validator. |
| Matrix integrity | PASS | Square dimensions, nonnegative integers, zero diagonal, complete location mapping, and asymmetry checks passed. |
| Scenario semantics | PASS | IDs, references, positive quantities, task-type endpoints, aware datetimes, shifts, deadlines, and expectations passed. |
| Scenario C lower-bound calculation | PASS | Expected earliest completion and 2,000-second lateness reconcile with fixture matrix and service times. |
| Scenario D individual feasibility | PASS | All four tasks pass individual earliest-completion checks while fixture expectations require a partial three-truck plan. |
| Requirement-to-test traceability | PASS | Every acceptance criterion AC-01 through AC-20 maps to milestones and evidence. |
| Reference project baseline | PASS | Current README, application, and requirements SHA-256 hashes match the captured M0 baseline. |
| M0 deliverables reviewed | PASS | Approved plan, reference notes, canonical fixtures, decision/build record, traceability, and repeatable validator are present. |
| Application runtime tests | NOT RUN | Application runtime does not exist until M1; no runtime behavior was claimed in M0. |

### Decisions and assumptions

- Canonical solver fixtures use fictional locations and deterministic offline matrices so later tests remain reproducible and incur no Google charges.
- The shared matrix is intentionally asymmetric to prevent accidental assumptions that road travel is symmetric.
- Scenario C defines deadline feasibility against completion after service, not arrival alone.
- Scenario D asserts minimum scheduled/unscheduled counts instead of a specific dropped task because equivalent optimal diagnostic choices may exist.
- Provider and datetime failure fixtures are contract cases rather than solver scenarios.
- Fixture version `1.0` is the M0 baseline; contract changes in M2 must update fixture versions and this log when incompatible.

### Known issues

- A live Google API smoke test remains intentionally deferred to M3 and requires a restricted developer key.
- Canonical fixtures describe the approved contract before Pydantic models exist; M2 may add optional fields but must preserve or explicitly version existing required behavior.

### Gate status

- **M0 COMPLETE.**
- Approved plan: PASS.
- Reference behavior notes and immutable hash baseline: PASS.
- Canonical A–H fixtures: PASS.
- Requirement-to-test traceability: PASS.
- Repeatable validation and manual gate review: PASS.
- No unresolved requirement blocks project scaffolding.
- M1 remains not started.

### Next action

- Begin M1 by scaffolding the separated backend/frontend packages and quality tooling, then execute the M1 automated and manual gate checks before starting domain implementation.

---

## 2026-06-21 — Build 003 — M1 — Project scaffold and quality foundation complete

### Scope

- Create the separated FastAPI backend and Streamlit frontend package structure.
- Establish pinned project dependencies and an isolated Python 3.12 environment.
- Add backend configuration, health endpoint, frontend HTTP client, and graceful connectivity shell.
- Add an offline fake routing provider for later domain and solver development.
- Establish formatting, linting, strict typing, tests, startup scripts, and M1 smoke checks.
- Execute every M1 automated and manual gate check before changing milestone status.

### Changes

- `pyproject.toml`: Added exact direct runtime/development dependency pins, package discovery, pytest, Ruff, mypy, and coverage configuration.
- `.gitignore`: Added Python, tool-cache, virtual-environment, secret, database, log, and export exclusions.
- `.env.example`: Added safe runtime, backend, persistence, and placeholder Google settings without credentials.
- `README.md`: Added architecture boundary, Python 3.12 setup, separate backend/frontend commands, combined startup, configuration, and quality commands.
- `run_app.ps1`: Added a Windows launcher that starts the backend as a hidden helper, runs Streamlit in the current console, and cleans up the backend on exit.
- `backend/app/`: Added package boundaries for API, application, domain, diagnostics, optimization, persistence, and routing.
- `backend/app/config.py`: Added validated environment settings; a Google key is optional and excluded from object representation.
- `backend/app/logging_config.py`: Added minimal process logging setup.
- `backend/app/api/main.py`: Added the FastAPI application factory and ASGI app.
- `backend/app/api/routes/health.py`: Added the versioned `/api/v1/health` endpoint with a strict response model.
- `backend/app/routing/base.py`: Added provider-neutral location, options, matrix, provider protocol, and stable provider-error contracts.
- `backend/app/routing/fake.py`: Added deterministic, no-I/O geocoding and matrix behavior with call counters and controlled errors.
- `frontend/api_client.py`: Added an HTTP-only health client with safe unavailable, HTTP, JSON, and contract errors.
- `frontend/session_models.py`: Added a frontend-only draft-state placeholder without business logic.
- `frontend/streamlit_app.py`: Added the M1 shell, backend status, graceful offline warning, and no Google-key requirement.
- `backend/tests/` and `frontend/tests/`: Added 21 configuration, API, provider, matrix, package-boundary, client-failure, and Streamlit smoke tests.
- `scripts/smoke_m1.py`: Added process-level startup and health verification for FastAPI and Streamlit with the Google key removed from the test environment.
- `scripts/validate_m0.py`: Applied the project formatter and safe modernization fixes; all 672 M0 validation checks still pass.
- `.venv/`: Created the ignored isolated environment and installed the pinned application and development dependencies.
- `project_plan.md`: Marked M1 completed only after the gate evidence below passed.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Environment creation and editable install | PASS | Python 3.12.4 virtual environment created; all pinned runtime and development dependencies installed. |
| `python -m pip check` | PASS | No broken requirements found. |
| `python -m ruff format --check .` | PASS | 34 Python files already formatted at final check. |
| `python -m ruff check .` | PASS | All lint checks passed. |
| `python -m mypy backend frontend` | PASS | Strict typing reported no issues in 32 source files. |
| `python -m pytest` | PASS | 21 tests passed in 5.32 seconds. |
| Backend package import test | PASS | Every discovered `backend.app` module imported successfully. |
| Backend boundary test | PASS | No Streamlit references exist under `backend/app`. |
| Frontend boundary test | PASS | No OR-Tools, Google implementation, or `backend.app` imports exist in frontend Python files. |
| FastAPI health integration test | PASS | `/api/v1/health` returned the exact versioned contract without a Google key. |
| OpenAPI route test | PASS | `/api/v1/health` is present in generated OpenAPI paths. |
| Fake routing provider tests | PASS | Ordered geocoding, asymmetric matrix, protocol compatibility, call counts, missing configuration, mismatch, and invalid matrices tested. |
| Frontend API-client failure tests | PASS | Connection refusal, HTTP failure, invalid JSON, incomplete fields, and unhealthy response are controlled. |
| Streamlit AppTest | PASS | Frontend executes with an unavailable backend and renders the expected warning without an exception. |
| `python scripts/smoke_m1.py` | PASS | Real FastAPI and Streamlit processes started and passed health probes on ports 8765 and 8766 with `GOOGLE_MAPS_API_KEY` removed. |
| In-app browser manual check | PASS | Frontend title/status rendered at port 8767; unavailable-backend warnings were visible; no browser console errors were reported. |
| Smoke-process cleanup | PASS | No listeners remained on ports 8765, 8766, or 8767. |
| `run_app.ps1` parser check | PASS | PowerShell parser reported no syntax errors. |
| Secret/generated ignore verification | PASS | Required patterns passed unit validation and real `git check-ignore` evaluation in a temporary repository. |
| M0 regression | PASS | `python scripts/validate_m0.py` passed all 672 checks after project-wide formatting. |

### Decisions and assumptions

- A single root `pyproject.toml` manages one reproducible environment for both packages, while runtime separation remains HTTP-only. This avoids dependency drift without coupling frontend code to backend implementation.
- Direct dependencies are exactly pinned. The environment is installed editable so local package imports match development behavior.
- Python support is initially constrained to 3.12 to match the verified Windows environment and pinned binary dependencies.
- Pydantic Settings owns backend environment loading; no Google key is required before M3.
- The fake provider contract is provider-neutral and asynchronous so later Google I/O can implement the same boundary.
- The M1 error-handler registration hook is intentionally present but behavior remains minimal until the structured API error work in M6.
- The frontend imports only its own HTTP client; it does not share backend Pydantic models in-process.

### Known issues

- The workspace is not currently initialized as a Git repository. Ignore behavior was therefore validated in a temporary Git repository; this does not block M2.
- Google geocoding and route-matrix behavior remain intentionally unimplemented until M3.
- The Streamlit application is intentionally a connectivity shell; fleet and PO workflow pages begin after backend contracts stabilize.
- A live Google smoke test still requires a restricted developer key in M3.

### Gate status

- **M1 COMPLETE.**
- Backend/frontend package structure: PASS.
- Pinned dependency configuration and isolated environment: PASS.
- `.gitignore`, `.env.example`, base README, and startup script: PASS.
- Ruff, pytest, and strict mypy foundation: PASS.
- Backend health endpoint and frontend connectivity behavior: PASS.
- Test fake routing provider: PASS.
- Backend contains no Streamlit dependency: PASS.
- Frontend contains no solver or Google implementation: PASS.
- Windows PowerShell startup and checks: PASS.
- M2 remains not started.

### Next action

- Begin M2 by implementing the Pydantic/domain contracts, task-expansion rules, timezone/date-only normalization, import-column mapping, and row-level validation format against canonical Scenarios A, B, and H.

---

## 2026-06-21 — Build 004 — M2 — Domain contracts and validation complete

### Scope

- Implement provider-, transport-, UI-, database-, and solver-independent domain contracts.
- Normalize all internal datetimes to UTC while preserving explicit local-time confirmation.
- Define deterministic date-only and daylight-saving behavior.
- Define CSV/XLSX task-column aliases and row mapping without coupling the domain to file-reading libraries.
- Expand every user-facing task into balanced internal pickup/delivery nodes.
- Return stable row/field validation issues and verify canonical Scenarios A, B, and H.
- Execute the M2 gate and all previous milestone regressions.

### Changes

- `backend/app/domain/enums.py`: Added task, deadline, geocode, routing, plan, stop, severity, and stable validation-code enumerations.
- `backend/app/domain/models.py`: Added immutable Pydantic contracts for location, vehicle, vehicle shift, planning horizon, task, matrix element issue, routing matrix, and planning request.
- `backend/app/domain/results.py`: Added validation issue/result and public plan stop, route, diagnostic, and plan-result contracts.
- `backend/app/domain/time_normalization.py`: Added IANA timezone validation, strict naive-time localization, UTC normalization, date-only shift-boundary handling, and ambiguous/nonexistent DST rejection.
- `backend/app/domain/import_contract.py`: Added canonical task columns, case/spacing normalization, human-friendly aliases, task/due-event value aliases, defaults, unknown-column reporting, and duplicate-column rejection.
- `backend/app/domain/validation.py`: Added collection parsing, datetime normalization, row-level errors/warnings, duplicate handling, task endpoint rules, capacity precheck, horizon checks, matrix checks, normalized request creation, and business-readable local/UTC payload output.
- `backend/app/domain/__init__.py`: Exported the stable M2 public contracts and validation entry points.
- `backend/app/optimization/task_expander.py`: Added deterministic pickup/delivery node expansion, internal load deltas, plant-node flags, service seconds, readiness, and completion-deadline attachment.
- `backend/app/optimization/__init__.py`: Exported task-expansion contracts and functions.
- `backend/app/routing/base.py`: Reused the canonical domain routing-matrix model while preserving the M1 `RouteMatrix` compatibility alias and provider-neutral interface.
- `docs/import_contract.md`: Documented canonical CSV/XLSX columns, accepted aliases, datetime behavior, duplicate PO policy, quantity precision, and internal load signs.
- `backend/tests/fixtures/canonical.py`: Added canonical fixture embedding for M2 tests.
- `backend/tests/unit/domain/`: Added 33 pure-domain tests covering validation, time normalization, import mapping, task expansion, contract JSON round-trips, and infrastructure boundaries.
- `scripts/review_m2_payloads.py`: Added a repeatable business-readable Scenario A preview and Scenario B diagnostic review.
- `backend/tests/unit/test_fake_routing_provider.py`: Updated the negative-matrix assertion to the centralized Pydantic contract wording; rejection behavior is unchanged.
- `README.md`: Updated project status to M2 complete.
- `project_plan.md`: Marked M2 completed only after the gate evidence below passed.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 51 Python files already formatted. |
| `python -m ruff check .` | PASS | All lint checks passed. |
| `python -m mypy backend frontend` | PASS | Strict typing reported no issues in 48 source files. |
| `python -m pytest backend/tests/unit/domain -q` | PASS | 33 pure-domain tests passed in 0.45 seconds. |
| Domain infrastructure-boundary tests | PASS | Domain/task-expansion code and domain tests contain no FastAPI, Streamlit, SQLite, HTTP client, requests, or urllib imports. |
| `python -m pytest -q` | PASS | All 54 backend/frontend tests passed in 4.12 seconds. |
| Valid pickup/drop/pickup-drop contracts | PASS | Canonical Scenario A normalizes all three task types with positive quantities and aware UTC datetimes. |
| Missing address and type/location mismatch | PASS | Both produce blocking row/field issues; mismatch uses `TASK_TYPE_LOCATION_MISMATCH`. |
| Duplicate task and PO handling | PASS | Duplicate task ID is a blocking row error; duplicate PO is allowed with a row warning. |
| Quantity validation | PASS | Zero/negative values rejected; positive values with up to three decimal places accepted; greater precision rejected. |
| Ready/due ordering | PASS | `ready_at > due_at` returns stable `READY_AFTER_DUE`. |
| Date-only normalization | PASS | Ready date uses earliest enabled shift start; due date uses latest enabled shift end; both produce explicit warnings. |
| DST boundaries | PASS | Canonical Scenario H aware conversion passed; ambiguous and nonexistent Toronto local times were rejected with stable codes. |
| JSON public-contract round-trip | PASS | Location, vehicle, shift, task, matrix, horizon, request, validation, stop, route, diagnostic, and plan result round-tripped. |
| Task expansion | PASS | All task types produce same-task pickup/delivery pairs with equal opposite internal loads, correct plant-node flags, service seconds, and selected completion deadline. |
| `python scripts/review_m2_payloads.py` | PASS | Six Scenario A lines displayed positive quantity, local ready/due, and explicit deadline event; Scenario B displayed row/task-specific capacity diagnostics. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks still pass. |
| `python scripts/smoke_m1.py` | PASS | FastAPI and Streamlit process health regression passed without a Google key; helper processes cleaned up. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- `task_id` is unique and identifies one movement line. A repeated `task_id` is an error.
- `po_number` may repeat because one PO can contain multiple movement lines. Later repeated rows receive a warning, not an error.
- User-facing quantities and vehicle capacities are positive decimals with at most three decimal places. Signed demand exists only inside expanded solver nodes.
- Tasks reference location IDs; addresses belong to the location table so repeated addresses can be geocoded and deduplicated once in M3.
- All domain datetimes are aware and stored in UTC. The selected plant timezone is used for parsing naive input and generating confirmation fields.
- Date-only ready values normalize to the earliest enabled truck-shift start on that local date. Date-only due values normalize to the latest enabled truck-shift end on that date. No matching shift is a blocking error.
- Ambiguous or nonexistent local times are rejected rather than guessed. Users must supply a valid explicit datetime/offset.
- Every business task expands to one pickup and one delivery node. A plant-origin drop receives an internal plant pickup node; a plant-destination pickup receives an internal plant delivery node.
- The hard deadline attaches to completion of the selected event. M5 will convert that completion bound to the corresponding latest service-arrival constraint.
- `due_event` defaults to `DELIVERY_COMPLETE`, matching the approved inbound-arrival/final-drop default; pickup completion remains explicitly selectable.
- Unknown import columns are ignored with warnings. Multiple source headers mapping to one canonical field are blocking because the intended value is ambiguous.

### Known issues

- CSV/XLSX file byte parsing is intentionally not in the domain layer; M7 adapters will convert files to row dictionaries before using this contract.
- Google address resolution and road matrices remain intentionally unimplemented until M3.
- Vehicle-tag compatibility is represented in contracts but its feasibility precheck is implemented with solver eligibility work in M4/M5.
- Aggregate route-result consistency is represented but independent route-result validation is implemented in M4.

### Gate status

- **M2 COMPLETE.**
- Location, task, vehicle, shift, matrix, request, and result contracts: PASS.
- Task-expansion rules: PASS.
- Timezone, date-only, and DST normalization: PASS.
- CSV/XLSX column-mapping contract: PASS.
- Row-level validation result format: PASS.
- Canonical and error-path checks: PASS.
- Business-readable manual review: PASS.
- Domain tests are infrastructure-independent: PASS.
- Node expansion and completion-deadline semantics are explicitly documented with no open ambiguity.
- M3 remains not started.

### Next action

- Begin M3 by implementing the Google geocoding/Routes provider, bounded retries, batching and response validation, persistent versioned matrix cache, matrix-request estimator, and mocked HTTP tests against canonical Scenario G.

---

## 2026-06-21 — Build 005 — M3 — Offline implementation complete; live gate pending

### Scope

- Implement the Google Geocoding and Routes Compute Route Matrix adapters.
- Add bounded retries, exponential backoff with jitter, batching, strict response assembly, and stable failure codes.
- Add a persistent versioned SQLite matrix cache and deterministic secret-free cache keys.
- Add matrix request estimation and provider construction from validated backend settings.
- Verify all Scenario G and cache behavior through mocked HTTP before any live Google call.
- Prepare a restricted live smoke script that never prints secrets or full provider responses.

### Changes

- `.env.example`: Added documented Google endpoints, retry/timeout limits, matrix batching limits, cache TTL, and departure-bucket settings.
- `backend/app/config.py`: Added validated M3 routing, quota-safe batching, timeout, retry, and cache settings; the API key remains excluded from representation.
- `backend/app/routing/base.py`: Added provider name and optional aware departure time to the provider-neutral contract.
- `backend/app/routing/errors.py`: Added stable routing error codes and a reusable secret-redaction helper.
- `backend/app/routing/estimator.py`: Added rectangular batch planning and pre-call matrix element/request estimates, including the lower traffic-aware-optimal element limit.
- `backend/app/routing/google.py`: Added duplicate-address geocoding, Google status mapping, bounded HTTP/API retries, request headers/field mask, batch request generation, complete matrix reassembly, asymmetric distance/duration preservation, duration rounding, unreachable detection, and fail-closed response validation.
- `backend/app/routing/factory.py`: Added production Google provider construction from backend settings with explicit missing-key failure.
- `backend/app/routing/fake.py`: Added stable provider name for cache-key compatibility.
- `backend/app/routing/__init__.py`: Exported M3 provider, errors, estimator, limits, batching, factory, and redaction contracts.
- `backend/app/persistence/database.py`: Added short-lived transactional SQLite connection handling.
- `backend/app/persistence/matrix_cache.py`: Added versioned cache schema, expiry and corrupt-payload invalidation, atomic upsert, expiry cleanup, departure bucketing, and SHA-256 cache keys over ordered coordinates/options without credentials.
- `backend/app/application/routing_service.py`: Added cache miss/hit/refresh orchestration and cache metadata result.
- `scripts/live_smoke_m3.py`: Added a restricted two-public-address geocode and 2x2 road-matrix smoke test with summary-only output.
- `docs/google_api_setup.md`: Documented required APIs, key restrictions, local secret storage, live command, production separation, and official Google references.
- `backend/tests/unit/routing/` and `backend/tests/integration/routing/`: Added 29 warning-free estimator, batching, mocked Google, retry, failure, redaction, cache, schema, expiry, and HTTP/cache integration tests.
- Existing configuration and API tests now disable `.env` loading explicitly so developer credentials cannot affect assertions.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Google credential presence check | PASS | `.env` and a nonempty `GOOGLE_MAPS_API_KEY` were detected without printing the value. |
| Official API contract review | PASS | Google Routes setup/Compute Route Matrix, Geocoding requests, limits, statuses, and security guidance reviewed. |
| `python -m ruff check .` | PASS | All lint checks passed. |
| `python -m mypy backend frontend` | PASS | Strict typing reported no issues in 61 source files. |
| Focused M3 suite | PASS | 29 routing/cache tests passed without warnings. |
| Full suite | PASS | All 83 backend/frontend tests passed in 4.63 seconds. |
| Geocoding success and deduplication | PASS | Equivalent addresses generated one mocked HTTP call and results preserved input order. |
| Matrix success/asymmetry | PASS | Mocked Google road distances and durations remained asymmetric and correctly ordered. |
| HTTP cache integration | PASS | First matrix request called mocked Google once; second identical request was a SQLite cache hit with no second HTTP call. |
| Routing-option and expiry invalidation | PASS | Changed preference produced a new key; expired entries were deleted and recomputed. |
| Batch reassembly | PASS | Small configured limits forced nine requests and reconstructed a complete ordered 5x5 matrix. |
| Retry behavior | PASS | HTTP 429/503, API quota status, and timeout retries were bounded with expected backoff attempts. |
| Authentication behavior | PASS | HTTP 403 failed on the first attempt with `ROUTING_AUTH_ERROR`. |
| Malformed/partial/unreachable behavior | PASS | Invalid JSON, wrong shape, missing elements, duplicate indexes, malformed geocodes, and unreachable routes failed closed. |
| Secret redaction | PASS | Key absent from provider representation, stable exception text, logs, cache keys, and suppressed request exception traceback. |
| Canonical Scenario G alignment | PASS | Every fixture error code is represented by the routing error taxonomy. |
| SQLite cache safety | PASS | Schema mismatch, expiry, and corrupt payload all became safe cache misses; no invalid matrix was returned. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks still pass. |
| `python scripts/smoke_m1.py` | PASS | FastAPI/Streamlit process regression passed and helper listeners were cleaned up. |
| `python -m pip check` | PASS | No broken requirements found. |
| `python scripts/live_smoke_m3.py` | NOT RUN | Deliberately withheld pending rotation of a credential exposed by an environment-isolation test failure. |

### Decisions and assumptions

- New work uses Geocoding API and Routes API `computeRouteMatrix`; the legacy Distance Matrix API is never called.
- Geocoding deduplicates normalized addresses within a request and preserves caller order.
- Matrix locations must have unique IDs; callers deduplicate physical locations before requesting a matrix.
- Production matrix behavior is fail-closed. There is no geodesic, straight-line, partial-matrix, or stale-incompatible fallback.
- Default batch limits are conservatively configurable at 25 origins, 25 destinations, and 625 elements; traffic-aware-optimal requests use a maximum of 100 elements.
- Fractional Google protobuf durations round upward to whole seconds so planning does not understate travel time.
- HTTP 401/403 and invalid requests do not retry. Rate limits, timeouts, network failures, and server errors use bounded retries.
- Cache keys include schema version, provider, ordered place/coordinate identity, routing options, and departure bucket. They never contain addresses or credentials.
- Complete validated matrices only are cached. Cache corruption, expiry, and schema mismatch are misses.
- The live smoke uses two public Toronto-area addresses and prints only counts/pass criteria.

### Known issues

- During the first full-suite run, an older configuration test loaded the local `.env` and its failed assertion echoed the development credential in local test output. The test was corrected to disable `.env` loading, and traceback redaction tests were added. The exposed development key must be rotated before any live call.
- The live Google geocoding and 2x2 Routes matrix smoke check remains pending that rotated restricted key.
- Persistent geocode caching is not part of the M3 gate; duplicate addresses are deduplicated per request. Matrix caching is persistent and versioned.

### Gate status

- **M3 IN PROGRESS.**
- Provider interface and fake provider: PASS.
- Google geocoding adapter: PASS offline mocked contract.
- Google Routes matrix adapter: PASS offline mocked contract.
- Batching, retries, validation, and error mapping: PASS.
- Versioned SQLite matrix cache and estimator: PASS.
- Mocked suite and all regressions: PASS.
- No silent straight-line fallback: PASS.
- Restricted live Google smoke: PENDING ROTATED KEY.
- M3 must not be marked complete until the live smoke passes with the rotated key.

### Next action

- Rotate the exposed development key in Google Cloud, update the ignored `.env`, and run `python scripts/live_smoke_m3.py`. If it passes, rerun the complete gate, mark M3 complete, and move the pointer to M4.

---

## 2026-06-21 — Build 006 — M3 — Live API authorization check

### Scope

- Execute the restricted live M3 smoke test using the configured development key after explicit user approval.
- Test Routes independently if the combined Geocoding and Routes smoke test fails.
- Record only sanitized provider results; do not print the credential, coordinates, or full responses.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python scripts/live_smoke_m3.py` | FAIL | Google received the request, but Geocoding returned `REQUEST_DENIED` / `ROUTING_AUTH_ERROR`. |
| Sanitized Geocoding diagnostic | FAIL | Google reported that the key is not authorized for the requested API/service and directed the caller to check enabled APIs and key API restrictions. |
| Independent Routes `computeRouteMatrix` request | PASS | The same key returned HTTP 200 for a fixed-coordinate route-matrix request. |
| Credential output safety | PASS | No credential value was printed by the smoke test or diagnostics. |

### Conclusion

- The caller IP restriction is not the current blocker because the Routes API accepted a request from the same process, network, public IP, and key.
- The key currently authorizes Routes API but not Geocoding API. Enable Geocoding API in the key's Google Cloud project and include **Geocoding API** under the key's API restrictions.
- Allow a few minutes for Google Cloud configuration propagation, then rerun the combined live smoke.

### Gate status

- **M3 IN PROGRESS.**
- Live Routes API check: PASS.
- Live Geocoding API check: BLOCKED BY GOOGLE CLOUD KEY/API CONFIGURATION.
- Combined two-address Geocoding and 2x2 matrix gate: NOT PASSED.

### Next action

- In Google Cloud Console, enable **Geocoding API** and ensure the development key's API restriction list contains both **Routes API** and **Geocoding API**. No new key is required for this configuration correction. Rerun `python scripts/live_smoke_m3.py` after the change propagates.

---

## 2026-06-21 — Build 007 — M3 — Live gate passed and milestone complete

### Scope

- Recheck the combined live Google Geocoding and Routes matrix flow after Geocoding API authorization was enabled.
- Diagnose and support Google's valid omission of protobuf default-valued `distanceMeters` on zero-distance matrix diagonal elements.
- Rerun the complete M3 quality and regression gate.

### Changes

- `backend/app/routing/google.py`: Treat an omitted `distanceMeters` as zero only when the element is on the true global matrix diagonal, has zero duration, and has already passed route-condition validation.
- `backend/tests/integration/routing/test_google_provider.py`: Added regression coverage for Google's omitted diagonal zero distance and confirmed the same omission remains invalid off the diagonal.
- `README.md` and `project_plan.md`: Marked M3 complete and identified M4 as the next milestone.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Live Geocoding API | PASS | Two public Toronto-area addresses resolved without logging addresses, coordinates, responses, or credentials. |
| Live Routes `computeRouteMatrix` | PASS | A complete 2x2 matrix returned positive off-diagonal road distance and duration. |
| `python scripts/live_smoke_m3.py` | PASS | Combined restricted live M3 smoke passed after Google configuration propagation. |
| Focused Google provider suite | PASS | 21 tests passed, including valid omitted diagonal zero distance and invalid off-diagonal omission. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 61 source files. |
| Full test suite | PASS | 85 tests passed in 5.46 seconds. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/smoke_m1.py` | PASS | FastAPI and Streamlit process regression passed without exposing or requiring the Google key. |
| `python -m pip check` | PASS | No broken requirements found. |
| Credential output safety | PASS | The key was not printed by live checks or diagnostics. |

### Gate status

- **M3 COMPLETE.**
- Provider interface and fake provider: PASS.
- Live Google Geocoding adapter: PASS.
- Live Google Routes matrix adapter: PASS.
- Batching, bounded retries, strict validation, and stable errors: PASS.
- Versioned SQLite matrix cache and request estimator: PASS.
- Secret redaction and backend-only credential boundary: PASS.
- No silent straight-line production fallback: PASS.
- Complete offline, live, and regression gates: PASS.

### Next action

- Begin M4 by implementing the OR-Tools capacity and pickup-delivery solver with deterministic settings and an independent result validator.

---

## 2026-06-22 — Build 008 — M4 — Core solver and validator complete

### Scope

- Implement the backend-only OR-Tools core solver for capacity and pickup-delivery routing.
- Keep solver implementation separate from frontend code and behind an application-service boundary.
- Add independent plan-result validation so invalid extracted routes are not returned as successful plans.
- Verify M4 acceptance behavior with deterministic fake/offline matrices.

### Changes

- `backend/app/optimization/solver.py`: Added `OrToolsCapacitySolver` with integer load units, enabled-shift filtering, compatible-vehicle capacity prechecks, same-vehicle pickup/delivery constraints, pickup-before-delivery ordering, capacity and route-duration dimensions, plant/configured depot starts and ends, fixed vehicle costs, deterministic first-solution settings, solution extraction, and validation-before-return.
- `backend/app/optimization/validator.py`: Added independent route-result validation for task uniqueness, pair order, same-route pairing, nonnegative/within-capacity loads, readiness waits, shift bounds, depot rules, route totals, plan totals, due/slack consistency, and corrupted-result detection.
- `backend/app/application/planning_service.py`: Added a thin backend application-service boundary so API/UI code can call planning without importing OR-Tools details.
- `backend/app/optimization/__init__.py`: Kept the package initializer lightweight so task expansion and M2 utilities do not eagerly load OR-Tools.
- `backend/tests/unit/optimization/test_solver_m4.py`: Added M4 regression tests for one pickup, one plant-origin drop, pickup-drop pair precedence, mixed tasks with three trucks available, load bounds, exact-capacity feasibility, over-capacity rejection, depot/totals consistency, deterministic repeated runs, and validator rejection of corrupted capacity state.
- `README.md` and `project_plan.md`: Marked M4 complete and identified M5 as the next milestone.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Focused M4 solver suite | PASS | `python -m pytest backend/tests/unit/optimization -q`: 10 tests passed. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 66 source files. |
| Full test suite | PASS | `python -m pytest -q`: 95 tests passed in 5.40 seconds. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/smoke_m1.py` | PASS | FastAPI and Streamlit process regression passed without requiring a Google key. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A payload and Scenario B capacity diagnostic remained correct; OR-Tools is no longer eagerly loaded by this review path. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- M4 intentionally enforces capacity, pairing, pickup-before-delivery, depot behavior, and route-duration limits only. Hard ready/due time-window feasibility and user-facing infeasibility diagnostics remain in M5, matching the approved milestone split.
- User-facing load decimals are converted to integer thousandths inside the solver to avoid floating-point capacity drift.
- The optimization package initializer stays lightweight; code that needs OR-Tools imports `backend.app.optimization.solver` directly.

### Known issues

- Pytest reports third-party OR-Tools/SWIG deprecation warnings during import. These are non-blocking library warnings and do not affect route behavior.

### Gate status

- **M4 COMPLETE.**
- Task-to-node expansion reused and covered: PASS.
- OR-Tools routing model with capacity dimension: PASS.
- Pickup/delivery same-vehicle and order constraints: PASS.
- Plant/configured depot start/end behavior: PASS.
- Basic deterministic objective/settings: PASS.
- Independent result validator: PASS.
- Core solver regression gate: PASS.

### Next action

- Begin M5 by adding time-window dimensions, hard ready/deadline enforcement, and infeasibility diagnostics for late or impossible pickups.

---

## 2026-06-22 — Build 009 — M5 — Time windows and diagnostics complete

### Scope

- Upgrade the backend solver from structural CVRP/PDP constraints to hard ready-time, deadline, and shift-safe routing.
- Add static earliest-completion diagnostics for individually impossible deadlines.
- Add relaxed diagnostic solving that can safely return partial feasible plans when the full workload is collectively infeasible.
- Verify multi-day vehicle-shift behavior and ensure returned strict/partial plans contain no late task.

### Changes

- `backend/app/optimization/solver.py`: Added a hard OR-Tools `Time` dimension with service-time transit, waiting slack, per-shift start/end bounds, per-node ready lower bounds, and completion-deadline upper bounds based on `due_at - service_seconds`.
- `backend/app/optimization/solver.py`: Added individual earliest-completion prechecks that return `DEADLINE_IMPOSSIBLE_INDIVIDUALLY` with estimated completion and `late_by_seconds`, plus `NO_COMPATIBLE_SHIFT_TIME` when a task cannot fit inside any compatible shift.
- `backend/app/optimization/solver.py`: Added relaxed diagnostic solving with paired-node disjunctions so pickup/delivery nodes are dropped together; unscheduled feasible tasks receive `INSUFFICIENT_COMBINED_FLEET_TIME`.
- `backend/app/optimization/solver.py`: Added multi-day shift-safe extraction from the time dimension and distinct timeout/infeasibility status mapping.
- `backend/app/optimization/validator.py`: Upgraded independent validation for both `FEASIBLE` and `PARTIALLY_FEASIBLE` plans, including task partitioning, hard-deadline slack, shift bounds, readiness waits, pair order, same-route pairing, load, and totals.
- `backend/tests/unit/optimization/test_solver_m5.py`: Added M5 regression coverage for waiting before readiness, exact deadline boundary, one-second deadline miss, service-included completion, shift-end infeasibility, next-day compatible assignment, no post-due reassignment, physical-truck multi-day shifts, Scenario C diagnostics, Scenario D partial plans, paired-node dropping, and timeout status mapping.
- `README.md` and `project_plan.md`: Marked M5 complete and identified M6 as the next milestone.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Focused optimization suite | PASS | `python -m pytest backend/tests/unit/optimization -q`: 22 tests passed. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 67 source files. |
| Full test suite | PASS | `python -m pytest -q`: 107 tests passed in 5.17 seconds. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/smoke_m1.py` | PASS | FastAPI and Streamlit process regression passed without requiring a Google key. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A payload and Scenario B capacity diagnostic remained correct. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- A hard deadline is enforced against completion/departure from the selected due node, not arrival. Internally the solver applies `latest_service_start = due_at - service_seconds`.
- Strict solve keeps all tasks mandatory. If strict solve is infeasible and does not time out, a relaxed diagnostic solve allows paired task nodes to be dropped together while preserving capacity, precedence, shift, and hard deadline safety for returned routes.
- A partial diagnostic result is valid only when scheduled and unscheduled task IDs partition the request and all returned scheduled stops pass independent validation.
- M5 remains backend-only; no deadline logic was added to the frontend.

### Known issues

- Pytest still reports third-party OR-Tools/SWIG deprecation warnings during import. These are non-blocking library warnings and do not affect route behavior.

### Gate status

- **M5 COMPLETE.**
- Time dimension with service and waiting: PASS.
- Ready-time and completion-deadline enforcement: PASS.
- Multi-day vehicle-shift behavior: PASS.
- Route-duration and shift-end safety: PASS.
- Static earliest-completion diagnostics: PASS.
- Strict solve plus relaxed partial diagnostic solve: PASS.
- Distinct timeout/infeasibility status handling: PASS.
- Returned strict and partial plans independently validated: PASS.

### Next action

- Begin M6 by exposing the validated planning workflow through versioned FastAPI endpoints and application-service dependency injection.

---

## 2026-06-22 — Build 010 — M6 — FastAPI application service complete

### Scope

- Expose the validated backend workflow through versioned FastAPI endpoints without requiring Streamlit.
- Add dependency injection for routing providers, routing service, planning service, matrix cache, and local repositories.
- Add structured API errors, request IDs, OpenAPI coverage, request-size/row-count limits, and SQLite scenario/plan persistence.
- Verify success, expected failure, unexpected failure, persistence, rollback, concurrent reads, and OpenAPI behavior.

### Changes

- `backend/app/api/contracts.py`: Added versioned API request/response contracts for geocoding, matrix calculation, validation, solve, scenario retrieval, plan retrieval, export, and structured error envelopes.
- `backend/app/api/middleware.py`: Added request-ID attachment/echoing and coarse body-size enforcement using `X-Request-ID` and `X-Request-ID` response headers.
- `backend/app/api/error_handlers.py`: Added controlled handlers for API errors, provider errors, request validation errors, HTTP errors, and unexpected backend errors without traceback/secret leakage.
- `backend/app/api/dependencies.py`: Added dependency providers for database, scenario repository, plan repository, routing provider, matrix cache, routing service, and planning service.
- `backend/app/api/routes/routing.py`: Added `POST /api/v1/locations/geocode` and `POST /api/v1/matrices/compute`.
- `backend/app/api/routes/plans.py`: Added `POST /api/v1/plans/validate`, `POST /api/v1/plans/solve`, `GET /api/v1/plans/{plan_id}`, and `GET /api/v1/plans/{plan_id}/export`.
- `backend/app/api/routes/scenarios.py`: Added `POST /api/v1/scenarios`, `PUT /api/v1/scenarios/{scenario_id}`, and `GET /api/v1/scenarios/{scenario_id}`.
- `backend/app/persistence/scenario_repository.py`: Added SQLite scenario and plan repositories with atomic writes and validated `PlanResult` retrieval.
- `backend/app/config.py`: Added solver time-limit and API request/row-count limit settings.
- `backend/tests/integration/test_m6_api.py`: Added M6 endpoint workflow, structured error, request-ID, persistence, rollback, concurrent-read, body-limit, and OpenAPI contract tests.
- `README.md` and `project_plan.md`: Marked M6 complete and identified M7 as the next milestone.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Focused M6 API suite | PASS | `python -m pytest backend/tests/integration/test_m6_api.py -q`: 9 tests passed. |
| Focused API/persistence lint | PASS | `python -m ruff check backend/app/api backend/app/persistence backend/tests/integration/test_m6_api.py`: all checks passed. |
| Focused API/persistence type check | PASS | `python -m mypy backend/app/api backend/app/persistence backend/tests/integration/test_m6_api.py`: no issues in 16 source files. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 74 source files. |
| Full test suite | PASS | `python -m pytest -q`: 116 tests passed in 6.28 seconds. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/smoke_m1.py` | PASS | FastAPI and Streamlit process regression passed without requiring a Google key. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A payload and Scenario B capacity diagnostic remained correct. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- `POST /api/v1/plans/validate` returns validation results with HTTP 200 so the frontend can preview row issues.
- `POST /api/v1/plans/solve` returns HTTP 422 for invalid payloads and persists successful solver results, including infeasible/partial `PlanResult` statuses produced by the solver.
- `GET /api/v1/plans/{plan_id}/export` returns JSON route/diagnostic rows in M6. CSV/XLSX file generation remains in M8.
- Geocode and matrix endpoints use the routing-provider abstraction; tests inject the fake provider and production uses the configured Google provider.
- Repository reads/writes use short-lived SQLite connections, and transaction rollback remains centralized in `SQLiteDatabase`.

### Known issues

- Pytest still reports third-party OR-Tools/SWIG deprecation warnings during import. These are non-blocking library warnings and do not affect API behavior.

### Gate status

- **M6 COMPLETE.**
- Versioned endpoints and application orchestration: PASS.
- Dependency injection for routing provider, repositories, and solver: PASS.
- Structured errors and request IDs: PASS.
- OpenAPI schema generation and route coverage: PASS.
- Scenario and plan repositories: PASS.
- API-level validation, size limits, and persistence tests: PASS.
- Endpoints work without Streamlit and without a Google key when using fake/test dependencies: PASS.

### Next action

- Begin M7 by building the Streamlit planning workflow on top of the new HTTP API client and versioned endpoint contracts.

---

## 2026-06-22 — Build 011 — M7 — Streamlit planning workflow complete

### Scope

- Build the planner-facing Streamlit workflow on top of the versioned HTTP API.
- Keep the frontend replaceable by avoiding backend implementation imports.
- Add explicit validation, matrix, and solve stages with stale-state protection.
- Add task CSV/XLSX import preview, route/result tables, diagnostics, and user-friendly API/provider errors.
- Verify the UI starts without a Google key and does not make matrix calls on rerun.

### Changes

- `frontend/streamlit_app.py`: Replaced the M1 shell with Setup, Fleet, Tasks & import, Validation, Matrix, Optimization, and Results tabs; added canonical sample loading, backend status, validation preview, matrix activation/calculation buttons, optimization action, result metrics, route stop table, diagnostic table, stale-state warnings, and flash/rerun behavior that immediately unlocks the next workflow stage.
- `frontend/api_client.py`: Expanded the HTTP-only client with typed health, validation, matrix, solve, plan retrieval, export, structured API error, timeout, and backend-unavailable handling.
- `frontend/session_models.py`: Added deterministic validation, location, and task fingerprints plus workflow status helpers so location edits invalidate validation/matrix/plan, due-date edits invalidate validation/plan but not an address-identical matrix, and stale plans are hidden.
- `frontend/import_preview.py`: Added frontend-only CSV/XLSX task import preview with alias mapping, unknown-column warnings, duplicate-column errors, missing-column errors, and row-level required-cell errors.
- `frontend/tests/`: Added M7 coverage for API-client success/error/timeout/outage behavior, import preview issue mapping, workflow invalidation rules, solve enablement rules, stale plan hiding, sample loading, Streamlit startup, and a Streamlit AppTest click-through for validate -> matrix -> solve.
- `README.md` and `project_plan.md`: Marked M7 complete and identified M8 as the next milestone.
- Applied `ruff format .` to bring existing source files and the new M7 files into compliance with the documented format check.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 81 files already formatted after mechanical formatting. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 77 source files. |
| Full test suite | PASS | `python -m pytest -q`: 129 tests passed; 3 third-party OR-Tools/SWIG deprecation warnings. |
| Focused frontend suite | PASS | `python -m pytest frontend/tests -q`: 20 tests passed during M7 development. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A normalized rows and Scenario B capacity diagnostic remained correct. |
| `python scripts/smoke_m1.py` | PASS | Real FastAPI and Streamlit processes started without a Google key; helper processes cleaned up. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- The UI never asks for a Google key. Credentials remain backend-only through environment configuration.
- Matrix calculation remains an explicit planner action. Loading the app, editing fields, validating, or rerunning Streamlit does not trigger a billable matrix call.
- M7 import is a preview and issue-mapping workflow. Applying imported rows into the scenario editor remains a future enhancement after save/load/export work.
- Sample Scenario A uses the deterministic fixture matrix so the primary workflow can be demonstrated without provider cost.
- Validation freshness tracks editable planning inputs, while matrix freshness tracks location/routing inputs and plan freshness tracks task/fleet inputs plus current matrix state.

### Known issues

- Pytest still reports third-party OR-Tools/SWIG deprecation warnings during import. These are non-blocking library warnings.
- The historical startup script remains named `smoke_m1.py`, but it continues to serve as the real backend + Streamlit process smoke check for later milestones.
- Maps, CSV/XLSX export files, save/load UI controls, and detailed stop sheets are intentionally deferred to M8.

### Gate status

- **M7 COMPLETE.**
- Setup, fleet, task, validation, matrix, optimization, and result pages: PASS.
- CSV/XLSX import preview with visible column/row issues: PASS.
- Backend API client with typed success, validation-error, timeout, and outage handling: PASS.
- State invalidation rules for locations, due dates, matrix, and stale plans: PASS.
- Solve disabled until current validation and matrix steps succeed: PASS.
- Route/diagnostic result tables and feasible/infeasible summary cues: PASS.
- Backend availability and provider/API errors displayed safely: PASS.
- Frontend/backend boundary remains HTTP-only: PASS.
- UI starts without direct API-key entry: PASS.

### Next action

- Begin M8 by adding route maps, CSV/XLSX exports, save/load scenario controls, and detailed plan sheets on top of the M7 workflow.

---

## 2026-06-26 — Build 012 — M8 — Maps, exports, and scenario persistence complete

### Scope

- Add route-map data shaping and Streamlit map rendering for backend route order.
- Add route/diagnostic CSV exports and a multi-sheet XLSX plan workbook.
- Add save/load scenario controls to the Streamlit setup workflow.
- Ensure exports include unscheduled tasks, preserve timezone-labelled datetimes, and escape formula-like cells.
- Verify empty/partial plans, duplicate-coordinate map markers, and save/load round-trip behavior.

### Changes

- `frontend/route_map.py`: Added map-data shaping with backend stop order preservation, stable per-vehicle colors, duplicate-coordinate marker offsets, labels, popups, and route-order preview polylines.
- `frontend/export_utils.py`: Added plan summary, route summary, detailed route stop, diagnostic, CSV, and XLSX workbook builders with spreadsheet formula escaping and stable empty-table handling.
- `frontend/api_client.py`: Added `save_scenario` and `load_scenario` methods for the existing scenario persistence API.
- `frontend/streamlit_app.py`: Added save/load scenario controls, route map rendering, route summary display, route-stops CSV download, diagnostics CSV download, and plan workbook XLSX download.
- `frontend/tests/test_route_map.py`: Added map-order, duplicate-coordinate, and distinct-vehicle-color tests.
- `frontend/tests/test_export_utils.py`: Added route/diagnostic export completeness, timezone-preservation, formula-escaping, workbook-sheet, and empty/partial-plan tests.
- `frontend/tests/test_api_client.py`: Added scenario save/load round-trip client test.
- `frontend/tests/test_streamlit_smoke.py`: Updated the smoke test to assert M8 save/load controls are present.
- `backend/app/application/routing_service.py`: Made routing-service cache metadata use the injected service clock for both `created_at` and `expires_at`, fixing a deterministic cache test failure when provider timestamps and injected cache time diverge.
- `README.md` and `project_plan.md`: Marked M8 complete and identified M9 as the next milestone.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Focused cache regression | PASS | `python -m pytest backend/tests/integration/routing/test_google_cache.py::test_cache_hit_prevents_second_google_http_call -q`: 1 passed. |
| Focused frontend suite | PASS | `python -m pytest frontend/tests -q`: 28 tests passed during M8 development. |
| `python -m ruff format --check .` | PASS | 85 files already formatted after mechanical formatting. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 81 source files. |
| Full test suite | PASS | `python -m pytest -q`: 137 tests passed; 3 third-party OR-Tools/SWIG deprecation warnings. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A normalized rows and Scenario B capacity diagnostic remained correct. |
| `python scripts/smoke_m1.py` | PASS | Real FastAPI and Streamlit processes started without a Google key; helper processes cleaned up. |
| `python -m pip check` | PASS | No broken requirements found. |

### Decisions and assumptions

- The map uses backend stop order and planner location coordinates. M8 draws optional straight route-order preview lines only; it does not request billable provider road polylines.
- Duplicate-coordinate stops are slightly offset for clickability and explicitly labeled as duplicate-coordinate markers.
- CSV/XLSX exports are generated from the backend plan JSON contract in the frontend, so no backend implementation models are imported.
- Formula-like spreadsheet values beginning with `=`, `+`, `-`, or `@` are prefixed with an apostrophe before CSV/XLSX export.
- Scenario save/load uses the backend scenario API and never stores or exposes provider credentials in the frontend.
- The cache timestamp fix centralizes cache metadata ownership in `RoutingService`, making tests and production cache expiry use one clock source.

### Known issues

- Pytest still reports third-party OR-Tools/SWIG deprecation warnings during import. These remain non-blocking library warnings.
- M8 route lines are route-order preview lines, not road-following polylines. Provider-road polyline support remains dependent on future provider/cost policy.
- The historical startup script remains named `smoke_m1.py`, but continues to serve as the real backend + Streamlit process smoke check.

### Gate status

- **M8 COMPLETE.**
- Route map with distinct vehicle colors and ordered markers: PASS.
- Duplicate-coordinate markers remain identifiable: PASS.
- CSV and XLSX route/diagnostic exports: PASS.
- Export contains route stops and unscheduled tasks: PASS.
- Datetimes retain timezone labels in human-readable exports: PASS.
- Formula-like cell content is escaped: PASS.
- Save/load scenario controls and client round-trip: PASS.
- Export generation handles empty/partial plans: PASS.
- Map, route table, and export use backend route order: PASS.
- Persistence does not retain or expose provider credentials: PASS.

### Next action

- Begin M9 by hardening the end-to-end release path, documenting deployment/Google setup/backup guidance, and preparing the Version 1 acceptance checklist.

---

## 2026-06-26 — Build 013 — M9 — Version 1 hardening and release documentation complete

### Scope

- Complete the end-to-end hardening and release-documentation milestone.
- Add operational documentation for deployment, Google API restrictions, SQLite backup/restore, troubleshooting, known limitations, and Version 1 release sign-off.
- Add release validation and clean-install scripts.
- Add performance/size-limit/cache/database/solver hardening tests.
- Establish the Version 1 baseline as `v1.0.0`.

### Changes

- `VERSION`: Added the Version 1 baseline marker `1.0.0`.
- `pyproject.toml`: Updated the package version to `1.0.0`.
- `README.md`: Updated status to Version 1 complete, refreshed quality commands, and linked the M9 operation/release docs.
- `.env.example`: Clarified persistence and backend-only Google key guidance.
- `docs/deployment.md`: Added Windows setup, backend/frontend startup, combined launcher usage, production settings, backend API independence, and release verification commands.
- `docs/google_api_setup.md`: Rewrote the Google Maps Platform setup guide with backend-only key handling, Geocoding API + Routes API enablement, IP restriction guidance, cost controls, live smoke, and recovery steps.
- `docs/backup_restore.md`: Added SQLite backup, online backup, restore, retention, and credential-safety guidance.
- `docs/troubleshooting.md`: Added health checks, backend outage, Google credential/quota recovery, payload size, solver timeout, saved-scenario, export warning, and known limitation guidance.
- `docs/version_1_release_checklist.md`: Added the `v1.0.0` release checklist covering all 20 Version 1 acceptance criteria.
- `scripts/validate_m9_release.py`: Added release documentation, official-link, checklist, version-sync, `.gitignore`, and secret-safety validation.
- `scripts/clean_install_check.py`: Added a temporary-venv clean install check for `pip install -e ".[dev]"`, `pip check`, and backend/frontend import validation.
- `backend/tests/integration/test_m9_hardening.py`: Added representative larger fake-matrix caching, solver time-bound, corrupt persisted plan, missing database creation, and request-size limit tests.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| Focused M9 lint | PASS | `python -m ruff check backend/tests/integration/test_m9_hardening.py scripts/validate_m9_release.py scripts/clean_install_check.py`: all checks passed. |
| Focused M9 tests | PASS | `python -m pytest backend/tests/integration/test_m9_hardening.py -q`: 6 tests passed. |
| `python -m ruff format --check .` | PASS | 88 files already formatted. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 82 source files. |
| Full test suite | PASS | `python -m pytest -q`: 143 tests passed; 3 third-party OR-Tools/SWIG deprecation warnings. |
| `python scripts/validate_m0.py` | PASS | All 672 M0 checks passed. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario A normalized rows and Scenario B capacity diagnostic remained correct. |
| `python scripts/smoke_m1.py` | PASS | Real FastAPI and Streamlit processes started without a Google key; helper processes cleaned up. |
| `python scripts/validate_m9_release.py` | PASS | Required docs, links, checklist, version sync, and secret-safety guards passed. |
| `python scripts/clean_install_check.py` | PASS | Temporary venv installed `manufacturing-po-route-optimizer==1.0.0`, `pip check` passed, and backend/frontend imports passed. |
| `python -m pip check` | PASS | No broken requirements found. |
| Dependency vulnerability tooling | PASS/Not available | `python -m pip_audit --version` reported `No module named pip_audit`; no vulnerability audit tool is installed in the project environment. Dependency integrity was verified with `pip check`. |

### Decisions and assumptions

- The workspace is not a Git repository, so the Version 1 baseline is recorded with `VERSION`, `pyproject.toml` version `1.0.0`, the release checklist, and this build log. If imported into Git later, tag the passing commit as `v1.0.0`.
- Google setup documentation links to official Google Maps Platform docs and keeps all credentials backend-only.
- `scripts/clean_install_check.py` is intentionally optional for routine development because it creates a temporary venv and can take several minutes.
- The release validator scans committed docs/config/scripts/tests for key-like Google secrets while ignoring the local `.env` file, which is intentionally untracked.
- The app remains a local SQLite Version 1 deployment; managed multi-user database hosting is documented as a future enterprise evolution.

### Known issues

- Pytest still reports third-party OR-Tools/SWIG deprecation warnings during import. These are non-blocking library warnings.
- `pip-audit` is not installed in the project environment, so a CVE audit was not available without adding tooling. This is documented in the verification table.
- Route-map lines remain non-billable route-order preview lines, not road-following provider polylines.
- Scenario search/list UI and richer grid editing remain future enhancements.

### Gate status

- **M9 COMPLETE.**
- Full regression suite: PASS.
- Performance and size-limit tests: PASS.
- Windows startup and deployment documentation: PASS.
- Google API setup/restriction guide: PASS.
- Backup/restore guidance for SQLite: PASS.
- Known limitations and troubleshooting section: PASS.
- Release checklist and Version 1 baseline: PASS.
- Clean-environment install: PASS.
- Lint, type, unit, integration, API, solver, and UI smoke tests: PASS.
- Representative larger matrix through fake provider: PASS.
- Solver respects configured time bound: PASS.
- Corrupt/missing cache and database failures are controlled: PASS.
- Dependency review where tooling is available: PASS with `pip check`; `pip-audit` unavailable.
- All 20 Version 1 acceptance criteria recorded as passing: PASS.
- No real secrets in committed configuration/docs/tests: PASS.

### Next action

- Version 1 is ready for user acceptance. If this folder is imported into Git, create the `v1.0.0` tag on the passing baseline.

---

## 2026-11-16 — Build 014 — V1.1-M0 — Baseline, decisions, safety net

Plan: `project_plan_v1.1.md` §14, V1.1-M0. Rule 8 above now refers to that plan for Version 1.1 milestones.

### Scope

- Record the Version 1.1 decisions and the Version 1.0 baseline.
- Housekeeping fixes F8 (3-second client timeout), F15 (version drift), F16 (boundary test), explicit `tzdata`.
- Safety net: frozen Version 1.0 payloads and default-option characterization tests.
- Re-read Google usage terms; write the D1/D2 conclusions into `docs/google_api_setup.md`.
- No feature behaviour changes.

### Decisions (accepted by the user on 2026-11-16 — "Accept defaults")

| # | Decision | Outcome |
|---|---|---|
| D1 | Showing Google-derived locations on a map | Google only: "Open route in Google Maps" link per truck; embedded Google map only if an embed key is provided. Folium stays for JSON-supplied coordinates. |
| D2 | Retention of Google data | Enforce the 30-day coordinate rule; review matrix persistence in M0 and change only if required. |
| D3 | Priority scale | 1 Routine (default), 2 Normal, 3 Important, 4 High, 5 Critical; omission weights 1/2/4/8/16. |
| D4 | Local defaults | Country bias `ca`; unit label "units". |
| D5 | Default objective | Keep "fewest trucks" (`MINIMIZE_TRUCKS`). |
| D6 | Persistence of Google travel-time matrices (new, from the D2 review below) | **Open — user decision needed before V1.1-M3.** Recommended: stop persisting Google-sourced matrices. Added to plan §4. |

### Baseline (before any change)

- Branch `v1.1` created from tag `v1.0.0` (`2d93b2d`).
- `ruff format --check`: 88 files formatted; `ruff check`: pass; `mypy backend frontend`: 82 files, no issues; `pytest -q`: **143 passed**, 3 OR-Tools/SWIG deprecation warnings; `validate_m0.py`: pass; `validate_m9_release.py`: pass.
- Version 1.0 default results measured through `POST /api/v1/plans/solve` (two runs, identical; each solve under 0.15 s):

| Scenario | Result | Truck-shifts used | Distance |
|---|---|---|---|
| A | FEASIBLE, 6/6 tasks | 1 (TRUCK-1, day 1) | 216 km |
| B | HTTP 422 `PLANNING_VALIDATION_FAILED` / `CAPACITY_EXCEEDED` | — | — |
| C | INFEASIBLE, `DEADLINE_IMPOSSIBLE_INDIVIDUALLY` | 0 | 0 km |
| D | PARTIALLY_FEASIBLE, TASK-SHORT-004 unscheduled, `INSUFFICIENT_COMBINED_FLEET_TIME` | 3 | 191 km |
| E | FEASIBLE, 1/1 | 1 | 73 km |
| F | FEASIBLE, 2/2 | 2 (TRUCK-1, both days) | 120 km |

### Changes

- `VERSION` is now the single version source (F15). `pyproject.toml` declares `dynamic = ["version"]` read from `VERSION`; `backend/__init__.py` reads `VERSION` in a source checkout and falls back to package metadata when installed. The health endpoint and OpenAPI now report `1.0.0` (previously `0.1.0`). The editable install was refreshed (`pip install -e . --no-deps`); package metadata now reports `1.0.0` (it reported `0.1.0`).
- `pyproject.toml`: `tzdata==2026.2` declared as a direct dependency (same version already installed through pandas).
- `scripts/validate_m9_release.py`: the version check accepts a version read from `VERSION`; it still requires `VERSION` = `1.0.0` (replaced by a version-driven script in M7).
- `frontend/api_client.py`: per-operation timeouts via the new `OperationTimeouts` (F8): health 3 s, validate 15 s, geocode 60 s, matrix 120 s, solve 60 s, plan/export/scenario calls 15 s; connecting is capped at 5 s so a stopped backend is still reported quickly. The unused `timeout_seconds` constructor argument was replaced by `timeouts`.
- `backend/tests/unit/test_package_boundaries.py`: the frontend scan is recursive and parses imports, so a sub-package importing `backend`, `ortools`, or Google client libraries fails the test (F16). A self-test proves nested files are reached.
- `sample_data/v1_0_compat/` (new, frozen): Version 1.0 planning payloads for A–F exactly as the Version 1.0 UI placed them in its JSON editor, `expected_default_results.json`, `manifest.json` (content hashes), and a README with the never-edit rule.
- `backend/tests/integration/test_v1_0_characterization.py` (new): verifies the frozen files are unchanged, then requires each payload's status, scheduled and unscheduled tasks, truck-shifts used, total distance, and diagnostic codes to match Version 1.0, and every returned plan to pass the independent validator.
- `backend/tests/unit/test_version.py` (new), `backend/tests/integration/test_health_api.py`, `frontend/tests/test_api_client.py`: tests for the version source, `tzdata`, and every operation's timeout.
- `docs/google_api_setup.md`: new section "Google usage terms that shape Version 1.1".
- `project_plan_v1.1.md`: D6 added to §4; §13.4 refreshed; M6 deliverables gain matrix persistence per D6 and Google attribution; M0 status updated.

### Google terms review (D1, D2)

- Read directly: Geocoding API policies and Routes API policies pages. Coordinates may be cached for at most 30 consecutive days; place IDs indefinitely; Google attribution is required when showing Google Maps Content unless it is on a Google map that already shows it.
- Service Specific Terms: automated fetching returned no content. Search excerpts of the current page state that Geocoding API content must not be used in conjunction with a non-Google map (**D1 confirmed**) and that Routes API coordinates follow the same 30-day ceiling.
- No express permission to cache Routes API distances or durations was found; the Routes policy page lists "distance matrix results" among content not to store outside the Services. Version 1.0 keeps a 24-hour matrix cache and stores matrices in saved scenarios. Recorded as **open decision D6**; M0 does not change the behaviour.
- To do before release: confirm the excerpted clauses by reading the Service Specific Terms in a browser. Not legal advice.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 90 files already formatted. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 84 source files. |
| `python -m pytest -q` | PASS | **179 passed** (143 baseline + 36 new); same 3 OR-Tools/SWIG warnings. |
| Characterization tests | PASS | `test_v1_0_characterization.py`: 13 passed (A–F results, independent validation of 5 plans, frozen-file hashes, Version 1.0 key set). |
| Timeout tests | PASS | Each of 9 client operations sends its own timeout; only health keeps 3 s; custom and invalid values handled. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | With the dynamic version declaration. |
| `python scripts/review_m2_payloads.py` | PASS | Scenario B capacity diagnostic unchanged. |
| `python scripts/smoke_m1.py` | PASS | Real FastAPI and Streamlit processes started without a Google key. |
| `python -m pip check` | PASS | No broken requirements. |
| `python scripts/clean_install_check.py` | Not run | Creates a fresh venv and downloads packages; the dynamic version was instead checked with `pip install -e . --no-deps` (metadata `1.0.0`). Run before the release (M7). |

### Manual checks

- UI against a live backend (uvicorn on :8010 with a throw-away database; real `frontend/streamlit_app.py` driven by Streamlit's `AppTest`, because the browser pane could not take clicks while hidden): backend banner "Connected to backend 1.0.0"; Load feasible sample → Validate payload → Use routing matrix from payload → Solve route plan → FEASIBLE, 216 km; route-stops CSV, diagnostics CSV, and XLSX export built; Save scenario → "Saved scenario A."; scenario reloaded and backend export retrieved through the client. PASS.
- F1 observed on the live page: the only text input is the "Planning payload JSON" area (the read-only Fleet and Tasks tables were confirmed from code, `streamlit_app.py:398-418`, not by clicking through).
- F2 confirmed at runtime: with latitude/longitude removed from Scenario A's locations, the UI's matrix step (`_routing_locations`) raises "Every location needs location_id, latitude, and longitude before matrix calculation."
- F4 confirmed: Scenario A with `maximum_route_distance_meters` = 50,000 on every truck still returns FEASIBLE with a 216 km route, and the validator reports it valid.
- F5 confirmed: in Scenario D, TASK-SHORT-004 is unscheduled whether its priority is 1 or 5 and whatever the other tasks' priorities are.
- Live Google smoke test: not run (optional; no change touched the Google provider).

### Known issues

- OR-Tools/SWIG deprecation warnings remain (third-party, non-blocking).
- D6 is open and must be settled before V1.1-M3.
- `.env` was not read or changed.

### Gate status

- **V1.1-M0 COMPLETE.**
- Baseline green: PASS. Decisions D1–D5 recorded: PASS; D6 open with a deadline (M3), which does not block M0.
- Clean working tree: PASS — the milestone was committed on branch `v1.1` at the user's request (2026-11-16), including `project_plan_v1.1.md`.

### Next action

- Settle D6; start V1.1-M1 (backend address resolution).

## 2026-11-16 — Build 015 — V1.1-M1 — Backend address resolution

Plan: `project_plan_v1.1.md` §14, V1.1-M1 (design in §8.2–§8.6).

### Scope

- `Location` provenance fields and the `NEEDS_REVIEW` status.
- `resolve_address()` on the Google and fake providers, with region bias.
- `location_service.py`, a 30-day `geocode_cache.py` with a start-up purge.
- `POST /locations/resolve`, `POST /matrices/estimate`, `GET /config`, and the new settings.
- Backend only: no frontend change in this milestone.

### Changes

- **Domain**
  - `domain/enums.py`: `GeocodeStatus.NEEDS_REVIEW`, `GeocodeLocationType`, `GeocodeReasonCode`, and validation codes `STALE_GEOCODE` and `GEOCODE_EXPIRED`.
  - `domain/geocoding.py` (new, pure): address normalisation, region-code check, the provenance fingerprint `v1:<region>:<sha256>`, the 30-day expiry rule, and straight-line distance (a sanity check only).
  - `domain/models.py` → `Location` gains `geocode_source_fingerprint`, `geocoded_at`, `geocode_location_type`, `geocode_partial_match`, and `geocode_confirmed`. A `NEEDS_REVIEW` location must carry the matched coordinates.
- **Validation** (`domain/validation.py`)
  - Warns `STALE_GEOCODE` when the fingerprint no longer matches the address.
  - Warns `GEOCODE_EXPIRED` when `geocoded_at` is older than the limit, or missing beside a fingerprint.
  - Coordinates without a fingerprint (Version 1.0 JSON) are trusted as before.
  - `validate_planning_payload` gains keyword-only `now` and `geocode_max_age_seconds`; the plan routes pass `GEOCODE_CACHE_TTL_SECONDS`.
- **Routing**
  - `routing/base.py`: `GeocodeCandidate`, `AddressResolution`, and `resolve_address` on the provider protocol.
  - `routing/google.py`: one shared geocode request returns every candidate with `location_type` and `partial_match`, and sends `region` when given.
    - `ZERO_RESULTS` is an empty resolution.
    - Key, quota and transport failures keep their stable codes.
    - The legacy `geocode()` is adapted from it with identical requests (no `region`): first match, `GEO-<hash>` ID, `GEOCODE_NOT_FOUND` on no match.
    - Malformed alternative results are skipped; a malformed first result is still `ROUTING_INVALID_RESPONSE`.
  - `routing/fake.py`: configurable resolutions per address, plus per-address or global failures, with call counting.
- **Persistence and services**
  - `persistence/geocode_cache.py` (new): a SQLite `geocode_cache` keyed by a hash of provider, region, normalised address and schema version.
    - Stores parsed candidates and fixed-width UTC timestamps only.
    - The TTL is refused above 30 days, and a lowered TTL also applies to older rows.
    - Not-found answers are refused; `purge_expired()` removes old rows.
  - `application/location_service.py` (new) implements plan §8.3–§8.4:
    - Normalises addresses, makes one provider call per distinct address, and checks the cache first.
    - Calls the provider with bounded concurrency through a `TaskGroup`. The first provider failure fails the batch with its own code, and answers already received are cached first.
    - Classifies every match: `RESOLVED`; `NEEDS_REVIEW` for `PARTIAL_MATCH`, `LOW_PRECISION`, `MULTIPLE_MATCHES` or `FAR_FROM_PLANT`; `FAILED` for `ADDRESS_NOT_FOUND`; plus the `DUPLICATE_PLACE` note.
    - Treats a re-resolved place the planner already confirmed as `RESOLVED` with `geocode_confirmed`.
    - Returns results in request order under the caller's location IDs.
  - `application/routing_service.py`: `estimate_matrix()` counts elements and requests and checks the cache, with no provider call.
- **API**
  - `api/routes/locations.py`: `POST /api/v1/locations/resolve`. The row limit is `API_MAX_GEOCODE_ADDRESSES` (HTTP 413 `RESOLVE_LIMIT_EXCEEDED`). Duplicate IDs, blank addresses and bad region codes return 422.
  - `api/routes/routing.py`: `POST /api/v1/matrices/estimate`.
  - `api/routes/system.py`: `GET /api/v1/config` returns timezone, `google_maps_configured`, region, TTL, plant-distance check, confirmation threshold, solver limit and request limits — never the key.
  - `api/main.py`: a lifespan hook purges expired geocode rows at backend start.
  - `api/dependencies.py`: geocode-cache and location-service dependencies, and shared routing limits.
- **Configuration and docs**
  - `config.py` and `.env.example`: `GEOCODE_REGION_CODE` (default `ca`, per D4); `GEOCODE_CACHE_TTL_SECONDS` (default and maximum 2,592,000); `GEOCODE_MAX_PLANT_DISTANCE_KM` (500); `GEOCODE_MAX_CONCURRENCY` (4); `MATRIX_CONFIRM_ELEMENTS` (400). Also the `google_maps_configured` property.
  - `docs/google_api_setup.md`: address-resolution cost controls, the estimate endpoint, and the logging fix with advice for old logs.
  - `project_plan_v1.1.md`: F19 added to §2; "as built" notes added to §8.3; M1 status and next step.

### Finding F19 — API key and addresses in the backend log (fixed)

While writing the "no key in any log" test, the first run failed. httpx logs every request URL at INFO. Geocoding sends the key and the raw address as query parameters, so at the default `LOG_LEVEL=INFO` lines such as `HTTP Request: GET …/geocode/json?address=…&key=…` reached the backend log.

This is Version 1.0 behaviour; the legacy `/locations/geocode` path has it too.

The fix limits the `httpx` and `httpcore` loggers to warnings in `logging_config.configure_logging` and whenever `GoogleRoutingProvider` is created. Scripts that use the adapter outside the API are covered too.

Logs written by a Version 1.0 backend that ran with a real key should be treated as containing the key. Recorded in plan §2 and `docs/google_api_setup.md`.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 101 files already formatted. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 95 source files. |
| `python -m pytest -q` | PASS | **281 passed** (179 before + 102 new); same 3 OR-Tools/SWIG warnings. No existing test file was modified. |
| Characterization tests | PASS | `test_v1_0_characterization.py`: 13 passed — Version 1.0 results unchanged. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | The secret scan first flagged a test sentinel shaped like a Google key (`AIza…`). The sentinel was renamed; no real secret was involved. |
| `python scripts/review_m2_payloads.py` | PASS | Unchanged. |
| `python scripts/smoke_m1.py` | PASS | Real backend (with the new start-up hook) and Streamlit started. |
| `python -m pip check` | PASS | No broken requirements. |

New tests (mocked HTTP or fake provider; no key needed), mapped to the plan's M1 checks:

| Plan check | Tests |
|---|---|
| Results map to the caller's IDs in request order | `test_location_service.py::test_results_keep_the_callers_ids_and_request_order`; API `test_resolve_returns_rows_in_request_order_with_a_summary` |
| Duplicate addresses cause one provider call | `test_duplicate_addresses_cause_one_provider_call` (case and spacing differences included) |
| Every classification row, including far-from-plant and duplicate place | `test_exact_and_interpolated_matches_resolve`; `test_doubtful_matches_need_review` (partial, approximate, geometric centre, multiple, wrong city); `test_unknown_address_fails_only_its_own_row`; `test_two_ids_at_one_place_are_resolved_with_a_note`; plant-coordinate and skipped-check tests; confirmation tests |
| One unmatched address does not fail the batch; key or quota failure does, with its code | `test_unknown_address_fails_only_its_own_row`; `test_provider_failure_fails_the_batch_with_its_code`; API `test_provider_failure_fails_the_request_with_its_stable_code` (502 with `ROUTING_AUTH_ERROR`, `ROUTING_RATE_LIMIT`, `ROUTING_TIMEOUT`); Google `test_key_and_quota_failures_raise_stable_codes` |
| Cache: miss then hit; expiry; TTL ≤ 30 days; failures not cached; force refresh | `test_geocode_cache.py` (13 tests); service tests for cache hits, original `geocoded_at`, expiry, per-region keys, force refresh, and caching before a failure; API `test_repeat_resolve_is_served_from_cache_unless_forced`; `test_backend_start_purges_expired_geocodes` |
| Address-only JSON validates; Version 1.0 JSON unchanged; stale and expired warnings | `test_geocode_provenance.py` (23 tests) |
| No key in any response, log, or cache row | API `test_no_key_or_address_in_responses_logs_or_cache_rows` (Google adapter over mocked HTTP, DEBUG capture, raw database bytes); Google `test_resolve_logs_never_contain_the_key_or_address`; `test_config_reports_settings_without_any_secret` |
| Legacy `/locations/geocode` unchanged | API `test_legacy_geocode_endpoint_is_unchanged`; Google `test_legacy_geocode_still_sends_no_region_parameter`, `test_legacy_geocode_still_fails_on_zero_results`; all Version 1.0 Google provider tests unchanged and passing |
| OpenAPI schema generates | `test_openapi_schema_lists_the_new_endpoints` |
| Gate: address-only end to end through the API with the fake provider | `test_address_only_scenario_resolves_validates_and_solves`: address-only JSON validates, then resolve, store derived fields, validate with no warnings, estimate (miss), compute, estimate (hit, 0 billable), solve → FEASIBLE |

### Manual checks

- Real backend under uvicorn (port 8011, throw-away database in the session scratchpad):
  - Start-up completed with no errors, including the purge hook.
  - `GET /config` returned only non-secret values (region `ca`, 30-day TTL, confirmation threshold 400, `google_maps_configured` as a boolean).
  - `POST /matrices/estimate` for 21 locations reported 441 elements, 1 request, no cache hit, and confirmation required.
  - `/openapi.json` lists the three new endpoints.
- Not called on the live server: `/locations/resolve`, which would send addresses to Google.
- Optional live check (resolve a handful of public addresses): **not run**. It is billable and sends addresses to Google, so it waits for the user's go-ahead.

### Known issues

- OR-Tools/SWIG deprecation warnings remain (third-party, non-blocking).
- D6 (persistence of Google travel-time matrices) is still open and must be settled before V1.1-M3; M1 does not change matrix caching.
- Stripping expired coordinates from saved scenarios on load and by a start-up sweep (plan §8.6) is not in M1's deliverables; it is an M6 check ("expired coordinates stripped on load"). Until then, validation warns `GEOCODE_EXPIRED`. M1's start-up purge covers the geocode cache table only.
- `.env` was not read or changed.

### Gate status

- **V1.1-M1 COMPLETE.**
- Address-only resolution works end to end through the API with the fake provider: PASS.
- Version 1.0 API tests untouched and green: PASS (no existing test file changed; 179 earlier tests pass).
- Clean working tree: PASS — the milestone was committed on branch `v1.1` at the user's request (2026-11-16).

### Next action

- Settle D6; start V1.1-M2 (frontend foundation).

## 2026-11-18 — Build 016 — V1.1-M2 — Frontend foundation

Plan: `project_plan_v1.1.md` §14, V1.1-M2 (design in §6.1, §7, §12).

### Scope

- `state/` modules.
- Navigation shell with a status sidebar.
- Advanced JSON page: view, edit, validate, apply, upload, and download, in clean and complete modes.
- API client methods for the new endpoints.
- Automatic validation on change.
- The app does everything Version 1.0 does, on the new state model, with JSON as the only editor. No forms yet.

### Decision taken in this milestone: navigation (plan §6.1, risk §17)

The plan chose `st.navigation` with `st.Page` callables, based on a spike on 2026-11-16. It was re-checked before building:

- Under `AppTest` in the pinned Streamlit 1.43.2, `st.switch_page` reaches the target page.
- The next interaction on that page re-renders the *default* page, and the click is lost. A multi-page workflow (navigate, then solve) could not be tested.
- The plan's risk register names a fallback for this: a single-script router.

The router keeps the current page in session state and in the `?page=` URL parameter, so a browser refresh stays on the page. The plan's §6.1 and §17 were updated before the code.

### Changes

- **`frontend/state/`** (new; pure, no Streamlit import):
  - `scenario_state.py`: create; upsert; delete that refuses while the item is referenced, listing the dependants ("used by 1 task and 1 shift"), or deletes them on request; the plant can never be deleted. Renames cascade to every reference. An address change clears the derived geocoding fields; a spacing or case change does not count as one. Also tag removal.
  - `fingerprints.py`: address, matrix-input, plan-input, and saved fingerprints (plan §12). Names and notes are excluded, which fixes F11. The matrix input also covers the address text, so an address edit makes travel times stale even without coordinates.
  - `readiness.py`: per-location readiness — resolved, supplied, not resolved, needs review, failed, stale, expired. It mirrors the backend provenance fingerprint; both test suites pin the same golden values, and a backend test compares the two functions directly. `workflow_status()` decides what is current and which actions are allowed.
  - `workspace.py`: the scenario beside its derived results (validation, active matrix, plan, each with its input fingerprint), and the transitions between them.
    - Deleting unused locations slices the matrix, and renaming a location ID renames it in the matrix; neither calls Google.
    - An embedded `routing_matrix` becomes active when its locations match.
    - "Save scenario" stores the complete scenario plus the active matrix (Version 1.0 behaviour, until D6).
  - `json_io.py`:
    - Clean export (planner inputs only) and complete export (adds derived fields and the active matrix).
    - Parse errors report line and column.
    - Older matrices using `location_order` are normalised to `location_ids`; the canonical samples use the older name.
    - Clean-view applies keep the resolution of unchanged addresses.
  - `ids.py`, `units.py`, `timeutil.py`: ID suggestions; km/m and h:mm conversions; wall-clock text and plant-local display with daylight-saving detection.
- **`frontend/views/`** (new): pages `advanced_json`, `fleet` and `tasks` (read-only, as in Version 1.0), `review`, `travel_times`, `optimize`, `results`; plus `navigation`, `status`, `validation` and `components`.
  - Every action handler re-checks its enable condition, because `AppTest` can click disabled buttons.
  - Values of the editor and its view selector are kept outside Streamlit's widget state, so unapplied JSON survives visiting another page. Streamlit drops a widget's value when its page is not shown; this was found by a test.
- **`frontend/streamlit_app.py`**: rewritten as a thin shell (client, health, config, automatic validation, router, sidebar), replacing the 782-line tabbed script.
- **`frontend/samples.py`**: the sample loader, moved out of the app; it now keeps the scenario `name`.
- **`frontend/api_client.py`**:
  - New methods `resolve_locations` (60 s), `estimate_matrix` and `get_config` (15 s), and the typed `BackendConfig`.
  - `compute_matrix` gains optional routing `options`; the request body is unchanged when they are omitted.
- **Removed:** `frontend/session_models.py`, superseded by `state/`.
- **Migrated tests:**
  - `test_session_models.py` (4 tests) → `test_state_freshness.py`, marked "migrated".
  - `test_streamlit_smoke.py` (4 tests) → `test_streamlit_app.py`, marked "Migrated".
  - Each Version 1.0 behaviour keeps an equivalent test.
- **Docs:** README "Current status"; plan §6.1 (navigation and as-built modules), §7.3 (as-built apply rules), §12 (matrix fingerprint), §14, §17, §21.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 127 files already formatted. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 121 source files. |
| `python -m pytest -q` | PASS | **413 passed**: 281 before, minus the 8 migrated tests, plus 140 new. Same 3 OR-Tools/SWIG warnings. |
| Characterization tests | PASS | Unchanged and green. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | |
| `python scripts/review_m2_payloads.py` | PASS | |
| `python scripts/smoke_m1.py` | PASS | Real backend and the new Streamlit shell start. |
| `python -m pip check` | PASS | |
| Boundary test | PASS | No frontend file imports backend code; `state/` and `views/` are scanned recursively. |

Plan M2 checks and their tests:

| Plan check | Tests |
|---|---|
| State functions: create, upsert, delete with dependants refused, ID rename cascades, address edit clears derived fields | `test_state_scenario.py` (22) |
| Every row of the freshness table (§12) | `test_state_freshness.py`: one test per row (names/IDs/notes/defaults, address, add location, delete unused location with slicing, routing options, fleet/shifts/tasks/period/timezone/plant, optimization options, new matrix, older than 30 days), plus ID rename and readiness cases |
| JSON round-trip in both modes | `test_state_json_io.py`: complete and clean round-trips, through a workspace, carry-over, literal complete apply |
| Invalid JSON cannot replace the current scenario | `test_streamlit_app.py`: a syntax error, and JSON with validation errors, leave a valid scenario unchanged; an invalid scenario may be replaced |
| Version 1.0 fixtures load, validate, use the embedded matrix, and solve through `AppTest` | `test_v1_1_m2_frontend_parity.py`: the real app drives the real backend (in-process, over HTTP) for frozen payloads A, C, D, E, F; each plan matches `expected_default_results.json` exactly (status, scheduled and unscheduled tasks, truck-shifts used, distance, diagnostics). B is refused over a valid scenario; over an invalid one it loads, shows `CAPACITY_EXCEEDED`, and cannot be solved |
| Unit and local-time conversions round-trip, including a DST boundary | `test_state_units_time_ids.py`: UTC to local and back every 30 minutes across both 2026 Toronto transitions; gap and overlap detection |
| Migrated Version 1.0 frontend tests all pass | Export, import-preview, route-map and API-client tests unchanged and passing; session-model and smoke tests migrated |

Also tested:
- Validation runs once per change, not on every rerun.
- Every page renders and is kept in the URL; a fresh session opens the page named in the URL.
- Unapplied editor text survives navigation.
- The clean view hides coordinates and the complete view shows them.
- Replacing an edited scenario asks first.
- Save and load round-trip.
- Address-only JSON cannot calculate travel times.
- No page has a latitude or longitude input.

### Manual checks

- **M0 manual run repeated on the new shell** (real backend under uvicorn, throw-away database; the real app driven by `AppTest`):
  - Load feasible sample, visit every page, Optimize, Solve.
  - Result: FEASIBLE, 6 of 6 tasks, 216 km, one truck-shift (`TRUCK-1/TRUCK-1-20260622`) — identical to M0 (Build 014).
  - Route-stops CSV (2,624 bytes), diagnostics CSV and XLSX built.
  - Save scenario: the sidebar shows no unsaved edits, and the saved payload includes the matrix.
  - The backend export was retrieved; the saved scenario reloaded after switching samples.
- **Real browser** (in-app browser pane; Streamlit on 8515, backend on 8014 with a throw-away database):
  - Sidebar groups Inputs and Plan, with the current page highlighted and the status panel below.
  - Optimize showed three green pre-flight checks; Solve opened Results with FEASIBLE, 6 and 0.
  - A browser refresh stayed on Results. The session's plan is gone after a refresh, as expected; refresh-safe drafts are an M6 item.
  - Observation: at the pane's narrow width the summary metrics truncate ("America…"); cosmetic.
- Live Google: not used. No M2 action calls Google.

### Known issues

- OR-Tools/SWIG deprecation warnings remain.
- **D6 is still open and blocks M3**: travel-time calculation, and whether matrices are stored, are M3's subject.
- `.env` was not read or changed.

### Gate status

- **V1.1-M2 COMPLETE.**
- Version 1.0 parity demonstrated (automated, through the real app and backend, and by the repeated M0 manual run): PASS.
- No frontend import of backend code: PASS.
- Must-have M-2 (JSON stays available as an advanced view of the same scenario) delivered.
- Clean working tree: PASS — the milestone was committed on branch `v1.1` at the user's request (2026-11-18).

### Next action

- Settle D6.
- Start V1.1-M3 (scenario, plant, locations, travel times).

## 2026-11-18 — Build 017 — V1.1-M3 — Scenario, plant, locations, travel times

Plan: `project_plan_v1.1.md` §14, V1.1-M3 (design in §8, §9.1, §9.2, §12, §13).

### Scope

- Scenario page.
- Locations page: name and address only; resolve, review, confirm, retry.
- Location import, and copying locations from a saved scenario.
- Travel times page: estimate, confirmation, routing options, cache indicator, matrix slicing.
- Address-only sample.

### Decision settled before the code: D6 (plan §4)

The go-ahead for M3 was given right after option (a) was recommended, so D6 is recorded as **(a), settled 2026-11-18**. The plan's decision table was updated before any code.

Google Routes distances and durations are not stored:

- **Matrix cache.** `RoutingService` neither reads nor writes the cache for a provider whose `matrix_storage_allowed` is false (Google); every calculation calls the provider. `/matrices/estimate` and `/matrices/compute` report `cache_enabled`. Fake-provider matrices are still cached.
- **Saved scenarios.** `POST` and `PUT /scenarios` drop an embedded `routing_matrix` whose `source` is `google_routes` and return `routing_matrix_dropped`. The app leaves a Google matrix out of saves and JSON downloads, and keeps it for the session.
- **Start-up sweep.** At backend start, Google rows in the matrix cache are deleted, and Google matrices are removed from saved scenarios. `updated_at` is unchanged, because a retention sweep is not a planner's save.
  - The real `data/route_optimizer.db` was inspected read-only. It holds no saved scenarios and no cached matrices, so the sweep removes nothing there.
- **Changed Version 1.0 test.** `test_google_cache.py` asserted a cache hit on the second identical Google request. It now asserts D6: two HTTP calls and an empty cache table. This is the one intended behaviour change.

### Changes

- **Backend**
  - `routing/{base,google,fake}.py`: `matrix_storage_allowed` (Google false, fake true).
  - `application/routing_service.py`: D6 cache rule; `cache_enabled` on its results.
  - `application/retention.py` (new): `matrix_is_storable`, `without_unstorable_matrix`, `sweep_unstorable_matrices`.
  - `persistence/matrix_cache.py`: `purge_source`.
  - `persistence/scenario_repository.py`: `list_summaries`, `rewrite_payloads`, `ScenarioSummary`.
  - `api/routes/scenarios.py`: `GET /scenarios` (newest first, with name and row counts); D6 drop on POST and PUT.
  - `domain/location_import.py` and `api/routes/imports.py` (new): `POST /imports/locations/preview`.
    - Headers map to name, address, and optional ID through aliases (supplier, customer, company, full address, site ID, and others).
    - Row-level issues use spreadsheet row numbers; blank rows are skipped.
    - The request is limited by `API_MAX_LOCATIONS`.
  - `api/main.py`: sweep in the lifespan; imports router.
- **Frontend state**
  - `state/locations.py` (new):
    - Pending addresses (the plant first; blank addresses skipped) and resolve rows; a confirmed place ID is sent back.
    - Plant coordinates for the far-from-plant check.
    - Applying results only while the location still has the address that was sent.
    - Confirm match; add, edit, and duplicate; import merge (by ID, else by a unique name); copy with provenance.
    - Used-by text, unused locations, and table rows.
  - `state/settings.py` (new): identity, timezone list, period (local wall-clock text), "fit to shifts and tasks" in whole local days, plant, choose plant, planner defaults.
  - `state/workspace.py`:
    - Resolve details kept per location for the session (alternatives, distance), following ID renames.
    - Estimate remembered per matrix-input fingerprint.
    - D6: `matrix_is_storable` and `storable_matrix`; `save_document` leaves Google matrices out.
- **Frontend views**
  - `scenario.py` (new): details form, fit button, plant form, choose plant, defaults form, Save, Open (picker over the saved list), Open sample, New.
  - `locations.py` (new):
    - Table with the plant pinned first.
    - Resolve (N pending); Retry not found.
    - Review cards: typed against matched address, reason, distance, Confirm, Correct, "Use this address" for alternatives.
    - Add form; edit, rename, duplicate, delete.
    - Import and Copy expanders.
  - `travel_times.py` (rewritten):
    - Readiness, unused-location note, estimate metrics, large-matrix tick, Calculate.
    - Advanced section: routing options form, plus Recalculate with its own tick.
    - Use travel times from JSON.
  - `opening.py` and `saving.py` (new): shared between Scenario and Advanced JSON.
  - `navigation.py`: Build / Plan / Advanced sections; the app opens on Scenario.
  - `optimize.py`: "Every location is resolved" pre-flight check.
  - `results.py`: address-resolved locations are not drawn on the OpenStreetMap preview (D1).
- **API client:** `list_scenarios`, `preview_location_import`.
- **Samples:** `sample_data/v1_1/v11_a_address_only.json` (V11-A) with a README.
  - Seven Greater Toronto civic-building addresses standing in for a plant, three suppliers, and three customers.
  - Three trucks and six mixed tasks; no coordinates and no travel times.
  - Offered in the app as "Address-only sample".
- **Tests**
  - New: `test_m3_pages.py` (25), `test_state_locations.py` (22), `test_state_settings.py` (9), `test_location_import.py` (7), `test_v1_1_m3_api.py` (9), `test_v1_1_m3_address_only.py` (2).
  - `fake_backend.py`: the `AppTest` fake client, moved out of `test_streamlit_app.py` and extended.
  - The M2 app and parity tests now open Advanced JSON through `?page=json`, because the first page is now Scenario. Their assertions are unchanged, except where a page's content moved: the locations table is on Locations, and a current matrix means there is nothing to calculate.
- **Docs**
  - Plan: status line; §6.1, §6.3, §7.3, §8.7, §9.1, §9.2, §13.2, §13.4, §14, §16 (criterion 12 under D6), §17, §21.
  - README "Current status"; `docs/google_api_setup.md` D6 row.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | 143 files already formatted. |
| `python -m ruff check .` | PASS | All checks passed. |
| `python -m mypy backend frontend` | PASS | No issues in 137 source files. |
| `python -m pytest -q` | PASS | **489 passed**: 413 before, plus 74 in new files and 2 more page cases in `test_streamlit_app.py`. Same 3 OR-Tools/SWIG warnings. |
| Characterization and M2 parity tests | PASS | Unchanged results for A–F. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | |
| `python scripts/review_m2_payloads.py` | PASS | |
| `python scripts/smoke_m1.py` | PASS | Run with `DATABASE_PATH` set to a scratch file, so the start-up sweep could not touch the real database. |
| `python -m pip check` | PASS | |
| Real database untouched by checks | PASS | The modification time of `data/route_optimizer.db` was unchanged across full backend and frontend test runs. |

Plan M3 checks and their tests:

| Plan check | Tests |
|---|---|
| No form on any page exposes a latitude or longitude input (widget tree) | `test_no_widget_on_any_page_asks_for_latitude_or_longitude`: every widget on all nine pages (labels, keys, help) |
| Add → resolve → confirm → calculate through `AppTest` with a fake client | `test_add_resolve_confirm_calculate_and_solve`, `test_a_new_scenario_is_built_from_the_scenario_and_locations_forms`; against the real backend: `test_typed_addresses_become_a_current_matrix_and_a_feasible_plan` |
| An address edit resets only that location and stales travel times; a rename changes nothing downstream | `test_editing_one_address_resets_only_that_location_and_stales_travel_times`, `test_renaming_a_location_changes_nothing_downstream` (plan stays current), `test_renaming_a_location_id_keeps_travel_times_current`, plus state tests |
| Rerunning or navigating makes zero provider calls | `test_rerunning_and_visiting_pages_makes_no_provider_calls` (fake client: resolve, matrix, and estimate counts); the real-backend gate test counts `FakeRoutingProvider` calls across reruns and every page |
| No calculation while a location is unresolved, in review, or failed | `test_travel_times_cannot_be_calculated_while_a_location_is_not_ready` (three cases; disabled buttons are clicked too, and nothing is sent) |
| Large-matrix confirmation above the threshold | `test_a_large_matrix_needs_a_confirmation_tick`, `test_below_the_threshold_no_confirmation_is_asked`, `test_recalculating_current_travel_times_needs_its_own_confirmation` |

Also tested:
- Only new or changed addresses are sent. A repeat lookup is served by the 30-day cache with no provider call.
- Not-found addresses are corrected and resolved again; an alternative match can be picked; the far-from-plant distance is shown.
- Deletion is refused while a location is used, and the plant cannot be deleted. Duplicating keeps the resolution.
- Locations copy from a saved scenario, and the import contract works end to end.
- Routing options make travel times stale and are sent with the calculation.
- Google travel times are not saved or downloaded.
- Scenario details, the period fit, and defaults; choosing another plant.
- The address-only sample opens with no coordinates or travel times, and results show no OpenStreetMap map for it.
- Address-only JSON validates on the backend before and after resolution.

### Manual checks

- **Browser run with the offline provider.** In-app browser; Streamlit on 8525; backend on 8024 with a scratch database and a fake provider answering the V11-A addresses plus two bad ones.
  - Opened the address-only sample on the Scenario page.
  - Added "Vaughan, ON" (vague) and "100 Queen St W, Ottawa, ON" (wrong city), then resolved 9 addresses: 7 resolved, 2 need review.
  - The vague address was caught (low precision). The partial match for Hamilton showed both addresses, the reason, and "41 km from the plant".
  - **The wrong-city address was not caught.** Ottawa is about 370 km from the Mississauga plant, under the default `GEOCODE_MAX_PLANT_DISTANCE_KM` of 500. The table still shows Google's matched address beside the typed one. Recorded in plan §17: regional fleets should lower the setting. The default was not changed.
  - Confirmed Hamilton, deleted the two test locations, calculated travel times (7 locations, 49 billable elements, 1 request), and solved: **FEASIBLE, 6 of 6 POs**.
  - A second session resolved the same 7 addresses with **0 lookups, 7 from the 30-day cache**.
- **Found and fixed during the browser run**
  - After Add location, the address field that had focus kept its text, a Streamlit `clear_on_submit` quirk. The form now gets fresh widget keys after each add, and a test asserts the fields are empty.
  - The used-by text "The plant and used by …" now reads "Plant; used by …".
  - "1 need review" is now "1 needs review".
- **Not done: the live-key check.** The plan's manual check calls for a live Google key on a seven-location scenario. It makes billable calls, so it was not run without a go-ahead. The steps above are ready to repeat with the key.
- Loading a page by URL starts a new session (refresh-safe drafts are an M6 item); the run used in-app navigation.

### Known issues

- OR-Tools/SWIG deprecation warnings remain.
- Live-key manual check outstanding (see above).
- Wrong-city matches within 500 km of the plant pass the far-from-plant rule (see above).
- Stored plans still hold per-leg distances and times derived from the matrix. D6 covers matrices, so plan retention is reviewed with plan history in M6.
- `.env` was not read or changed.

### Gate status

- **V1.1-M3 COMPLETE**, with the live-key manual check outstanding.
- A planner gets from typed addresses to a current travel-time matrix, and to a feasible plan, with no coordinate entered. Shown through the real app and backend (offline provider) and in the browser.
- **Must-haves M-3 and M-4** (address-only locations) delivered.
- Clean working tree: PASS — the milestone was committed on branch `v1.1` at the user's request (2026-11-18).

### Next action

- Run the live-key manual check when approved.
- Start V1.1-M4 (fleet, shifts, tasks, import, review).

## 2026-11-20 — Build 018 — V1.1-M4 — Fleet, shifts, tasks, import, review

Plan: `project_plan_v1.1.md` §14, V1.1-M4 (design in §9.3–9.6, §10.4, §10.5, §10.7, §15).

### Scope

- Fleet page with the shift generator; Tasks page; task import and apply through the backend contract; templates.
- Review page with the new warnings.
- Backend completion of the fields these forms expose: the route-distance limit, priority weights, and validator re-checks.

### Decisions

No open decision blocked M4. D3 (priority scale and weights 1/2/4/8/16) was settled on 2026-11-16 and is implemented as decided.

### Changes

- **Backend: solver and validator**
  - `domain/options.py` (new): priority labels and weights (D3).
  - `optimization/solver.py`:
    - A left-out task node costs `dropped_task_penalty` × its priority weight. With every priority at 1, the model is exactly Version 1.0's.
    - A `RouteDistance` dimension is added only when some active truck has a distance limit.
    - The per-task check reports `ROUTE_DISTANCE_LIMIT_EXCEEDED` when only a distance limit stops a truck from doing the task alone, in time.
    - Every task diagnostic carries `priority`. The partial-plan message now names "fleet time, capacity, or route allowance"; its code is unchanged.
  - `optimization/validator.py`: rejects routes that carry a task without its tags, last longer than the truck's or shift's route-time limit (waiting included), exceed the truck's distance limit, or use a disabled truck.
- **Backend: validation (Review)**
  - New warnings:
    - `UNKNOWN_FIELD`, for top-level keys outside the known set.
    - `UNUSED_LOCATION`.
    - `VEHICLE_WITHOUT_SHIFT`, for enabled trucks only.
    - `NO_COMPATIBLE_VEHICLE`: tags no enabled truck has, or a quantity only too-small tagged trucks could carry.
    - `TASK_WINDOW_OUTSIDE_SHIFTS`.
  - Overlapping shifts (`SHIFT_OVERLAP`) and shifts outside the period (`OUTSIDE_PLANNING_HORIZON`) are now named per shift. They used to be one generic `INVALID_VALUE`; validity is unchanged.
  - `ValidationIssue` gains `section` and `item_id` (additive). The details of a rejected payload carry `severity`, `section`, and `item_id`.
- **Backend: import**
  - `domain/task_import.py` (new):
    - Task spreadsheet preview through the same column table as JSON validation.
    - Location cells match an ID, then a unique name, ignoring case and spacing.
    - The plant end of a pickup or drop may be empty, and so may `task_id`.
    - Priority labels are accepted. Empty service minutes take the scenario defaults.
    - Local times are checked for daylight-saving gaps.
    - Template descriptions are built from the same column specs.
  - `api/routes/imports.py`: `POST /imports/tasks/preview` (limited by `API_MAX_TASKS`) and `GET /imports/templates/{tasks|locations}`.
- **Frontend: state**
  - `state/fleet.py` (new):
    - Trucks: capacity up to three decimals, tags, h:mm and km limits.
    - Shifts: an end time at or before the start time is the next day; the plant is the default end; "copy to the next day".
    - Overlap detection, and the generator, which flags shifts that already exist or overlap and gives unique IDs.
  - `state/tasks.py` (new):
    - Movements fill the plant end; the form rules match the backend's.
    - Duplicate marks the PO "(copy)".
    - Immediate tag and capacity warnings; filters.
    - Import apply in three modes, all-or-nothing.
  - `state/settings.py`: `extend_period`. Forms that add shifts or tasks outside the period grow it to whole days and say so; it never shrinks on its own.
- **Frontend: views**
  - `fleet.py` and `tasks.py` are forms in tabs (Add / Edit / Generate / Import), because Streamlit does not nest expanders.
  - On the Tasks page the movement is chosen above the form, and the plant end is a disabled picker holding the plant.
  - `review.py` groups issues by section with "Go to" buttons that open the row's form, and offers "Fit the planning period" when something is outside it.
  - `imports.py` (new): template downloads (CSV, and Excel with a column guide), fetched once per session.
  - `import_preview.py` now only reads files and writes templates. Its alias table, a second copy of the backend's, is deleted (F12).
- **Sample fixtures:** V11-F (priority shortage), V11-G (tags), V11-H (route time and distance limits), V11-I (multi-day shifts ending at a hub). Each reuses the canonical locations and travel times, trimmed to what it uses.
- **Docs:** plan status and as-built notes (§6.1, §6.3, §9.3–9.6, §10.4, §10.5, §10.7, §14, §15, §21); README "Current status"; `docs/import_contract.md` (spreadsheet import, apply modes, templates); `sample_data/v1_1/README.md`.

### Changed existing tests

Each change is deliberate:

- **`test_v1_0_characterization.py`, Scenario B.** The 422 details of the Version 1.0 payload now also list the new `UNUSED_LOCATION` warnings for its unused shared locations. Details now carry `severity`, and the test compares the blocking codes against the frozen `["CAPACITY_EXCEEDED"]`. The frozen file is unchanged.
- **M2 parity test and `test_streamlit_app.py`.** Review now lists issues as lines with "Go to" buttons instead of a table, so these assertions look for the issue there.
- **`test_state_freshness.py`.** Issue rows gained `section` and `item_id`.
- **`test_import_preview.py`.** Rewritten for file reading and templates, plus a check that the frontend has no alias table any more.
- **Fake backend.** It gained `preview_task_import`, `import_template`, and configurable extra issues.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | |
| `python -m ruff check .` | PASS | |
| `python -m mypy backend frontend` | PASS | No issues in 151 source files. |
| `python -m pytest -q` | PASS | **627 passed** (489 before: 135 in new files, 3 more in the rewritten import test). Same 3 OR-Tools/SWIG warnings. |
| Characterization tests A–F | PASS | Same status, scheduled set, truck-shifts, and distance as Version 1.0. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | |
| `python scripts/review_m2_payloads.py` | PASS | |
| `python scripts/smoke_m1.py` | PASS | `DATABASE_PATH` set to a scratch file. |
| `python -m pip check` | PASS | |
| Real database untouched | PASS | Modification time of `data/route_optimizer.db` unchanged (2026-11-18 22:08). |

Plan M4 checks and their tests:

| Plan check | Tests |
|---|---|
| Vehicles, shifts, and all three task movements created through forms validate on the backend | `test_a_complete_scenario_is_built_and_solved_without_opening_json` (real app and backend); `test_all_three_movements_are_added_through_the_form`; `test_imported_rows_validate_as_planning_tasks` |
| Shift generator: unique IDs, overlaps flagged, existing skipped, multi-day and weekday selection | `test_generator_covers_several_days_on_the_chosen_weekdays_with_unique_ids` (two weeks, three trucks: 30 unique IDs), `test_generator_skips_existing_shifts_and_flags_overlaps`, `test_the_generator_adds_only_new_shifts_and_extends_the_period` |
| Movement selection fills and locks the plant end; backend rules agree | `test_choosing_a_movement_fills_and_locks_the_plant_end` (all three movements), `test_the_movement_fills_the_plant_end`, `test_movement_rules_agree_with_the_backend`, `test_movement_and_plant_must_agree` |
| Import: append, update, replace; all-or-nothing; locations by ID or name; one alias table | `test_append_…`, `test_update_…`, `test_replace_…`, `test_a_failing_row_imports_nothing` (4 cases), `test_a_checked_import_is_applied_in_the_chosen_mode`, `test_a_failing_import_changes_nothing`, `test_locations_match_by_id_or_exact_name`, `test_headers_map_through_the_shared_contract`, `test_templates_come_from_the_same_contract`, `test_the_frontend_has_no_column_alias_table_of_its_own` |
| Distance limit enforced by the solver, rejected by the validator, reported per task | `test_distance_limit_is_enforced_by_the_solver` (Scenario A with 150 km: every route within it, more than one truck), `test_validator_rejects_routes_over_the_distance_limit`, `test_a_task_beyond_every_distance_limit_is_reported_individually` |
| Priority: all scheduled when feasible; higher kept in the shortage fixture; weights monotonic; pairs together | `test_every_task_is_scheduled_when_everything_fits_whatever_the_priority`, `test_shortage_keeps_the_higher_priorities` (V11-F keeps 5 and 4), `test_reversed_priorities_keep_the_other_tasks`, `test_priority_scale_and_weights_follow_decision_d3`, `test_pickup_drop_pairs_are_kept_or_dropped_together`, `test_priority_penalties_dwarf_routing_costs_and_cannot_overflow` |
| Validator rejects corrupted plans violating tags, duration, or distance | `test_validator_rejects_a_route_without_the_required_tags`, `test_validator_rejects_routes_over_the_duration_limit` (truck and shift), `test_validator_rejects_routes_over_the_distance_limit` |
| Default-option characterization tests from M0 still pass | `test_v1_0_characterization.py` (A–F), `test_without_any_distance_limit_no_distance_dimension_is_added` |

Also tested:

- Review warnings with sections and IDs, including on the API.
- Version 1.0 payloads stay valid with only warnings added.
- "Go to" opens the truck or task form with the row selected, and "Fit the planning period" works.
- Fleet and task edits keep travel times current and make no provider call.
- Renaming keeps the row selected in the edit picker.
- A one-off message no longer moves the page below it.

### Manual checks

- **Browser run with the offline provider.** In-app browser; Streamlit on 8525; backend on 8024 with a scratch database and the M3 fake provider.
  - From "Start a new empty scenario": plant and four locations by address, then one resolve.
  - Three trucks through the form, including a refrigerated truck limited to 9:00 and a truck limited to 150 km.
  - Shift generator: 7–8 December for all three trucks, "6 new, 0 skipped". The message said the planning period was extended to include them.
  - Tasks through the form, all three movements. Pickup and Drop showed the plant end as a disabled picker; Pickup-drop offered both ends without the plant.
  - Spreadsheet import of a three-row CSV, with a location by name, one by a lower-case name, one by ID, and empty plant ends. The backend matched every location; "3 added".
  - Edited an imported row (quantity and priority) and saved.
  - Review: valid with no issues. Travel times calculated; solved **FEASIBLE**, all POs scheduled. The refrigerated PO went on the refrigerated truck, read from the stored plan. Saved the scenario.
  - Each address was a cache hit on the second build: 0 lookups, 5 from the 30-day cache.
- **Found and fixed during the browser run**
  - After an import or save, the next widget change reopened the first tab, for example from "Edit" back to "Add". Cause: the one-off message disappeared, so the page below it moved up one place and Streamlit treated the tabs as new. Notices are now always drawn in one container, with a regression test.
  - Editing a task's PO number, or a location's name, made the edit picker jump to the first row. The picker's labels include the name, and Streamlit resets a selectbox whose options change. Every save now keeps its row selected, on Trucks, Shifts, Tasks, and Locations (an M3 bug too), with a regression test.
  - Follow-on from the notices fix: "How to import" is now always shown on the Import tab, instead of only with a checked file. The planner sees beforehand how the next file will be applied, and the caption warns when Replace is chosen.
    - Why it mattered in tests: when a click triggers a rerun, `AppTest` keeps the elements of the interrupted first pass that the rerun does not redraw. A keyed radio that vanished after an import then broke the test's next run.
    - The browser removes such leftovers when the run finishes, so the app itself was not affected.
- **Notes**
  - The browser cannot use the operating system's file dialog, so the CSV was handed to the upload control by a page script; the app's own steps from there were clicked normally. `AppTest` cannot upload files either: automated tests start from the checked preview.
  - Changing app code while a browser session is open makes Streamlit reload its modules, and that session's workspace no longer matches the reloaded class ("Session workspace is missing"). It happens only during development; a refresh starts a new session. The scenario was rebuilt through the forms after the layout fix, as recorded above.

### Known issues

- OR-Tools/SWIG deprecation warnings remain.
- The M3 live-key manual check is still outstanding (needs a go-ahead for billable Google calls).
- The first task added to an empty task list, or the first truck or shift, still reopens the first tab once. The table then appears above the tabs and moves them. It happens once per page.
- Fixtures V11-B, C, D, E, and J (plan §15) belong to other milestones and were not created here.
- Tests only: after an action that removes a keyed checkbox, such as "Also delete its shifts" once the truck is deleted, a further `AppTest` run would fail on the leftover element. No test runs after such a deletion; the app is not affected.
- `.env` was not read or changed.

### Gate status

- **V1.1-M4 COMPLETE.** A complete scenario is built and solved without opening JSON. This is shown by the gate test, real app and backend from an empty scenario, and by the browser run.
- **Must-have M-1** (forms for every input) delivered. With M3, all five must-haves (M-1 to M-5) are now in place.
- Clean working tree: PASS. The milestone was committed on branch `v1.1` at the user's request (2026-11-20).

### Next action

- Run the M3 live-key manual check when approved.
- Start V1.1-M5 (optimization options and the Optimize page).

## 2026-11-21 — Build 019 — V1.1-M5 — Optimization options and the Optimize page

Plan: `project_plan_v1.1.md` §14, V1.1-M5 (design in §9.7, §10.1–10.3, §10.6, §10.8).

### Scope

- The `optimization_options` contract and bounds.
- Objective modes, search effort, travel-time buffer, and precomputed transit matrices.
- Solving off the event loop; unique plan IDs, history, and metadata.
- The Optimize page.

### Decisions

No open decision blocked M5. D5 (default objective: fewest trucks, as in Version 1.0) is implemented as decided.

### Changes

- **Options contract** (`domain/options.py`, `domain/enums.py`)
  - `OptimizationOptions` has `objective_mode`, `search_effort`, `time_limit_seconds` (empty means the server default), `travel_time_factor` (1.00–2.00, two decimals), `extra_truck_cost_km` (0–100,000), and `balance_strength`.
  - Unknown keys are rejected.
  - `PlanningRequest` carries the options; a payload without them gets the Version 1.0 defaults.
- **Validation:** options are parsed with field-level errors in section `optimization_options`. A time limit above `SOLVER_MAX_TIME_LIMIT_SECONDS` (new, default 120) is an error, so JSON cannot exceed the server's ceiling.
- **Objective and search** (`optimization/objective.py`, new; all weights live here)
  - Fewest trucks: a fixed cost per truck-shift of `extra_truck_cost_km` × 1,000.
  - Least travel: no fixed cost.
  - Balanced workload: no fixed cost, plus a span cost on the `RouteDuration` dimension, which is working time.
  - The balance presets were tuned on V11-E and frozen: Light 5, Medium 10, Strong 20. The first try (5/20/100) was not monotonic in working time.
  - Thorough search adds guided local search.
- **Solver** (`optimization/solver.py`)
  - Per-solve settings; no settings means exactly Version 1.0's.
  - Distances, durations, and load changes are registered as precomputed matrices up to 1,000 nodes, with Python callbacks above that.
  - Each route records its total duration; each plan records its objective value and metrics.
- **Metrics** (`optimization/metrics.py`, new): truck-shifts used and available; longest and shortest route (elapsed, waiting included); longest working time; average load and time utilisation.
- **Validator:** re-checks a route's total duration.
- **Planning service** (`application/planning_service.py`)
  - It maps options to settings and applies the travel-time buffer once, to a copy of the matrix shared by the solver, pre-checks, and validator. Each leg is rounded half up; the stored matrix is untouched.
  - Plan IDs are `PLAN-<UTC timestamp>-<8 hex>`.
  - A plan records `created_at`, the options with the time limit filled in, and the matrix identity, including the factor.
- **Off the event loop, one at a time.** A worker thread did not help: OR-Tools keeps Python's interpreter lock for the whole search (measured: one main-thread tick during a 3 s solve).
  - Solves now run in one long-lived worker process (`SOLVER_IN_SUBPROCESS`, default on), which also serialises them. The API waits for it in a thread.
  - The worker exits when the backend exits, even when the backend is killed (found in the manual run; see below).
- **History:** the plan repository keeps `PLAN_HISTORY_LIMIT` (default 20) plans per scenario. `GET /api/v1/scenarios/{id}/plans` lists them newest first, with settings and headline figures.
- **Config:** `GET /config` reports `solver_max_time_limit_seconds` and `plan_history_limit`. `.env.example` documents the three new settings.
- **Frontend**
  - `state/optimization.py` (new): stores only values that differ from the defaults, so an all-default scenario keeps the Version 1.0 JSON. It also provides the one-line summary, plan figures, and the solve timeout.
  - The Optimize page has a settings form: objective and search effort, each with an explanation; a time-limit slider bounded by the server; a 0–100 % buffer; and, under Advanced, the extra-truck cost and balance strength. It states that no setting relaxes a hard rule, and the expected wait for a thorough search.
  - The solve shows a spinner, and the client waits 2 × limit + 20 s.
  - Results show truck-shifts used, distance, longest route, and longest working time, with "Made with: …".
  - Review links optimization issues to the Optimize page.
- **Fixture V11-E:** Scenario A's six POs on one day with three trucks.
- **Docs:** plan status and as-built notes (§6.3, §9.7, §10.1–10.3, §10.6, §10.8, §14, §15, §21); README "Current status"; `sample_data/v1_1/README.md`; `.env.example`.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | |
| `python -m ruff check .` | PASS | |
| `python -m mypy backend frontend` | PASS | No issues in 160 source files. |
| `python -m pytest -q` | PASS | **690 passed** (627 before, 63 new). Same 3 OR-Tools/SWIG warnings. No solver worker process left after the run. |
| Characterization tests A–F | PASS | Unchanged through the planning service, the worker process, and precomputed matrices. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | |
| `python scripts/review_m2_payloads.py` | PASS | |
| `python scripts/smoke_m1.py` | PASS | `DATABASE_PATH` set to a scratch file. |
| `python -m pip check` | PASS | |
| Real database untouched | PASS | Modification time unchanged across the runs. It is newer than at M4 because the app was used in between, not because of the checks. |

Plan M5 checks and their tests:

| Plan check | Tests |
|---|---|
| No options gives Version 1.0 results | `test_v1_0_characterization.py` (API, A–F); `test_default_options_reproduce_the_version_1_0_solve`; `test_precomputed_matrices_and_callbacks_give_identical_plans` (A, C–F) |
| Out-of-range values rejected with field-level errors; server maximum cannot be exceeded through JSON | `test_out_of_range_options_are_field_level_errors` (8 cases, including a misspelt key), `test_json_cannot_exceed_the_server_time_limit_ceiling`, `test_the_server_default_must_not_exceed_its_maximum`, `test_settings_are_bounded` |
| V11-E: fewest trucks uses the fewest truck-shifts; balanced uses more with a shorter longest route; least travel no further than the other two | `test_fixture_v11_e_objective_modes_differ_as_documented`, `test_balance_presets_are_frozen`, `test_objective_chosen_on_the_page_changes_the_plan` (real app and backend) |
| Every mode and effort passes the independent validator on every fixture | `test_every_mode_and_effort_passes_the_independent_validator`: 3 modes × 2 efforts × 10 fixtures |
| Buffer: solver, pre-check, and validator agree; a deadline that holds at 1.0 and fails at 1.5 is diagnosed; no provider call on change | `test_buffer_deadline_holds_at_1_0_and_is_diagnosed_at_1_5` (late by exactly 7:30), `test_solver_precheck_and_validator_see_the_same_buffered_times`, `test_settings_are_stored_minimally_and_make_only_the_plan_stale` (no provider call; travel times stay current) |
| Thorough search within the time limit plus tolerance, no worse than standard | `test_thorough_search_respects_the_time_limit_and_is_no_worse` (each mode, objective value compared) |
| Two solves give two retrievable plans; health responds during a solve | `test_two_solves_give_two_retrievable_plans_and_history`, `test_history_keeps_only_the_newest_plans_per_scenario`, `test_health_responds_while_a_solve_is_running` |
| Timeout still told apart from infeasibility | existing `test_solver_timeout_status_is_not_reported_as_proven_infeasible`; `test_thorough_search_on_a_shortage_is_still_a_partial_plan_not_a_timeout` |

Also tested:

- Unique plan IDs, 30 characters whatever the scenario ID.
- Metrics and route durations; plans stored by Version 1.0 stay readable.
- Time-limit default and cap; the client's solve timeout (MockTransport).
- The Optimize page's bounds, summary, and Review link.
- The worker exits when its backend is killed.

### Manual checks

- **API on a real uvicorn server** (scratch database, offline provider, Windows):
  - A thorough solve of Scenario A with a 3 s limit took 4.8 s, about 1.8 s of it starting the worker on first use.
  - `/health` answered in about 0.3 s throughout.
- **Browser run on the feasible sample (Scenario A).** All four plans appear in `GET /scenarios/A/plans`, newest first. The backend made no travel-time or Google calls.

  | Settings | Truck-shifts | Distance | Longest route | Longest working time |
  |---|---|---|---|---|
  | Fewest trucks (default) | 1 of 6 | 216.0 km | 7:33 | 7:18 |
  | Least travel | 1 of 6 | 216.0 km | 7:33 | 7:18 |
  | Balanced workload, medium | 3 of 6 | 254.0 km | 4:07 | 3:23 |
  | Fewest trucks, thorough, 20 % buffer | 1 of 6 | 216.0 km | 8:21 | 8:06 |

  - The explanations match what happened. Least travel equals fewest trucks here because one chained route is also the shortest. Balanced spreads the work for 38 km more.
  - The buffer lengthened every leg without recalculating travel times. After each saved change, the sidebar showed travel times current and the plan stale.
- **Found and fixed:** after the backend was stopped by killing it, its solver worker kept running, idle. `run_app.ps1` stops the backend this way, so every run would have left a stray Python process.
  - Reproduced: a worker outlived its parent.
  - Fix: the worker watches its parent process and exits with it.
  - Regression test: `test_the_solver_worker_exits_when_the_backend_is_killed`.
  - The leftover workers from the manual run were removed.

### Known issues

- OR-Tools/SWIG deprecation warnings remain.
- The M3 live-key manual check is still outstanding.
- The first solve after a backend start takes about 2 s longer while the worker starts.
- Balanced workload evens out working time, meaning driving plus service. The elapsed day can stay longer where a route waits for a ready time.
- Plan comparison on the Results page, and the buffer printed on exports, come with M6.
- `.env` was not read or changed.

### Gate status

- **V1.1-M5 COMPLETE.** Each option has deterministic regression evidence: V11-E figures, frozen presets, the buffer deadline case, and thorough-versus-standard objective values.
- None weakens a hard constraint: every mode and effort passes the independent validator on every fixture.
- Clean working tree: PASS. The milestone was committed on branch `v1.1` at the user's request (2026-11-21).

### Next action

- Run the M3 live-key manual check when approved.
- Start V1.1-M6 (results, plan history and comparison, run sheets, scenario management, drafts).

## 2026-11-21 — Build 020 — V1.1-M6 — Results, plan history, scenario management

Plan: `project_plan_v1.1.md` §14, V1.1-M6 (design in §11.1–11.3, §12, decisions D1 and D6).

### Scope

- The Results page in planner language.
- Plan comparison and earlier plans.
- Run sheets and updated exports.
- Scenario management: Save as, Duplicate, Delete, and the overwrite guard.
- Refresh-safe drafts and restore.
- Map behaviour per D1 (Google Maps links).
- Drafts storing only the matrix identity (D6).
- Google attribution.
- Stripping expired coordinates on load.

### Decisions

No open decision blocked M6. D1 is implemented as "links only": no embed key was provided, so there is no embedded Google map. D6's last part (drafts store only the matrix identity) is implemented.

### Changes

- **Plan identity** (`application/planning_service.py`, `domain/results.py`)
  - Each plan records an `input_fingerprint` of what was planned: period, plant, location IDs and addresses, trucks, shifts, tasks, and travel times without their timestamps.
  - Names, notes, settings, and derived geocoding fields are left out, so plans that differ only in their settings share it.
  - Plan history summaries add the fingerprint, trucks available, longest working time, driving time, and the remaining settings.
- **Persistence** (`persistence/scenario_repository.py`)
  - `save(..., overwrite=False)` raises instead of replacing.
  - New: `delete`, a `scenario_drafts` table and repository, plan deletion and counts per scenario, and the `plans_by_scenario` index.
  - `schema_meta` records schema version 2. The backend prepares the schema at start-up.
- **API** (`api/routes/scenarios.py`, `api/contracts.py`)
  - Scenarios:
    - `POST /scenarios?if_exists=error` answers 409 `SCENARIO_EXISTS`; the default still replaces.
    - `DELETE /scenarios/{id}` removes the scenario, its plans, and its draft.
    - The scenario list adds `plan_count`.
  - Drafts: `PUT/GET/DELETE /scenarios/{id}/draft`.
    - The path and payload IDs must match, and `meta` is limited to 16 KB.
    - A Google matrix is dropped.
- **Retention** (`application/retention.py`)
  - Coordinates found by address resolution that are older than 30 days are stripped when a saved scenario or a draft is loaded, and by a sweep at start-up. The stored copy is cleaned too.
  - The address, place ID, and confirmation stay, and the status returns to `PENDING`.
  - Coordinates supplied in JSON are never stripped. The start-up sweep for Google matrices now covers drafts too.
- **Results in planner language** (`frontend/state/results.py`, new; `frontend/views/results.py`, rewritten)
  - The status is one sentence. The figures are truck-shifts used, POs planned, distance, driving time, longest route, and tightest slack.
  - Not-planned POs come highest priority first, with a reason, the due time, and a suggested action. Problems with the whole plan are shown apart.
  - Trucks and routes show location names, POs, quantities with the unit, plant-local times (with "+1 day"), and Depart / Pick up / Deliver / Return or Finish.
- **Compare and earlier plans**
  - Stored plans are listed side by side, newest first, with "Inputs: This plan / Same / Different".
  - Any other plan opens as an earlier plan, clearly dated, and can be exported.
  - A stale plan stays hidden but listed.
- **Map (D1).** Each route gets an "Open in Google Maps" link.
  - Repeated consecutive places are merged.
  - Routes beyond nine waypoints or 2,048 characters are split into consecutive links.
  - The OpenStreetMap preview remains for JSON coordinates only.
- **Attribution.** "Matched addresses / Travel times: Google Maps" appears on Scenario, Locations, Travel times, and Results, and in exports, wherever that content comes from Google.
- **Exports** (`frontend/export_utils.py`)
  - Version 1.0 columns and sheets are unchanged.
  - Diagnostics gain `priority` and `suggested_action`, and the plan workbook gains a "Plan Settings" sheet.
  - A new run-sheet workbook has one printable sheet per truck-shift (header, then stops with names and addresses).
  - Every cell is escaped, and empty or failed plans export.
- **Scenario management** (`frontend/views/saving.py`, `scenario.py`, `advanced_json.py`)
  - Save replaces only the copy this session opened or saved; otherwise it asks first.
  - Save as and Duplicate never overwrite, and Save as continues in the copy.
  - Delete needs a tick and leaves an open scenario unsaved.
- **Drafts** (`frontend/state/drafts.py`, `frontend/views/session.py`, new)
  - The URL keeps `?scenario=`.
  - While there are unsaved edits, each change writes the draft; saving or undoing the edits deletes it, and renaming the ID moves it.
  - A new session opens the saved scenario in the URL (else the sample with that ID) and offers Restore or Discard. Nothing is written over the draft until the planner answers.
  - Restore brings back storable travel times and a current plan. Google travel times come back only as their identity, with a prompt to calculate them again.
  - The sidebar says when unsaved edits are kept.
- **Tests and docs**
  - The fake backend gains the new calls.
  - Two Results assertions now read the plain-language status.
  - The plan, the README "Current status", and this log are updated.

### Found and fixed

- **Tests wrote to the real database.** Three Version 1.0 health tests started the backend with the default `DATABASE_PATH`, which is the real `data/route_optimizer.db`.
  - Before M6 their start-up changed nothing there. With M6, their start-up created the new schema in it on the first test run (18:06), before this was noticed.
  - What changed in the real database: an empty `scenario_drafts` table, the plans index, and `schema_meta` (version 2). The backend would add all three on its first M6 start anyway.
  - Nothing was removed. The one saved scenario there has no resolved coordinates, and its row was not changed.
  - The tests now use a temporary database. A later full run left the real database's modification time unchanged.
- **Stale widgets in the test harness.** Streamlit's test harness keeps elements from a run interrupted by `st.rerun()`. The new Save-as fields changed widget ID between runs, so they had no state and the next click failed.
  - Fix: the fields have fixed keys and their suggestions are seeded through session state, so the IDs stay the same.
- **A leftover M5 process.** The M5 manual run had left a Streamlit on port 8525 running. It was stopped; `run_app.ps1` uses 8000 and 8501, so it was not the planner's.

### Verification

| Check | Result | Evidence/notes |
|---|---|---|
| `python -m ruff format --check .` | PASS | |
| `python -m ruff check .` | PASS | |
| `python -m mypy backend frontend` | PASS | No issues in 170 source files. |
| `python -m pytest -q` | PASS | **749 passed** (690 before, 59 new). Same 3 OR-Tools/SWIG warnings. |
| Characterization tests A–F | PASS | Unchanged. |
| `python scripts/validate_m0.py` | PASS | 672 checks. |
| `python scripts/validate_m9_release.py` | PASS | |
| `python scripts/review_m2_payloads.py` | PASS | |
| `python scripts/smoke_m1.py` | PASS | `DATABASE_PATH` set to a scratch file. |
| `python -m pip check` | PASS | |
| Real database untouched by the final runs | PASS | Modification time unchanged across the full test run and the gate scripts (see "Found and fixed" for the earlier run). |

Plan M6 checks and their tests:

| Plan check | Tests |
|---|---|
| Local-time and unit formatting | `test_times_are_plant_local_and_say_when_they_fall_on_a_later_day`, `test_units_are_kilometres_hours_and_the_capacity_label`, `test_trucks_show_day_times_and_peak_load_against_capacity` |
| Location names resolved for every stop | `test_every_stop_shows_a_location_name_and_po_instead_of_ids`, `test_results_speak_the_planners_language`, `test_every_stop_has_a_name_and_the_run_sheets_match_the_stop_tables` (real app and backend) |
| Exports contain settings, priority, and run sheets and remain formula-safe | `test_m6_exports.py`: Version 1.0 columns first; priority and suggested action; Plan Settings sheet; run sheets reconcile with the stop table; formula-like planner text escaped |
| Empty and partial plans export | `test_empty_and_failed_plans_still_export`, plus the existing `test_export_generation_handles_empty_partial_plan` |
| Save/load round-trip is lossless | `test_a_saved_scenario_round_trips_losslessly` |
| Save as never overwrites | `test_if_exists_error_never_overwrites_and_the_default_still_replaces`, `test_save_as_never_overwrites_and_continues_in_the_copy`, `test_duplicate_copies_a_saved_scenario_without_opening_it`, `test_save_asks_before_replacing_a_different_saved_scenario` |
| Draft restore after a simulated session loss | `test_unsaved_edits_survive_a_session_loss_and_can_be_restored`, `test_a_kept_draft_can_be_discarded`, `test_unsaved_edits_are_restored_after_a_refresh` (real backend), `test_state_drafts.py` (9) |
| Expired coordinates stripped on load | `test_expired_coordinates_are_stripped_when_a_saved_scenario_is_loaded`, `test_fresh_coordinates_are_kept_and_drafts_are_cleaned_too`, `test_start_up_strips_expired_coordinates_and_records_the_schema` |
| Version 1.0 saved scenario opens with defaults | `test_a_version_1_0_saved_scenario_opens_with_defaults` (stored as Version 1.0 saved it; forms show the defaults; it solves and keeps the Version 1.0 shape) |

Also tested:

- Plans with the same inputs share a fingerprint whatever the settings, names, or notes.
- Delete removes plans and the draft.
- Draft requests are checked, and drafts never keep Google matrices.
- Google Maps links stay within Google's limits and chain correctly.
- Attribution appears only for Google content.
- Earlier plans can be viewed; a stale plan stays listed.
- A refresh reopens the saved scenario named in the URL.

### Manual checks

Real API on uvicorn (scratch database, offline provider) and Streamlit, in the browser:

- **Refresh mid-entry.**
  - Renamed the feasible sample, then reloaded the page. The app offered "Unsaved changes to A (Week 26 inbound (manual check)) from Sat 21 Nov 18:33". Restore brought the edit back, and the sidebar still said the edits were unsaved.
  - After solving, a further reload and restore also brought the plan back as current.
- **Results.** The stop table shows names, POs, quantities with units, and plant-local times; there are no internal IDs.
  - Fewest trucks: 1 of 6 truck-shifts, 216.0 km, longest route 7:33.
  - Balanced workload: 3 of 6, 254.0 km, 4:07. Both match Build 019.
- **Run sheet against the stop table.** The run sheet for the same plan and scenario matched the table on the page row for row: actions, location names, POs, quantities, arrive, start, and depart times, and loads.
- **Google Maps link.**
  - The link held 11 points in stop order, with repeated places merged.
  - Google Maps opened it with the stops in the same order: plant, Scarborough, Oakville, Mississauga, Concord (Vaughan), plant, Concord, Mississauga, Unionville (Markham), Brampton, plant.
  - The sample's coordinates are rounded fixture values, so Google labels them with nearby street addresses.
- **Compare.** Both plans were listed, the earlier one marked "Inputs: Same" (only the settings and the name differed). It opened as an earlier plan, clearly dated.
- **Scenario management.** Save, then Save as (the URL followed the new ID). Giving the copy the ID of the saved A showed the overwrite question; "Keep the saved one" left A unchanged. Duplicate made a new copy; Delete stayed disabled until ticked and removed only that copy.
- **Processes.** Servers stopped afterwards; no solver worker or Streamlit process was left running.

### Known issues

- OR-Tools/SWIG deprecation warnings remain.
- The M3 live-key manual check is still outstanding.
- No embedded Google map (D1 allows one only with a separate embed key).
- Phones may show fewer stops per Google Maps link than computers. The page says so.
- Two browser tabs on the same scenario share one draft slot; the later change wins.
- If the backend is unreachable when a refreshed page starts, the feasible sample opens and the draft is not offered; it stays on the backend.
- The Optimize summary shows the server's time limit even for a Version 1.0 scenario. This is the M5 behaviour, unchanged.
- `.env` was not read or changed.

### Gate status

- **V1.1-M6 COMPLETE.** Results are understandable without knowing any internal ID: every stop, PO, and reason is in planner terms, verified in tests and in the browser.
- No data loss on refresh: unsaved edits are kept on the backend and restored, verified in tests (fake and real backend) and in the browser.
- Clean working tree: PASS. The milestone was committed on branch `v1.1` at the user's request (2026-11-22).

### Next action

- Run the M3 live-key manual check when approved.
- Start V1.1-M7 (hardening, documentation, release).
