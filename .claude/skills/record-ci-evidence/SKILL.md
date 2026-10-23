---
name: record-ci-evidence
description: After pushing a fix to master, look up the GitHub Actions "Python CI" run for that exact SHA and append a Progress ledger row to docs/PDF2AUDIOBOOK_TODO.md in a separate docs commit. Use after every pushed fix commit.
---

Target SHA: `$ARGUMENTS` if given, otherwise the latest non-`docs:` commit on `master`. Resolve it to the full 40-character SHA with `git rev-parse`.

1. Find every CI run for that exact head:
   `gh run list --workflow "Python CI" --commit <sha> --json databaseId,number,status,conclusion,attempt,url`
   If the run is still in progress, wait for it with `gh run watch <id> --exit-status`. Never record a run that has not finished.
2. If it failed, read `gh run view <id> --log-failed`, tell the user, and stop. Fix the failure first. Failed attempts are still noted in the eventual ledger row.
3. Read the end of `docs/PDF2AUDIOBOOK_TODO.md`, the `| Date | Master SHA | Completed tasks | Tests/CI | Blockers |` table. If a row for this SHA already exists, update it rather than adding a duplicate.
4. Append one row that matches the style of the recent rows:
   - Date: today, as YYYY-MM-DD.
   - Master SHA: the full SHA.
   - Completed tasks: the TODO task ID(s), marked "partial" unless every subtask is verified, plus a plain description of what changed and what the regression tests prove.
   - Tests/CI: for example "Exact-head Python CI #<number> (run <databaseId>) passed Python 3.11/3.12/3.13 with locked dependencies, Ruff, scoped format, mypy, pytest, CLI and packaging smoke". Include any earlier failed attempts and their run IDs.
   - Blockers: the scope still unqualified. Real Kitten, LLM and Tesseract acceptance stay listed until they are actually run.
5. Flip a TODO checkbox to `[x]` only if the implementation and its verified evidence fully cover that item.
6. Commit only that file as `docs: record <short summary> CI evidence` (lowercase, no body) and push to `master`.

Every number in the row must come from `gh` output. Never invent or estimate CI results.
