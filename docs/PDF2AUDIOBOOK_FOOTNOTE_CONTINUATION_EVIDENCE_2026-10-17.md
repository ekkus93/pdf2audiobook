# Footnote continuation — qualification evidence

Date: 2026-10-17 UTC. Scope: partial P1.05 only.

## Implementation

- src/pdf2audiobook/pdf.py now propagates footnote classification only from a previously confirmed, small-type, separated numbered anchor into immediately adjacent, similarly small lines in the same column.
- Stops at a numbered independent candidate, table, body-sized text, large vertical gap, different column or unexpected reading-order geometry.
- Every line remains independently represented as an unmodified DocumentBlock and SourceSpan; no new transcription, reordering, omission or relocation is claimed.
- Warning text retains the established anchor wording for compatibility and explicitly describes continuation lines.

## Regression and CI evidence

- tests/test_footnote_continuation.py covers wrapped lines, unanchored/distant/other-column candidates, table intersection and a synthetic PDF with exact source-span preservation.
- Original commit a19d2e13ee187cdbf4a0dfdbafaa8fc1b47d42b6 failed CI #190 solely because an existing test matched the prior warning wording; the expected wording was restored.
- Corrected implementation commit 8bad3b0681e4240cf2b5649547a36dfbba5f2602: Python CI #191, run 39045278597, **passed**. No real-book inference is claimed.

## Remaining P1.05 work

Footnote anchors inside body text remain unrelocated. Extended, multi-column and cross-page notes may still require user review. Table cell order, equations' spoken rendering and real-document acceptance remain unqualified. This does **not** complete P1.05 or M1.
