# Editing and review

[Home](../../README.md) · [All guides](README.md)

For the browser review workflow, see [the illustrated
walkthrough](getting-started.md#step-4-review-the-chapters-in-your-browser). Keep a backup of your
workspace before editing its manifest or chapter text.

- [Editing chapter text](#editing-chapter-text)
- [Protecting manual edits](#protecting-manual-edits)
- [Citations and equations](#citations-and-equations)

## Editing chapter text

Chapter files are editable. After changing one, keep a backup: resume and conversion preserve
compatible edits, and changed narration makes existing audio stale. If a boundary, source text,
cleanup decision or footnote policy changes for an edited chapter, the operation stops and names
the chapter number. Resolve it with:

```bash
pdf2audiobook regenerate-chapter ./audiobooks/BOOK/manifest.json --chapter 3
pdf2audiobook regenerate-chapter ./audiobooks/BOOK/manifest.json --all-conflicts
```

This copies a differing chapter file to `chapter-backups/NNN-<UTC time>.txt` (a backup is never
overwritten or deleted by the tool), then writes the generated text and records it as unedited.
It does not change approvals, review reasons or the manifest. Reapply your edits afterwards from
the backup. If you deleted an edited chapter file that the application had already observed, the
same command restores it. Do not delete `chapter-artifacts.json`; that is unsupported. A legacy
workspace with no generation record adopts a chapter file only when it matches current generated
text, and `regenerate-chapter` resolves a differing legacy file the same way.

A workspace created before footnote policies were recorded has no stored policy. Review,
packaging and `regenerate-chapter` infer it from the manifest's footnote edits and the unedited
chapter files, and record it only when exactly one policy fits; nothing is guessed. Otherwise
they stop and ask you to run `analyze` with the original `pdf.footnotes` setting, or to pass
`--footnotes warn|inline|end|omit` to `regenerate-chapter`.

### Recovering an interrupted update

Review and chapter regeneration record a workspace transaction before publishing files. If an
update reports that recovery is needed, or a later command says a previous update needs recovery,
run:

```bash
pdf2audiobook recover ./audiobooks/BOOK/manifest.json
```

It completes the interrupted update, or reports which targets (`chapter 3`, `manifest`,
`coverage report`, `chapter metadata`) were changed after the interruption. Add
`--back-up-changed` to copy those files to `chapter-backups/` or `workspace-backups/` first and
then finish the update. An invalid transaction file is never repaired automatically; restore the
workspace from a backup. Reading a manifest (for example the review page or `inspect`) never
runs recovery and refuses while an update is pending. The transaction file can contain book
text and should be protected like the workspace. The stored footnote policy is reused by review
and packaging. A deleted edit can be detected only after the application has observed it; keep
backups even when an edit has not yet been processed.

### The review page

The review server binds only to loopback, requires a per-run token for manifest data, and marks
saved chapter boundaries as manually approved. It also accepts an optional TTS voice ID per chapter;
paragraph-level voice markers in the approved chapter text can override it for dialogue.

## Protecting manual edits

After reviewing a `manifest.json`, mark a chapter's `manually_approved` field or the book's
`approved` field to preserve the approved boundaries. The app will regenerate missing derived
chapter text from that manifest on resume, but will **reject a destructive reanalysis** when
approved content would otherwise be overwritten (including when using `--no-resume` or changing
analysis settings). A footnote policy change can reuse approved analysis when its policy-specific
cleanup decisions are unchanged and affected chapter files have no edits. To start a new analysis,
back up the approved manifest and choose a fresh output directory.

## Citations and equations

Technical books read badly aloud when citations and equations are spoken literally. Two
independent settings, both **on by default**, change that:

~~~toml
[reading]
process_citations = true   # (default) skip [13], [35, 2, 5], [1-3] in the audio
process_equations = true   # (default) LLM proposes spoken readings; you approve them
~~~

Each also has a flag pair on `analyze` and `convert` (`--process-citations/--no-process-citations`,
`--process-equations/--no-process-equations`) and an environment variable
(`PDF2AUDIOBOOK_PROCESS_CITATIONS`, `PDF2AUDIOBOOK_PROCESS_EQUATIONS`).

**Citations** are skipped in the spoken text only. The chapter file still contains them, so your
edits and the source transcript are unchanged. A citation is a bracketed list of numbers or an
ascending range after a space or an opening bracket or quote; `a[1]`, `x[i]`, `[see 13]` and
author-year forms such as `(Vaswani et al., 2017)` are left alone, and so is a list right after a
relation symbol (`x ∈ [1, 5]`, `p = [2, 3]`), which is an interval. "As shown in [1, 5]" is still
read as a citation. Numbers that start bibliography entries (`[1] Jimmy Ba. …`) are brackets like
any other, so they are not spoken either. A chapter you have edited down to nothing but citations
has nothing to say: that chapter fails with the usual "Chapter audio failed" error and the others
still convert. Changing the setting regenerates only audio.

**Equations** need the LLM. It proposes a spoken form for each line of mathematics (found by
symbols such as `= + − √ ∑ ≤ ∈` and Greek letters, at most 500 per book). Every proposal is checked
against the source: the digits must be identical, words of four letters or more must survive in
order, and markup or runaway length is refused. Survivors are **pending** and never reach the
audio until you accept them:

~~~bash
pdf2audiobook edits list ./audiobooks/BOOK/manifest.json
pdf2audiobook edits accept ./audiobooks/BOOK/manifest.json p00003-l00012
pdf2audiobook edits accept ./audiobooks/BOOK/manifest.json --all
pdf2audiobook edits reject ./audiobooks/BOOK/manifest.json p00003-l00020
~~~

Accepting regenerates that chapter's text (a chapter file you edited by hand is a conflict;
see `regenerate-chapter`) and makes only its audio stale. The checks cannot judge whether an
operator was read correctly, which is why nothing is applied unreviewed. Accepting an LLM edit
counts as approving the workspace's content, so that book then refuses re-analysis without a new
`--output`, just as a manually approved chapter does. A block takes one accepted edit: accepting
a second one on the same block is refused rather than replacing the first. `edits list --status
rejected` shows cleanups you rejected during review; `edits` leaves those alone. `edits` also
resolves pending cleanup suggestions. Turn either off with `--no-process-citations` or
`--no-process-equations` (or `false` in `[reading]`). With the LLM off (`--no-llm`) equation
processing is simply inactive; asking for it explicitly alongside `--no-llm` is an error.

Because citation skipping is on by default, audio made before this setting existed is regenerated
on its next `convert` (chapter text and analysis are not). The equation setting is not part of the
analysis identity, so changing it does not re-analyze an existing workspace; to get equation
proposals for a book analyzed without them, re-run analysis with `--no-resume` on a workspace with
no approved chapters, or use a new `--output`.
