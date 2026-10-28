# PDF2Audiobook Citation and Equation Reading Specification

**Status:** Proposed
**Date:** 2026-10-27
**Companion:** `docs/PDF2AUDIOBOOK_CITATIONS_EQUATIONS_TODO.md`
**Baseline:** master at b0b4d7c (`docs: record epub chapters follow-up completion and CI evidence`)
**Supplements:** `docs/PDF2AUDIOBOOK_SPEC.md` (§4.3 text restoration and special material, §6 LLM layer, §7 configuration, §9 audio)

## 1. Purpose and scope

Technical books and papers are full of material that sounds wrong when read literally. Converting *Attention Is All You Need* (15 pages) showed two problems:
- Numeric citations (`[13]`, `[35, 2, 5]`) occur every few sentences and are read aloud as numbers.
- Equations are read as whatever the voice makes of symbols such as `√dk`.

The narration stage of the LLM layer already runs, but it is advisory only. For this paper it produced 28 pronunciation hints for author names, saved to `reports/narration_suggestions.json` and never applied to audio. The classification stage has no equation category, and the extractor marked only two stray fragments (`√dk`, `lrate = d−0.5`) as equations.

This spec adds **two independent, opt-in settings**:
- **Citation processing** skips numeric citations in the audio. It is deterministic and needs no LLM.
- **Equation processing** has the LLM propose a spoken reading for blocks of mathematical notation. Proposals stay **pending until the user accepts them**; nothing the model writes reaches the audio unreviewed.

Both default to off, so existing behavior, caches and fingerprints are unchanged for anyone who does not enable them.

The project invariants still hold: the source transcript is never altered or silently dropped, PDF text and LLM output are untrusted, LLM edits are proposals until a human accepts them, errors and logs are content-free, and CI stays offline.

## 2. Requirements

### C1: Two separate settings

Add a `[reading]` table (not `[narration]`, which would collide with the existing `llm.narration` stage toggle) with two booleans:

```toml
[reading]
process_citations = false
process_equations = false
```

- Environment: `PDF2AUDIOBOOK_PROCESS_CITATIONS` and `PDF2AUDIOBOOK_PROCESS_EQUATIONS`.
- CLI, on `analyze` and `convert`: `--process-citations/--no-process-citations` and `--process-equations/--no-process-equations`. The pairs default to unset, so config and environment values stay effective unless a flag is given (the project's boolean-pair convention). The precedence is CLI > environment > TOML > default.
- Each setting affects only its own feature. Turning one on never turns the other on.
- `process_equations = true` with the LLM disabled (`--no-llm` or `llm.enabled = false`) is a configuration error with exit code 2 and a content-free message: "Equation processing needs the LLM; enable it or turn equation processing off". `process_citations` has no such requirement.
- `config show` (text and `--json`) and `doctor --json` report both values.

**Acceptance:**
- Defaults are false.
- Each flag form, the environment variable and the TOML key reach `Settings`, with CLI over environment over TOML.
- The two settings are independent.
- The LLM-required error is exit 2 and content-free.
- `config show --json` includes `reading`.
- The environment-variable coverage test is extended for both variables.

### C2: Citation processing (skip)

When `process_citations` is on, numeric citations are **not spoken**. The chapter text file (`chapters/NNN.txt`) is unchanged, so the user's editable narration artifact and the source transcript still contain every citation; only the audio omits them.

**What is a citation.** A bracketed group that contains only integers, ranges and separators, for example `[13]`, `[35, 2, 5]`, `[1-3]`, `[1–3]`, `[4; 7]`:
- each number has at most three digits;
- a range has an ascending pair;
- separators are commas, semicolons and spaces;
- the group is preceded by whitespace, an opening bracket or quote, or the start of a line.

A group attached directly to a word (`a[1]`, `x[i]`) is not a citation, nor is `[` containing letters. Author–year forms such as `(Vaswani et al., 2017)` are out of scope for this version and are read as written.

**How it is skipped.** The spoken layer already works on word tokens aligned to source character ranges (`split_sentences`, `_spoken_sequence`, `chunk_source_ranges`, `_droppable_word`). Citation groups are removed from the spoken sequence, so chunking, voice markers, pauses and the chunk-to-source mapping stay correct. The skipped range remains in the source mapping.
- Trailing punctuation stays: "translation [38]." is spoken "translation."
- A paragraph consisting only of citations contributes nothing to the audio (it is blank once masked). A paragraph of citations and punctuation, such as `[13].`, is a pause-only paragraph like any other punctuation-only one.
- A citation split across a line break is still one group.

**Identity.** When the setting is on, add `"citations": true` to the chapter audio fingerprint and to the sidecar's `rendering_inputs`. When it is off, the fingerprint and sidecar are **byte-identical to today's**, so existing audio stays valid. A cached chapter is reused only when its recorded rendering inputs match the current setting. `pack-m4b` does not treat a differing citation setting as stale audio, because the audio is whatever was converted.

**Acceptance:**
- Examples above are skipped or kept as specified, including `a[1]` and `x[i]`, and `[13]` mid-sentence, at a sentence end and at the start of a paragraph.
- With the setting off, chunk text and fingerprints are unchanged (a golden comparison).
- Chunk-to-source alignment still succeeds on text containing citations.
- A fake-provider conversion never sends a citation to the provider when on, and does send it when off.
- Toggling the setting regenerates only audio.

### C3: Equation processing (LLM proposals, pending)

When `process_equations` is on and the LLM is enabled, analysis runs an **equation reading** task after the other LLM stages.

**Candidates** are chosen without the LLM: blocks with `kind == "equation"`, or blocks containing mathematical notation by a deterministic test. The test matches any of the symbols `= + − × ÷ √ ∑ ∏ ∫ ≤ ≥ ≠ ≈ ∈ ∞ ± ∂ ∇ ^`, a Greek letter, or a function-call form being defined, such as `f(x) =` or `Attention(Q, K, V) =`. A bare `layer(s)` or `f(x)` in prose is not enough, and a line containing `://` is never a candidate. The candidate count is capped (default 500 per book, content-free warning when exceeded), and the LLM budget limits still apply.

**Task.** The model is asked to rewrite only the mathematical notation of a candidate block as words a person would say aloud, to keep every other word exactly, and not to solve, simplify or explain. The prompt carries the usual untrusted-content framing. Block text is sent in bounded windows like the other stages, and the usual remote-content consent rules apply.

**Verification** (a proposal that fails is discarded and recorded in the decision audit; it never becomes an edit):
1. The proposal is non-empty and differs from the source.
2. It contains no markup, backticks or code fences, and is at most six times the source length plus 40 characters (so a three-character `√dk` may expand to a short phrase).
3. **The stream of digits is identical** in source and proposal, in order, where a digit may be written as a numeral or as a number word (`eight`, `twenty-one`, `squared`, `cubed`; superscript digits count). This is stronger than comparing numbers one by one, and it does not wrongly reject faithful readings of text whose superscripts the extractor merged (`10000^2i` arrives as `100002i`).
4. Every alphabetic word of four or more letters in the source appears in the proposal in the same order, compared without spaces so `dmodel` may be read "d model" (prose and names such as `softmax` survive).
5. The model's confidence is at least 0.80, and it quotes the block text exactly.

**Result.** An accepted-by-verification proposal is stored in `manifest.edits` as a `CleanupEdit` with `provider = "llm"`, `accepted = false`, the original text, and a reason such as "spoken reading of mathematical notation". It does **not** change chapter text until accepted (C4). With nothing accepted, audio is identical to today's.

**Acceptance:**
- A fake provider's proposals that pass produce pending edits; the manifest, chapter files and audio are unchanged until accepted.
- Each verification rule has a rejecting case (a changed or invented digit, a dropped or reordered prose word, an empty, unchanged or oversized proposal, markup, low confidence, a misquoted source line).
- The candidate test matches the listed forms and rejects ordinary prose, including numbered list items and years.
- Over the cap, the cap applies with a warning.
- Disabling the setting skips the task entirely and makes no model calls.
- An LLM failure behaves as for the other stages (the existing fallback setting).

### C4: Accepting and rejecting pending edits

Today nothing in the CLI or review UI can set an LLM edit's `accepted` flag, so any LLM edit (cleanup, equation) is permanently a proposal. Add:

```
pdf2audiobook edits list   MANIFEST [--status pending|accepted|all] [--json]
pdf2audiobook edits accept MANIFEST (--all | BLOCK_ID ...)
pdf2audiobook edits reject MANIFEST (--all | BLOCK_ID ...)
```

- `list` shows block ID, chapter number, provider, reason, status and the original and proposed text. Text appears in human output only; `--json` carries IDs, chapter numbers, status and reason codes, never book text.
- `accept` sets `accepted = true` and regenerates the affected chapters' text through the existing artifact planner and transaction machinery, under the workspace lock: chapter text, coverage, metadata and manifest are published together or recovered.
- An accepted edit whose chapter file was hand-edited produces the existing content-free chapter conflict, naming the chapter and `regenerate-chapter`, and nothing is changed.
- `reject` removes a pending proposal from `edits`; an accepted edit cannot be rejected. Decisions are recorded in `reports/edit_decisions.json` (block ID, action, provider; no book text). *Amendment:* a rejected proposal can reappear if the workspace is re-analyzed, because the model's cached answer is unchanged; remembering rejections would need a manifest schema change and is out of scope.
- Both commands refuse an unknown block ID (exit 2). Accepting twice is harmless.
- Changed chapter text invalidates that chapter's audio automatically (the text hash changes) and nothing else.

**Acceptance:**
- Accepting an edit changes exactly that block's narrated text and the chapter's audio becomes stale; rejecting removes it.
- A hand-edited chapter file is a conflict, with all files unchanged.
- An interrupted accept recovers with `recover`.
- Lock contention returns the lock error.
- `--json` output is parseable and content-free.
- The same commands accept a pending cleanup edit.

### C5: Identity, upgrade and documentation

- When `process_equations` is on, include it in the `llm-analysis` stage fingerprint **only when true** (so off-state fingerprints are unchanged), and bump nothing else. Existing workspaces without approvals are re-analyzed on the next run with the setting on, reusing cached LLM answers for earlier stages. A workspace with an approved chapter keeps refusing reanalysis with the existing message; the equation setting should be chosen before the first analysis, and this is documented.
- Update `docs/MAINTAINER_GUIDE.md` (settings, the spoken-layer citation hook, the edit workflow) and the README (the two settings, the `edits` commands, and the limitations below). Update §4.3, §6 and §7 of `docs/PDF2AUDIOBOOK_SPEC.md`.

## 3. Known limitations (documented, not solved here)

- Author–year citations and superscript or footnote-style numbers are not handled.
- Math in running prose that uses none of the listed symbols is not a candidate. Display equations that the PDF extractor splits across lines are judged block by block, so a fragment may be proposed on its own.
- Equation proposals have no review UI in this version; `pdf2audiobook edits` is the interface.
- Verification rules 1–4 catch dropped numbers and prose, not a plausible but wrong reading of an operator. That is why proposals are never applied without acceptance.
- The setting applies at analysis time. Enabling it for a workspace that already has approved chapters needs a new output directory.

## 4. Validation

- Add focused deterministic tests for each requirement, using synthetic PDFs and fake LLM providers. Run `/verify`, plus mypy on Python 3.12 and 3.13.
- Local acceptance, never committed: re-run the *Attention Is All You Need* paper with citation processing on and equation processing on, with the LLM. Record only counts: citations skipped, equation candidates, proposals that passed verification, and accepted edits. Listen to a sample of the audio.
