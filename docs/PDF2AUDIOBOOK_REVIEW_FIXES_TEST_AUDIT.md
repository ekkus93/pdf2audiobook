# PDF2Audiobook — Test Change Audit (2904f19..0c19845)

**Date:** 2026-10-25
**Task:** FX9.16d (spec R79). Every changed assertion or fixture input under `tests/` between
2904f19 and 0c19845, in files that existed at 2904f19. `git diff -U0 2904f19 0c19845 -- tests`
lists 94 hunks with removed lines; they are grouped below by reason, one row per file and test.

**Decision recorded:** spec R79 asked for one ledger line per change. A ledger cell cannot hold
this many lines, so the lines live here and the ledger row links to this file.

"Action" says what FX9 did: **restored** (put back to the 2904f19 text), **kept** (the change is
required by a spec requirement and has a truthful name), **renamed**, or **covered** (the old
scenario is tested by a named test elsewhere).

## A. Manifest schema version 2 → 3 (R48, FX8.06b)

Every manifest built by hand in a test now says `schema_version=3`, because v2 manifests are
rejected. Action: **kept** for all of them; no assertion about behaviour changed.

| File | Test or helper |
| --- | --- |
| test_adapter_protocols.py | test_injected_audio_adapters_change_chapter_identity |
| test_chapter_text_stale_files.py | `_manifest` |
| test_chapter_text_streamed_resume.py | test_render_chapter_texts_streams_existing_artifact_comparison |
| test_chapter_voice.py | `_manifest` |
| test_conversion_bounded_pending_text.py | `_setup_conversion` |
| test_corrupt_mp3_resume.py | test_resume_replaces_corrupt_mp3_even_with_matching_checksum |
| test_cover_art.py | test_cover_bytes_change_fingerprint_and_regenerate_mp3 |
| test_coverage_error_privacy.py | `_manifest` |
| test_manifest_read_privacy.py | test_valid_manifest_round_trip_is_unchanged |
| test_mp3_cache_identity.py | `_fixture` |
| test_mp3_resume_id3_integrity.py | test_mp3_resume_checks_actual_chapter_id3_tags |
| test_pack_m4b_safety.py | `make_book` |
| test_partial_conversion.py | test_one_failed_chapter_continues_and_resume_only_regenerates_it |
| test_pipeline_mp3_resume.py | test_mp3_resume_force_and_no_resume |
| test_pipeline_private_chapter_errors.py | test_missing_or_undecodable_chapter_text_is_private |
| test_prose_coverage_acceptance.py | `book` |
| test_resume_stat_race.py | test_resume_recovers_from_output_stat_race_without_leaking_path |
| test_scan_text_layer_fragments.py | test_fragmented_pdf_lines_become_one_block_with_every_span |
| test_source_span_coverage_integrity.py | `manifest_with_spans` |
| test_voice_marker_approval.py | `_run` |
| test_workspace.py | test_manifest |
| test_workspace_contract.py | test_manifest_schema_version_is_rejected (`== 3`), schema v2 → v3 round-trip rename |

## B. Budget limits raised so the worst-case reservation fits (R49)

R49 reserves each attempt's upper bound (prompt bytes + 128 + output cap) before sending. A limit
smaller than that bound refuses the first call, so the limits grew. The behaviour each test
checks is unchanged. Action: **kept**.

| File | Test | Old → new |
| --- | --- | --- |
| test_llm_book_budget_ledger.py | test_token_ceiling_… (renamed from `…records_response_that_crosses_limit`) | limit 75 → 200; reported 100 → 50 (the second call is refused before it is sent) |
| test_llm_book_budget_ledger.py | test_cost_budget_uses_explicit_rates | cost limit 0.00009 → 0.0003 |
| test_llm_exact_budget_boundary.py | test_exactly_exhausted_budget_delivers_result_then_denies_next_call | token limit 12 → 145, cost limit 0.000012 → 0.000145 (bound of one request) |
| test_llm_ledger_failures.py | test_invalid_json_response_still_charges_book_token_ledger | limit 100 → 2000 |
| test_llm_retry_budget_attempts.py | test_request_budget_stops_retry_after_first_sent_timeout | limit 100 → 100_000 |
| test_llm_token_cost_budgets.py | test_reported_token_limit_blocks_future_requests_and_fails_overshoot | limit 70 → 200; calls 2 → 1; report totals 100 → 50 |
| test_llm_token_cost_budgets.py | test_priced_cost_limit_uses_reported_usage_and_explicit_rates | cost limit 0.00009 → 0.00035 |
| test_llm_token_cost_budgets.py | test_missing_telemetry_fails_closed_when_token_limit_is_enabled | limit 100 → 200 |
| test_llm_unbilled_requests.py | `run_failed_request`, test_connect_failure_… | limit 100 → 3000 |
| test_llm_budget_price_integrity.py | test_invalid_token_rates_…, test_valid_zero_pricing_… | `upper_bound_usd` added: a USD budget needs a bounded request cost |
| test_acceptance_config.py | test_convert_no_llm_and_no_resume_cli_are_explicit_false | fake `convert` accepts `**kwargs` (new `accept_review` argument) |

## C. Budget tests whose old assertion was restored in FX9

| File | Test | Old → FX8 → FX9 |
| --- | --- | --- |
| test_llm_budget_integer_bounds.py | …unknown_without_sqlite_overflow | blocks → "bounded reserve succeeds" → **restored** (FX9.02); the bounded case is `test_llm_budget_fail_closed.py` |
| test_llm_budget_settlement_types.py | …is_unresolved_and_blocks_new_budgeted_request | blocks → bounded reserve succeeds → **restored** (FX9.02) |
| test_llm_book_budget_ledger.py | test_pending_budget_reservation_blocks_next_worker | An unbounded pending row blocks; FX8 renamed it to `…allows_safe_retry_only` and gave it a bound. **Covered** by `test_legacy_open_row_without_a_bound_blocks_a_token_budget` and the restored integer-bounds test |
| test_llm_exact_budget_boundary.py | test_overspent_token_budget_still_fails_closed | calls 1 → 0. **Kept**: the first call is refused before sending when its bound exceeds the limit; the post-flight overspend is **covered** by `test_provider_usage_above_the_reserved_bound_still_fails_closed` |
| test_llm_unbilled_requests.py | test_read_timeout_remains_unknown_and_blocks_token_budget | **Renamed** to `…is_charged_at_its_bound`: a bounded unknown row is charged, not blocking |
| test_llm_provider_matrix.py | test_rejected_generation_parameter_is_removed_and_remembered | `max_tokens` case now also asserts the `max_completion_tokens` substitution (R49). **Kept** |

## D. CLI diagnostics restored in FX9

| File | Test | Old → FX8 → FX9 |
| --- | --- | --- |
| test_cli_json_errors.py | test_json_error_contract | `json.loads(err)` → `splitlines()[-1]` → **restored** (FX9.07); OSError message **restored** (FX9.15) |
| test_cli_json_errors.py | test_config_show_json_error_is_only_on_stderr | same → **restored** (FX9.07) |
| test_cli_json_errors.py | test_human_error_output_remains_human_readable | "does not start with {" → deleted → **restored** (FX9.07) |
| test_cli_json_errors.py | test_non_domain_exception_diagnostics_are_content_free | `json.loads(err)` and OSError/ValueError messages → **restored** (FX9.07, FX9.15) |
| test_cli_error_privacy.py | test_analyze_output_path_failure_is_content_free | `json.loads(stderr)` → `splitlines()[-1]` → **restored** (FX9.07) |
| test_scan_text_layer_fragments.py | `_scan_pdf` and the tight-folio test comment | y=500 → 474 restored in FX8; "appear as page" **restored** (FX9.15) |

## E. Required by a second-review requirement (kept)

| File | Test | Old → new | Requirement |
| --- | --- | --- | --- |
| test_page_number_sequences.py | test_competing_edge_sequences_… → test_outermost_competing_edge_sequence_wins | keep both → nearer edge wins | R47: edge distance breaks ties between competing sequences. The equal-distance case is now tested in `test_page_number_ties.py` |
| test_page_number_sequences.py | test_explicit_page_labels_must_agree_with_folio_sequence → test_label_disagreement_warns_but_does_not_disable_folio_removal | none removed → removed with a warning | R47: a label disagreement never turns removal off |
| test_pagination_margin_safety.py | test_multiple_margin_numbers_are_ambiguous_not_folios → …outermost…wins | none removed → outermost removed | R47 |
| test_pagination_multiple_margin_numerals.py | test_multiple_margin_numerals_per_page_… → …outermost_of_competing_margin_sequences_is_removed | none removed → outermost removed | R47 |
| test_scan_text_layer_fragments.py | test_extraction_classifies_numbered_items_as_lists | kinds `[list, list]` → `[list, list, list, unknown]` | R46: the fixture gained a wrapped continuation line; the two original items are still lists |
| test_config_redaction.py | …url_userinfo_query_and_secret_fields | fragment secret added to the fixture URL | R55 (additive input) |
| test_config_redaction.py | test_config_redaction_masks_secret_field_values_but_keeps_env_names → …does_not_infer_secrets_from_user_dictionary_keys | `api_key`/`access_token` keys masked → shown | R55: never mask by name |
| test_chapter_edit_protection.py | test_user_edited_chapter_survives_reanalysis… | warning "…numbers: 1" → "…numbers: 1, 2" | R53: each edited field is protected separately, and chapter 2's start edit counts |
| test_chapter_edit_privacy.py | test_unalignable_edited_chapter_error… → test_boundary_edit_moves_neighboring_boundary_without_private_diagnostics | error → the neighbouring boundary moves | R53. The error path is **covered** by `test_impossible_boundary_merge_names_chapter_without_source_text` |
| test_pack_m4b_safety.py | test_pack_m4b_cli_refuses_stale_audio_… → …text_stale_audio_… | stale fingerprint → stale `text_sha256` | R52: `pack-m4b` no longer compares convert-time fingerprints |
| test_tts_retries.py | FlakyProvider | plain `RuntimeError` retried → error marked `transient = True` | R61: only transient errors are retried |
| test_pipeline_mp3_resume.py | test_mp3_resume_force_and_no_resume | a corrupt-sidecar step inserted before `force=True`; call counts shift by one | Additive: the force, no-resume and changed-voice steps remain |
| test_audio_cache_bounded_io.py | test_deeply_nested_wav_metadata_… | `"[" * 100_000` → depth-8 list | The old payload was rejected by the size cap. **Replaced** by `test_cache_depth_reaches_check.py` (FX9.16b) |
| test_audio_narration_normalization.py | test_punctuated_pronunciation_keys_… | `UNITED, (SEEPLUS)` → `United, (seeplus)` | R58 case transfer; later **deleted** with the "Doctor." period in FX9.13 |
| test_review_ui.py | imports; save request body | body built by a Python copy of the page script | R10. **Covered** by `test_review_ui_page_script.py`, which runs the page's own script (FX9.16c) |
| test_voice_marker_approval.py | two `match=` patterns | `"chapter\(s\): 1"` → raw string | Lint fix only |
