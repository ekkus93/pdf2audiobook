from pdf2audiobook.llm import propose_llm_cleanup
from pdf2audiobook.models import DocumentBlock


class FakeProvider:
    def complete_json(self, *, instructions, document_text):
        return {
            "edits": [
                {
                    "block_id": "good",
                    "original": "The b00k was very good.",
                    "replacement": "The book was very good.",
                    "confidence": 0.96,
                    "reason": "Misread zero as o",
                },
                {
                    "block_id": "invented",
                    "original": "Fake source",
                    "replacement": "Fake correction",
                    "confidence": 0.99,
                    "reason": "Unknown block",
                },
                {
                    "block_id": "other",
                    "original": "Not the source text",
                    "replacement": "More text",
                    "confidence": 0.95,
                    "reason": "Hallucinated original",
                },
            ],
        }


def test_cleanup_proposals_preserve_source_and_require_review():
    blocks = [
        DocumentBlock(id="good", page_index=0, text="The b00k was very good."),
        DocumentBlock(id="other", page_index=0, text="Original passage."),
    ]
    edits, warnings = propose_llm_cleanup(blocks, FakeProvider())
    assert len(edits) == 1
    assert edits[0].original == blocks[0].text
    assert edits[0].replacement == "The book was very good."
    assert edits[0].accepted is False
    assert edits[0].provider == "llm"
    assert len(warnings) == 2
    assert blocks[0].text == "The b00k was very good."


def test_cleanup_rejects_large_rewrites_and_deletions():
    class BadProvider:
        def complete_json(self, **kwargs):
            return {
                "edits": [
                    {
                        "block_id": "b",
                        "original": "One sentence about kittens.",
                        "replacement": "",
                        "confidence": 1,
                        "reason": "Deletion",
                    }
                ]
            }

    edits, warnings = propose_llm_cleanup(
        [DocumentBlock(id="b", text="One sentence about kittens.", page_index=0)],
        BadProvider(),
    )
    assert not edits
    assert len(warnings) == 1
