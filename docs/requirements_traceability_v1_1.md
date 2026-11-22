# Requirements traceability: Version 1.1

**Release:** v1.1.0
**Plan:** `project_plan_v1.1.md` (§3 scope, §16 acceptance criteria)
**Evidence:** `build_log.md`, builds 014 (V1.1-M0) to 021 (V1.1-M7)
**Version 1.0 matrix:** [requirements_traceability.md](requirements_traceability.md)

Each acceptance criterion of plan §16 is listed with the milestone that delivered it, the automated tests that prove it, and any manual check recorded in the build log. `scripts/validate_release.py` checks that every criterion is listed here and that every test named here exists.

## Acceptance criteria

### Forms and JSON

| ID | Criterion | Milestone | Automated evidence | Manual evidence |
|---|---|---|---|---|
| AC-01 | A planner creates a complete scenario and obtains a plan without opening JSON. | M4, M7 | `test_a_complete_scenario_is_built_and_solved_without_opening_json`, `test_a_form_built_week_at_the_documented_size_plans_completely` | Build 018: forms-only run in the browser |
| AC-02 | Every scenario field can be entered through a form. | M3, M4, M5 | `test_a_new_scenario_is_built_from_the_scenario_and_locations_forms`, `test_scenario_details_period_fit_and_defaults`, `test_trucks_are_added_edited_duplicated_and_deleted_through_forms`, `test_all_three_movements_are_added_through_the_form`, `test_routing_options_make_travel_times_stale_and_are_sent`, `test_settings_are_stored_minimally_and_make_only_the_plan_stale` | Build 018 |
| AC-03 | JSON can be viewed, edited, uploaded, and downloaded, and always shows the same scenario as the forms. | M2 | `test_complete_round_trip_yields_an_equal_scenario_and_matrix`, `test_clean_round_trip_yields_an_equal_clean_scenario`, `test_clean_view_hides_and_complete_view_shows_derived_data`, `test_unapplied_editor_text_and_view_survive_visiting_other_pages` | Build 016: upload in the browser (the test harness cannot upload files) |
| AC-04 | Unmodified Version 1.0 JSON loads into the forms and solves with the same result. | M0, M2, M6 | `test_version_1_0_payload_loads_validates_uses_its_matrix_and_solves_identically`, `test_default_results_match_version_1_0`, `test_a_version_1_0_saved_scenario_opens_with_defaults` | Build 021: Version 1.0 JSON loaded, solved, saved, exported |
| AC-05 | Invalid JSON never replaces a valid scenario. | M2 | `test_a_syntax_error_never_replaces_the_scenario`, `test_json_with_errors_never_replaces_a_valid_scenario`, `test_version_1_0_payload_b_is_refused_over_a_valid_scenario` | — |

### Address only

| ID | Criterion | Milestone | Automated evidence | Manual evidence |
|---|---|---|---|---|
| AC-06 | No form contains a latitude or longitude input. | M3 | `test_no_widget_on_any_page_asks_for_latitude_or_longitude`, `test_no_page_has_a_latitude_or_longitude_input` | Build 017 |
| AC-07 | A location needs only a name and an address. | M1, M3 | `test_location_accepts_address_only_and_derived_fields`, `test_address_only_payload_validates`, `test_adding_needs_a_name_and_an_address_and_suggests_a_unique_id`, `test_typed_addresses_become_a_current_matrix_and_a_feasible_plan` | Build 017 |
| AC-08 | The backend resolves addresses and returns a per-location status. | M1 | `test_resolve_returns_rows_in_request_order_with_a_summary`, `test_results_keep_the_callers_ids_and_request_order`, `test_address_only_scenario_resolves_validates_and_solves` | Live check with a Google key: not run (see the release checklist) |
| AC-09 | Vague, partial, ambiguous, and far-away matches require confirmation before use. | M1, M3 | `test_doubtful_matches_need_review`, `test_multiple_matches_list_the_alternatives`, `test_far_from_plant_reports_the_distance`, `test_confirming_a_review_match_makes_it_ready_and_confirmed`, `test_travel_times_cannot_be_calculated_while_a_location_is_not_ready` | Build 017 (offline provider) |
| AC-10 | One bad address does not block the others. | M1, M3, M7 | `test_unknown_address_fails_only_its_own_row`, `test_a_not_found_address_is_corrected_and_resolved_again`, `test_a_failure_part_way_keeps_what_was_already_resolved` | — |
| AC-11 | Editing an address invalidates only what depends on it. | M2, M3 | `test_row_address_edit_unresolves_that_location_and_stales_travel_times_and_plan`, `test_editing_one_address_resets_only_that_location_and_stales_travel_times`, `test_an_edited_address_is_resolved_alone_and_a_repeat_is_served_from_the_cache` | — |
| AC-12 | Google is called only on an explicit action; repeated identical requests are served from cache. Under D6 this covers address lookups; travel times are reused within the session. | M1, M3 | `test_rerunning_and_visiting_pages_makes_no_provider_calls`, `test_fleet_and_task_edits_keep_travel_times_and_call_no_provider`, `test_repeat_resolve_is_served_from_cache_unless_forced`, `test_second_resolve_is_served_from_the_cache`, `test_google_matrices_are_never_cached_and_the_estimate_says_so` | — |
| AC-13 | Coordinates older than 30 days are not used. | M1, M6 | `test_coordinates_older_than_thirty_days_produce_expired_warning`, `test_row_coordinates_older_than_thirty_days_unresolve_and_stale_everything`, `test_entry_expires_at_the_ttl`, `test_expired_coordinates_are_stripped_when_a_saved_scenario_is_loaded`, `test_start_up_strips_expired_coordinates_and_records_the_schema` | — |

### Controls are real

| ID | Criterion | Milestone | Automated evidence | Manual evidence |
|---|---|---|---|---|
| AC-14 | Route-distance limits are enforced by the solver and re-checked by the validator. | M4 | `test_distance_limit_is_enforced_by_the_solver`, `test_validator_rejects_routes_over_the_distance_limit`, `test_a_task_beyond_every_distance_limit_is_reported_individually` | — |
| AC-15 | Priority decides which tasks a partial plan keeps and never relaxes a hard rule. | M4 | `test_shortage_keeps_the_higher_priorities`, `test_reversed_priorities_keep_the_other_tasks`, `test_every_task_is_scheduled_when_everything_fits_whatever_the_priority`, `test_pickup_drop_pairs_are_kept_or_dropped_together` | Build 021: the fleet shortage sample in the browser |
| AC-16 | With no options supplied, results match Version 1.0. | M0, M5 | `test_default_results_match_version_1_0`, `test_default_options_reproduce_the_version_1_0_solve`, `test_all_default_settings_leave_the_version_1_0_shape` | — |
| AC-17 | Each objective mode produces its documented effect on the comparison fixture. | M5 | `test_fixture_v11_e_objective_modes_differ_as_documented`, `test_balance_presets_are_frozen`, `test_objective_chosen_on_the_page_changes_the_plan` | Build 019 |
| AC-18 | Search effort makes the time limit meaningful. | M5, M7 | `test_thorough_search_respects_the_time_limit_and_is_no_worse`, `test_the_time_limit_is_bounded_by_the_server_and_sent_with_the_solve`, `test_a_week_too_large_for_its_time_limit_is_a_timeout_not_a_shortage`, `test_a_partial_plan_cut_short_by_the_time_limit_says_more_may_fit` | Build 021: size measurements |
| AC-19 | The travel-time buffer is applied consistently and recorded on the plan. | M5, M6 | `test_solver_precheck_and_validator_see_the_same_buffered_times`, `test_buffer_deadline_holds_at_1_0_and_is_diagnosed_at_1_5`, `test_plan_workbook_adds_a_settings_sheet_with_the_buffer` | — |
| AC-20 | Every returned plan passes independent validation of capacity, time, pairing, shifts, tags, duration, distance, and deadlines. | M4, M5 | `test_default_plans_pass_independent_validation`, `test_every_mode_and_effort_passes_the_independent_validator`, `test_validator_rejects_a_route_without_the_required_tags`, `test_validator_rejects_routes_over_the_duration_limit`, `test_validator_rejects_routes_over_the_distance_limit`, `test_validator_rejects_a_wrong_route_duration` | — |

### Usability and safety

| ID | Criterion | Milestone | Automated evidence | Manual evidence |
|---|---|---|---|---|
| AC-21 | Results show local times, kilometres, location names, and PO numbers. | M6 | `test_times_are_plant_local_and_say_when_they_fall_on_a_later_day`, `test_units_are_kilometres_hours_and_the_capacity_label`, `test_every_stop_shows_a_location_name_and_po_instead_of_ids`, `test_every_stop_has_a_name_and_the_run_sheets_match_the_stop_tables` | Build 020: run sheet reconciled with the stop table |
| AC-22 | Task and location spreadsheets can be previewed and applied, all-or-nothing. | M3, M4 | `test_a_checked_import_is_applied_in_the_chosen_mode`, `test_a_failing_import_changes_nothing`, `test_an_invalid_import_row_raises_and_applies_nothing`, `test_task_import_preview_reports_row_errors`, `test_location_import_preview_maps_rows_and_reports_issues` | Build 018: upload in the browser |
| AC-23 | Scenarios can be listed, saved as, duplicated, and deleted; nothing is overwritten without confirmation. | M3, M6 | `test_saved_scenarios_are_listed_newest_first_with_counts`, `test_save_asks_before_replacing_a_different_saved_scenario`, `test_save_as_never_overwrites_and_continues_in_the_copy`, `test_duplicate_copies_a_saved_scenario_without_opening_it`, `test_delete_needs_a_confirmation_and_leaves_the_open_scenario_unsaved`, `test_if_exists_error_never_overwrites_and_the_default_still_replaces` | Build 020 |
| AC-24 | Unsaved work survives a browser refresh. | M6 | `test_unsaved_edits_survive_a_session_loss_and_can_be_restored`, `test_unsaved_edits_are_restored_after_a_refresh`, `test_a_refresh_reopens_the_saved_scenario_named_in_the_url` | Build 020: refresh mid-entry in the browser |
| AC-25 | Each solve is kept as a separate plan; recent plans can be compared. | M5, M6 | `test_two_solves_give_two_retrievable_plans_and_history`, `test_history_keeps_only_the_newest_plans_per_scenario`, `test_plans_are_compared_and_an_earlier_plan_can_be_viewed`, `test_comparison_marks_plans_with_the_same_inputs` | Build 020 |
| AC-26 | The backend works without Streamlit; Streamlit imports no backend code. | M0 | `test_backend_application_does_not_import_streamlit`, `test_frontend_has_no_solver_google_or_backend_implementation_imports`, `test_frontend_boundary_scan_reaches_sub_packages`, `test_every_backend_application_module_imports` | — |
| AC-27 | No key or secret appears in forms, JSON, exports, logs, or tracked files. | M1, M3, M7 | `test_no_key_or_address_in_responses_logs_or_cache_rows`, `test_config_reports_settings_without_any_secret`, `test_invalid_key_fails_once_without_exposing_key`, `test_an_auth_rejection_reason_names_the_cause_but_never_the_key`, `test_a_routes_rejection_carries_googles_reason`, `test_secret_and_generated_paths_are_ignored`, `test_a_key_shaped_value_is_found` | `scripts/validate_release.py` scans tracked files, logs, exports, and the database (Build 021) |
| AC-28 | Every Version 1.0 test still passes; every milestone has evidence in `build_log.md`. | M0 to M7 | `test_frozen_files_are_unchanged`, `test_default_results_match_version_1_0`, and the whole suite | Builds 014 to 021 |

## Scope coverage

| Scope item (plan §3) | Delivered in | Criteria |
|---|---|---|
| M-1 Forms for every input | M3, M4 | AC-01, AC-02 |
| M-2 JSON retained on the same scenario | M2 | AC-03, AC-04, AC-05 |
| M-3 Address-only locations | M1, M3 | AC-06, AC-07, AC-08 |
| M-4 Explicit resolve, review, travel times, with caching | M1, M3 | AC-09 to AC-13 |
| M-5 No regression | M0 to M7 | AC-04, AC-16, AC-28 |
| S-1 Route-distance limit | M4 | AC-14 |
| S-2 Priority-aware partial plans | M4 | AC-15 |
| S-3 Objective modes and search effort | M5 | AC-17, AC-18 |
| S-4 Travel-time buffer | M5 | AC-19 |
| S-5 Spreadsheet import with templates | M3, M4 | AC-22 |
| S-6 Scenario list, save as, duplicate, delete, drafts | M3, M6 | AC-23, AC-24 |
| S-7 Readable results, run sheets, plan history | M5, M6 | AC-21, AC-25 |
| S-8 Fixes F8, F9, F10, F15, F16, F17 | M0, M4, M5, M7 | AC-20, AC-26; see below |
| C-1 to C-4 (could have) | Not built | Never gated the release |

## Code-review findings (plan §2)

| Finding | Resolution | Milestone | Evidence |
|---|---|---|---|
| F1 UI is a JSON editor | Forms for every input | M2 to M5 | AC-01, AC-02 |
| F2 UI demands coordinates | Address-only workflow | M3 | AC-06, AC-07 |
| F3 Geocode endpoint unfit for forms | Resolve endpoint, match rules, cache | M1 | AC-08 to AC-10 |
| F4 Distance limit ignored | Enforced and validated | M4 | AC-14 |
| F5 Priority ignored | Weighted partial plans | M4 | AC-15 |
| F6 Time limit decorative | Search effort | M5 | AC-18 |
| F7 Everything on one truck | Objective modes | M5 | AC-17 |
| F8 3-second client timeout | Per-operation timeouts | M0 | `test_each_operation_uses_its_own_timeout` |
| F9 Plan ID overwritten | Unique IDs, history | M5 | `test_each_plan_gets_a_unique_short_id_and_its_metadata` |
| F10 Validator gaps | Tags, duration, distance re-checked | M4 | AC-20 |
| F11 Coarse fingerprints | Granular freshness | M2 | `test_renaming_a_location_id_keeps_travel_times_current` |
| F12 Import preview only, two alias tables | One backend contract, apply | M4 | `test_the_frontend_has_no_column_alias_table_of_its_own` |
| F13 No scenario list; silent overwrite | List and overwrite guard | M3, M6 | AC-23 |
| F14 UTC, seconds, metres, IDs | Planner-readable results | M6 | AC-21 |
| F15 Version drift | One version source; release script reads `VERSION` | M0, M7 | `test_backend_reports_the_version_file`, `test_a_version_the_backend_does_not_report_fails`, `test_this_checkout_passes` |
| F16 Boundary scan not recursive | Recursive scan | M0 | `test_frontend_boundary_scan_reaches_sub_packages` |
| F17 Solve blocks the API | Worker process | M5 | `test_health_responds_while_a_solve_is_running` |
| F18 Google terms | D1, D2, D6; terms re-read in M0 and M7 | M0 to M7 | AC-13, `docs/google_api_setup.md` |
| F19 Key in httpx log lines | Transport loggers quietened | M1 | `test_no_key_or_address_in_responses_logs_or_cache_rows` |

Found in M7 and fixed there (Build 021):

| Finding | Resolution | Evidence |
|---|---|---|
| A large scenario that ran out of time was reported as a partial plan blaming fleet time | OR-Tools' plain failure after the whole time limit counts as a timeout; a partial plan cut short says more POs may fit | `test_a_search_that_used_its_whole_limit_without_a_plan_ran_out_of_time`, `test_a_week_too_large_for_its_time_limit_is_a_timeout_not_a_shortage` |
| Google rejections gave no reason (the HTTP 400 met in M5) | Google's reason shown, key removed, never logged; a past departure time refused before sending | `test_a_routes_rejection_carries_googles_reason`, `test_a_past_departure_time_is_refused_before_anything_is_sent`, `test_a_past_departure_time_blocks_calculation_with_a_reason` |
| More than 100 addresses or locations failed with a contract error | Resolve in batches; a clear message above 100 travel-time locations | `test_addresses_are_resolved_in_requests_the_backend_accepts`, `test_more_locations_than_one_calculation_allows_is_explained` |
