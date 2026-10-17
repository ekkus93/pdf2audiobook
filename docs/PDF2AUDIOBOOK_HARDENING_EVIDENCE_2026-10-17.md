# PDF2Audiobook hardening evidence — 2026-10-17

## Vector-only figure captions (P1.05 partial)

At commit `3a618fb221915158230e092b64e60cc4afb61f30`, caption
classification now recognizes an explicit Figure caption near a bounded
cluster of sizable vector paths. A single rectangle or a caption far from
the drawing is insufficient. All original source spans remain intact.
Synthetic PDF regression tests cover positive and negative cases.

Exact-head Python CI: run 39031669112, passed.

## Multiple margin numerals (P1.04c partial)

At commit `456879dd13223b92e52e68d81ce7e83f49aeaa61`,
pagination cleanup rejects numeric sequences corroborated by a page
containing more than one standalone margin numeral. The ambiguity check
counts even numeric lines excluded earlier by body-adjacency heuristics,
preventing a legitimate numbered list from inadvertently confirming
a page-number sequence.

Synthetic regression tests cover ambiguous numerals, valid sequential
folios, and an ambiguous page adjacent to an otherwise valid folio.
An initial regression failed in CI run 39031904129; the corrected
implementation passed exact-head Python CI run 39032012108.

Neither parent TODO is complete. Complex vector diagrams, math narration,
and additional pagination false positives remain review-required.
The canonical TODO was not changed because the Ralph Bridge rejected
both attempted writes to the large checklist.
