# PDF extraction: displayed-equation classification evidence

Date: 2026-10-17 (UTC). Scope: partial P1.05, not milestone completion.

## Verified implementation

- \`src/pdf2audiobook/special_material.py\` classifies short, standalone
  mathematical expressions using conservative lexical checks. Inline prose,
  list markers, and figure/table captions are not treated as formulas.
- \`src/pdf2audiobook/pdf.py\` emits source-linked \`equation\` blocks and
  review warnings. \`DocumentBlock\` accepts the new kind without changing
  the manifest schema version.
- Chapter-heading discovery, pagination cleanup and narration reflow do not
  mistake an equation for a heading, folio, or soft-wrapped body sentence.
  The exact source text remains in the manifest and chapter transcript.
- Offline regression tests in \`tests/test_display_equations.py\` cover
  classification, false-positive guards, span preservation and separate
  narration lines.

## Qualification

Commit: \`0f1d562669f044250bf3177ea81d2f03152f861e\`
Python CI #188: PASSED at that exact head.
The previous CI #187 failed lint import ordering; the issue was fixed and
CI #188 passed.

## Remaining work

P1.05 remains unchecked. Complete table cell order and math narration
policies, robust footnote continuation/anchor placement, difficult OCR and
real-document review. The classifier is a conservative review heuristic,
not mathematical OCR, semantic interpretation or guaranteed speech quality.
