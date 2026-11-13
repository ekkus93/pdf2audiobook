# PDF2Audiobook — Module Split TODO

**Status:** Open; MS0–MS4.02 done with exact-head CI; MS4.03 waits on the user's review of the "Found during split" list
**Date:** 2026-11-13
**Baseline:** master at 676abc50eff5cc8bb9bb8c201277d5cfbc7e023b
**Specification:** `docs/PDF2AUDIOBOOK_MODULE_SPLIT_SPEC.md` (M1–M8)

## Working rules

- Work in the order below. Use `[x]` only when the implementation exists and its named checks pass. Check a parent only when all its subitems are checked.
- Every task is a pure move (spec §2). Existing tests change only a monkeypatch target or an import path, to follow a moved name.
- Don't re-export moved private names; do re-export every public name.
- One move per commit: `refactor(<scope>): move <job> into <module>`, no body, no `Co-Authored-By` trailer. Run `/verify` and mypy on 3.12 and 3.13 before each commit.
- After CI finishes, add a ledger row in a separate `docs:` commit with the full SHA and the real run ID. The ledger is append-only.

## Phase MS0 — Safety net

- [x] MS0.01 Add the M5 patch-target guard (`tests/test_patch_targets.py`). It passes at the baseline, and fails when `conversion.py` is made to reference a patched name directly.
  - Evidence: commit 9e3b2367512bee10341ae03beb9116ae0bdd685b, `tests/test_patch_targets.py` (3 tests). It passes at the baseline with `digest_file` and `write_json` allowed in `conversion.py`, because the tests that patch them on `pipeline` exercise analysis only. Adding `from pdf2audiobook.workspace import read_manifest` to `conversion.py` made it fail ("conversion.py uses patched pipeline names directly: {'read_manifest'}"). Pushed with ea4351581bc76b69c0ec613c5ebc29bf63e3ee8c, so it has no CI run of its own; covered by run [43391646308](https://github.com/ekkus93/pdf2audiobook/actions/runs/43391646308).
- [x] MS0.02 Write the M4 verbatim-move script in the scratchpad and run it at the baseline (zero moved functions).
  - Evidence: the script compares the `ast.dump` of every top-level function, class and constant in `pdf.py`, `audio/__init__.py` and `pipeline.py` at the baseline with wherever that name now lives. At the baseline: 129 definitions, 0 moved, 0 differences.

## Phase MS1 — `pdf.py` (M1)

- [x] MS1.01 Move OCR into `pdf_ocr.py`. Retarget the tests that patch `pdf._ocr_page_lines`, `pdf._cached_ocr_lines`, `pdf._ocr_engine_version`, `pdf.shutil` and `pdf.subprocess`. The Tesseract-gated tests run.
  - Evidence: commit b77f5316a0153e708f65491bc1b3e8f966738fbb. `pdf_ocr.py` (443 lines) holds 16 definitions. `pdf.py` imports only `_page_ocr_strategy` and `_apply_ocr_fallback`, which its extraction calls, plus `tesseract_languages` and `missing_ocr_languages` as re-exports. `_ocr_page_lines`, `_cached_ocr_lines` and `_ocr_engine_version` no longer exist on `pdf`. Six test files first failed to import them, and one patch split over two lines failed with `AttributeError`, as designed. 19 test files were retargeted, and only patch targets and import paths changed: 46 references, including `pdf.shutil` and `pdf.subprocess`. The Tesseract-gated tests ran; 2055 passed, 1 skipped. Python CI run [43392042301](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392042301) passed.
  - Note: done after MS1.02, because OCR uses `_PageVisuals` and `_lines` from `pdf_layout`, and `pdf_ocr` must not import `pdf`.
- [x] MS1.02 Move page classification into `pdf_layout.py`. Move the `_footnote_line_indices` allowlist key.
  - Evidence: commit ea4351581bc76b69c0ec613c5ebc29bf63e3ee8c. `pdf_layout.py` (497 lines) holds 15 definitions, including `_lines` and `_positive_finite_number`, which page classification needs. `pdf.py` imports back only the 10 names its own code still calls, so a patch on `pdf._lines` still reaches extraction. The `_footnote_line_indices` allowlist key moved with its ceiling of 112. No test changed; 2055 passed, 1 skipped. Python CI run [43391646308](https://github.com/ekkus93/pdf2audiobook/actions/runs/43391646308) passed.
- [x] MS1.03 `pdf.py` keeps extraction, `_open`, `_lines` and `inspect_pdf`. M4 reports zero differences.
  - Evidence: `pdf.py` is 624 lines (was 1,505): extraction, `_open`, `_lines` (imported) and `inspect_pdf`. The M4 script reports 31 definitions moved out of `pdf.py` with 0 differences.

## Phase MS2 — `audio/__init__.py` (M2)

- [x] MS2.01 Move synthesis into `audio/synthesis.py`. Retarget the tests that patch `audio._MAX_CACHED_WAV_BYTES`, `audio.time` and `audio.wave`.
  - Evidence: commit 891f284b5d33c87b4b604fb17253f92517467a09. `audio/synthesis.py` (562 lines) holds 17 definitions: synthesis, plus `wav_bytes`, `read_wav` and `_MAX_CACHED_WAV_BYTES`. The facade re-exports `synthesize_chunks`, `wav_bytes` and `read_wav`. 5 test files retargeted: `audio._MAX_CACHED_WAV_BYTES` and `audio.time.sleep` go to `audio.synthesis`, `audio.wave` and `audio.np` to `audio.encoding`, where the exercised `encode_mp3` lives, and `audio._write_pcm_chunk` to `audio.wav`. Python CI run [43392763651](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392763651) passed.
  - Note: `wav_bytes` and `read_wav` belong to the chunk cache, not to `audio/wav.py` as spec M2 lists. `_MAX_CACHED_WAV_BYTES` bounds both them and the synthesis replay and store, and tests patch it once. Splitting them would give that patch two homes, and a test patching one would silently miss the other. Done last in MS2, because synthesis uses both `audio.wav` and `audio.speech_text`.
- [x] MS2.02 Move WAV I/O into `audio/wav.py`.
  - Evidence: commit 2124ad92ab8a5740280a82ba67a53e81b892a030. `audio/wav.py` (63 lines) holds the streaming chapter-WAV writer (4 definitions). No test changed. Python CI run [43392286078](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392286078) passed.
- [x] MS2.03 Move speakability, voice markers and sentence chunking into `audio/speech_text.py`. `audio.encode_m4b` and `audio.read_cover_image` patches still take effect. M4 reports zero differences.
  - Evidence: commit dbb55913b7bb7da6efef3a4f2aec1fb0b7e0a1d4. `audio/speech_text.py` (298 lines) holds 17 definitions, and every public one is re-exported from `audio`. One test import of the private `_NARRATION_TRANSLATION` was retargeted. `audio.encode_m4b` and `audio.read_cover_image` stay facade names, and their patches pass. `audio/__init__.py` is 99 lines (was 945), holding only the facade, the output paths and the cover image. The M4 script reports 69 definitions moved so far with 0 differences. Python CI run [43392510424](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392510424) passed.

## Phase MS3 — `pipeline.py` (M3)

- [x] MS3.01 Move the analysis orchestration into `analysis.py` behind `AnalysisServices`. Every name tests patch on `pipeline` still takes effect; the M5 guard covers `analysis.py`. M4 reports zero differences.
  - Evidence: commit 0792bf2f069127990c560d1cf7efb2110a333941. `analysis.py` (872 lines) holds 23 definitions plus `AnalysisServices`, with 15 fields: the 13 names tests patch, plus `_llm_cache_identity` and `_resolve_auto_llm_model`, which stay in `pipeline` because the latter calls `create_provider`. `_AnalysisRun` has a `services` field; `pipeline._analysis_services()` builds the record from module globals on every `analyze_book` call. `pipeline.py` is 471 lines (was 1,204). It re-exports every public name it had except the stdlib `dataclass` and `field`.
  - Evidence: after undoing the services plumbing in the AST (`run.services.X` and `services.X` back to `X`; the `services` parameter, field and argument removed), all 23 moved definitions and `analyze_book` equal the baseline. The guard covers `analysis.py` with no names allowed. All 15 `AnalysisServices(...)` keywords map to the same-named `pipeline` global. Bypassing each patched name in `_analysis_services()` fails the tests that patch it for 8 of 13 names (`_analysis_stage_fingerprints`, `create_provider`, `detect_llm_headings`, `extract_pdf`, `log_event`, `pagination_cleanup`, `propose_chapters`, `propose_llm_cleanup`).
  - Note: the other five bypass mutants survive because those tests' outcomes don't depend on analysis getting the patched object, not because the patch misses. The tests that patch `read_manifest` and `render_chapter_texts` also replace `analyze_book`, so they exercise conversion. The `CachedLLMProvider` patch is a pass-through, and the `digest_file` and `write_json` patches don't affect what those tests assert. Recorded under "Found during split". One test (`tests/test_hand_edit_merge_characterization.py`) moved its two private references to `analysis`. Python CI run [43394065316](https://github.com/ekkus93/pdf2audiobook/actions/runs/43394065316) passed.

## Phase MS4 — Closure

- [x] MS4.01 M7: mypy file list and allowlist keys updated.
  - Evidence: `pyproject.toml` lists the six new modules for mypy (52 files, clean on 3.11, 3.12 and 3.13). The `_footnote_line_indices` allowlist key moved to `pdf_layout.py`.
- [x] MS4.02 M8: `docs/MAINTAINER_GUIDE.md` and `CLAUDE.md` updated.
  - Evidence: commit 94d4417dcb636aa1130a06ca956b785b7935102a. `docs/MAINTAINER_GUIDE.md` covers the module map, the analysis steps in `analysis.py` with `AnalysisServices` and the guard, `pdf_ocr.py` in the outlined-text note, and the audio package layout. The `CLAUDE.md` facade rule now covers `pdf`, the no-re-export rule for private names and the services records. Python CI run [43394134458](https://github.com/ekkus93/pdf2audiobook/actions/runs/43394134458) passed.
- [ ] MS4.03 Final gate: `/verify` passes with mypy on 3.11, 3.12 and 3.13; exact-head CI passes for every move commit; the "Found during split" list is reviewed with the user.
  - Note: not checked. `/verify` passes, with mypy on 3.11, 3.12 and 3.13, and every move commit has passing exact-head CI. The golden snapshot is unchanged: no commit touched `tests/fixtures/golden/`. One clause remains: the user's review of the "Found during split" list.

## Found during split

- Test sensitivity, not a bug (`tests/test_pipeline_footnote_warning_preservation.py`, `tests/test_pipeline_private_source_errors.py`): these tests patch `pipeline.CachedLLMProvider`, `pipeline.digest_file` and `pipeline.write_json`, but their assertions pass even when analysis gets the real objects. The patches reach analysis (the services mapping and the guard prove it); the tests just don't depend on them. It was the same before the move.
- Spec M2 vs code: `wav_bytes` and `read_wav` stay with synthesis, not in `audio/wav.py`, so the patched `_MAX_CACHED_WAV_BYTES` keeps one home (see MS2.01).
- Facade names dropped: incidental imports that `pdf` and `audio` no longer need. These are stdlib modules such as `shutil`, `time` and `numpy`, and helpers that belong to other modules, such as `fingerprint` and `AudioError`. No caller used them through these modules; the tests that patched `pdf.shutil`, `pdf.subprocess`, `audio.time`, `audio.wave` and `audio.np` were retargeted. `pipeline` keeps every public name except the stdlib `dataclass` and `field`.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started | Not run | None |
| 2026-11-13 | ea4351581bc76b69c0ec613c5ebc29bf63e3ee8c | MS0.01 (guard, 9e3b2367512bee10341ae03beb9116ae0bdd685b, pushed with it) and MS1.02: page classification into `pdf_layout.py` | `/verify` 2055 passed, 1 skipped; M4: 15 moved, 0 differences; exact-head Python CI [43391646308](https://github.com/ekkus93/pdf2audiobook/actions/runs/43391646308) passed | MS4.03 needs the user's review |
| 2026-11-13 | b77f5316a0153e708f65491bc1b3e8f966738fbb | MS1.01 and MS1.03: OCR into `pdf_ocr.py`; `pdf.py` 1,505 → 624 lines; 19 test files retargeted (patch targets and imports only) | `/verify` 2055 passed, 1 skipped (Tesseract tests ran); M4: 31 moved, 0 differences; exact-head Python CI [43392042301](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392042301) passed | MS4.03 needs the user's review |
| 2026-11-13 | 2124ad92ab8a5740280a82ba67a53e81b892a030 | MS2.02: streaming chapter-WAV writer into `audio/wav.py` | `/verify` 2055 passed, 1 skipped; exact-head Python CI [43392286078](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392286078) passed | MS4.03 needs the user's review |
| 2026-11-13 | dbb55913b7bb7da6efef3a4f2aec1fb0b7e0a1d4 | MS2.03: speech text into `audio/speech_text.py` | `/verify` 2055 passed, 1 skipped; M4: 52 moved, 0 differences; exact-head Python CI [43392510424](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392510424) passed | MS4.03 needs the user's review |
| 2026-11-13 | 891f284b5d33c87b4b604fb17253f92517467a09 | MS2.01: synthesis and the chunk-cache codecs into `audio/synthesis.py`; `audio/__init__.py` 945 → 99 lines | `/verify` 2055 passed, 1 skipped; M4: 69 moved, 0 differences; exact-head Python CI [43392763651](https://github.com/ekkus93/pdf2audiobook/actions/runs/43392763651) passed | MS4.03 needs the user's review |
| 2026-11-13 | 0792bf2f069127990c560d1cf7efb2110a333941 | MS3.01: analysis into `analysis.py` behind `AnalysisServices`; `pipeline.py` 1,204 → 471 lines | `/verify` 2055 passed, 1 skipped; 23 definitions equal the baseline once services are undone; 8 of 13 bypass mutants fail their tests; the other 5 don't run analysis with the patch or don't depend on it; exact-head Python CI [43394065316](https://github.com/ekkus93/pdf2audiobook/actions/runs/43394065316) passed | MS4.03 needs the user's review |
| 2026-11-13 | 94d4417dcb636aa1130a06ca956b785b7935102a | MS4.01–MS4.02: maintainer guide, CLAUDE.md, mypy list | Docs only; exact-head Python CI [43394134458](https://github.com/ekkus93/pdf2audiobook/actions/runs/43394134458) passed | MS4.03 needs the user's review |
