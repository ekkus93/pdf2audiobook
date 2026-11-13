# PDF2Audiobook — Module Split Specification

**Status:** Draft; M1–M8 not implemented
**Date:** 2026-11-13
**Baseline:** master at 676abc50eff5cc8bb9bb8c201277d5cfbc7e023b
**Parent specification:** `docs/PDF2AUDIOBOOK_SPEC.md` (§12 engineering principles)
**Companion:** `docs/PDF2AUDIOBOOK_MODULE_SPLIT_TODO.md`

## 1. Purpose and scope

Three modules each hold several unrelated jobs (measured at the baseline):

| ID | Module | Lines | Jobs |
| --- | --- | --- | --- |
| M1 | `src/pdf2audiobook/pdf.py` | 1,505 | extraction (~480), page classification (~420), OCR (~380), `inspect_pdf` (~70) |
| M2 | `src/pdf2audiobook/audio/__init__.py` | 945 | synthesis (~430), speakability and voice markers (~140), WAV I/O (~100), sentence chunking (~100), paths and cover (~20) |
| M3 | `src/pdf2audiobook/pipeline.py` | 1,204 | re-export facade, analysis orchestration, conversion entry point |

This work moves code between modules. **It is a pure move: no behaviour change.** Manifests, chapter texts, reports, warnings, review reasons, audio, sidecars, cache entries, ledger rows, CLI output and exit codes stay byte-identical.

- **M1** `pdf.py`: move OCR (strategy, engine version, Tesseract calls, OCR cache, fallback, `tesseract_languages`, `missing_ocr_languages`) to `pdf_ocr.py`, and page classification (page visuals, tables, footnotes, special material, block kinds, `page_review_warnings`) to `pdf_layout.py`. `pdf.py` keeps extraction, `_open`, `_lines` and `inspect_pdf`.
- **M2** `audio/__init__.py`: move synthesis to `audio/synthesis.py`, WAV I/O to `audio/wav.py`, and speakability, voice markers and sentence chunking to `audio/speech_text.py`. `__init__` keeps the output paths and cover image, and becomes the facade CLAUDE.md describes.
- **M3** `pipeline.py`: move the analysis orchestration (`_AnalysisRun` through `_analyze_book_locked`) to `analysis.py`, reached through an `AnalysisServices` record built in `pipeline.py`, as `conversion.py` does with `ConversionServices`. `analyze_book` stays in `pipeline.py`.

M4–M8 are cross-cutting (§3).

**Out of scope:** changing what any function computes; fixing bugs found along the way (record them, §4); splitting `cli.py` or `document/structure.py`; renaming public names.

## 2. Ground rules

Everything in parent spec §12 and CLAUDE.md applies. In addition:

- **No behaviour change.** No fingerprint, schema, cache-identity or sidecar constant changes. Moved function bodies are unchanged except for the imports they need.
- **Public names stay.** Every public name imported from `pdf`, `audio` or `pipeline` today is still importable from there (re-export).
- **Moved private names are not re-exported.** A test that patches a moved private name on its old module (for example `monkeypatch.setattr("pdf2audiobook.pdf._ocr_page_lines", ...)`) must then fail with `AttributeError` instead of silently patching a name nothing uses. Those tests are retargeted to the new module.
- **Test edits are mechanical only.** An existing test may change only a monkeypatch target or an import path, to follow a moved name. Inputs and assertions stay unchanged.
- **Patched names keep taking effect.** Code moved to `analysis.py` reaches every name that tests patch on `pipeline` through `AnalysisServices`, never by a direct import.
- **No import cycles.** `pdf_ocr`, `pdf_layout` and the new `audio` submodules never import their parent module.
- **One move per commit:** `refactor(<scope>): move <job> into <module>`. Each commit passes `/verify` and mypy on 3.11, 3.12 and 3.13.

## 3. Cross-cutting requirements

- **M4 Moved code is verbatim.** For every moved function and class, a script compares its `ast.dump` at the baseline with the new module and reports zero differences other than the module it lives in. Record the counts.
- **M5 Patch-target guard.** Add `tests/test_patch_targets.py`. It scans the tests for names patched on `pipeline`, and fails if `analysis.py` or `conversion.py` references any of them directly instead of through its services record.
- **M6 Golden snapshot and suite.** `tests/test_golden_analysis_snapshot.py` and the full suite pass unchanged, apart from the mechanical edits allowed in §2.
- **M7 Typing and guards.** Add each new module to `[tool.mypy].files`. Move `tests/test_function_length.py` allowlist keys with their functions, keeping each ceiling.
- **M8 Documentation.** Update `docs/MAINTAINER_GUIDE.md` (module map and extension points) and the facade sentence in `CLAUDE.md`.

## 4. Bugs found during the work

Record them in the TODO's "Found during split" list with `file:line` and a concrete scenario; fix them separately.

## 5. Acceptance criteria

- No module touched here keeps more than one of the jobs listed in §1.
- M4 reports zero body differences; M5 passes; the golden snapshot is unchanged.
- `/verify` and exact-head CI pass for every move commit.
