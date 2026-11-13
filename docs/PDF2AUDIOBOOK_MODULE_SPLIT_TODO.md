# PDF2Audiobook — Module Split TODO

**Status:** Open; no task started
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

- [ ] MS0.01 Add the M5 patch-target guard (`tests/test_patch_targets.py`). It passes at the baseline, and fails when `conversion.py` is made to reference a patched name directly.
- [ ] MS0.02 Write the M4 verbatim-move script in the scratchpad and run it at the baseline (zero moved functions).

## Phase MS1 — `pdf.py` (M1)

- [ ] MS1.01 Move OCR into `pdf_ocr.py`. Retarget the tests that patch `pdf._ocr_page_lines`, `pdf._cached_ocr_lines`, `pdf._ocr_engine_version`, `pdf.shutil` and `pdf.subprocess`. The Tesseract-gated tests run.
- [ ] MS1.02 Move page classification into `pdf_layout.py`. Move the `_footnote_line_indices` allowlist key.
- [ ] MS1.03 `pdf.py` keeps extraction, `_open`, `_lines` and `inspect_pdf`. M4 reports zero differences.

## Phase MS2 — `audio/__init__.py` (M2)

- [ ] MS2.01 Move synthesis into `audio/synthesis.py`. Retarget the tests that patch `audio._MAX_CACHED_WAV_BYTES`, `audio.time` and `audio.wave`.
- [ ] MS2.02 Move WAV I/O into `audio/wav.py`.
- [ ] MS2.03 Move speakability, voice markers and sentence chunking into `audio/speech_text.py`. `audio.encode_m4b` and `audio.read_cover_image` patches still take effect. M4 reports zero differences.

## Phase MS3 — `pipeline.py` (M3)

- [ ] MS3.01 Move the analysis orchestration into `analysis.py` behind `AnalysisServices`. Every name tests patch on `pipeline` still takes effect; the M5 guard covers `analysis.py`. M4 reports zero differences.

## Phase MS4 — Closure

- [ ] MS4.01 M7: mypy file list and allowlist keys updated.
- [ ] MS4.02 M8: `docs/MAINTAINER_GUIDE.md` and `CLAUDE.md` updated.
- [ ] MS4.03 Final gate: `/verify` passes with mypy on 3.11, 3.12 and 3.13; exact-head CI passes for every move commit; the "Found during split" list is reviewed with the user.

## Found during split

None yet.

## Progress ledger

| Date | Commit SHA | Completed tasks | Tests/CI evidence | Blockers |
| --- | --- | --- | --- | --- |
| 2026-11-13 | Not committed | Spec and TODO drafted; no work started | Not run | None |
