# Canonical Acceptance Fixtures

These files define deterministic, non-sensitive scenarios used across domain, solver, API, and frontend tests.

## Principles

- Locations and addresses are fictional.
- Travel matrices are deterministic offline test data, not real Google results.
- Datetimes include an explicit timezone offset unless a case intentionally tests invalid/date-only input.
- Quantities are always positive.
- Scenario expectations describe required behavior, not a specific route unless route order is the subject of the test.
- Live Google smoke tests use separate developer-provided addresses and credentials and never overwrite these files.

## Files

- `manifest.json`: fixture registry and required A–H coverage.
- `shared_locations.json`: common plant, supplier, customer, and hub locations.
- `shared_matrix.json`: asymmetric distance and duration matrix.
- `scenario_a_feasible_mixed.json`: three-truck feasible mixed workload.
- `scenario_b_capacity_impossible.json`: quantity above all capacities.
- `scenario_c_deadline_impossible.json`: individually impossible due time.
- `scenario_d_collective_shortage.json`: individually feasible but collectively infeasible workload.
- `scenario_e_pair_precedence.json`: same-truck and pickup-before-drop behavior.
- `scenario_f_multiday_shifts.json`: one physical truck with separate daily shifts.
- `scenario_g_routing_failures.json`: provider failure mapping.
- `scenario_h_timezone_boundaries.json`: date-only and daylight-saving validation.

Run the M0 fixture check from the project root:

```powershell
python scripts/validate_m0.py
```
