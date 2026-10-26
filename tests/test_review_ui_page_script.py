"""The page's own JavaScript builds the save request (R10, R73); run it, not a Python copy."""

import json
import shutil
import subprocess

import pytest

from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.review_ui import _HTML, _review_payload

REASON_LABELS = {
    "damaged_source": "I reviewed the damaged source and checked its page coverage.",
    "ambiguous_page_numbers": "I reviewed the ambiguous page-number cleanup.",
}

NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const [scriptPath, payloadPath, ackChecked, editedVoice] = process.argv.slice(2);
const payload = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.value = '';
    this.name = ''; this.type = ''; this.textContent = ''; this.hidden = false;
    this.checked = false; this.listeners = {}; }
  append(...nodes) { for (const n of nodes) if (n instanceof El) this.children.push(n); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  find(match) { for (const c of this.children) { if (match(c)) return c; const d = c.find(match); if (d) return d; } return null; }
  findAll(match) { return this.children.flatMap(c => [ ...(match(c) ? [c] : []), ...c.findAll(match) ]); }
  querySelector(sel) { const m = /^\[name=(\w+)\]$/.exec(sel); return m ? this.find(c => c.name === m[1]) : null; }
}
const ids = {};
for (const id of ['#status', '#chapters', '#save', '#review-acknowledgements', '#damaged', '#ack-damaged']) ids[id] = new El('x');
ids['#ack-damaged'].checked = ackChecked === 'true';
global.document = {
  createElement: tag => new El(tag),
  createTextNode: () => ({}),
  querySelector: sel => ids[sel],
  querySelectorAll: sel => sel === 'article' ? ids['#chapters'].children.filter(c => c.tag === 'article') :
    sel === '[data-review-reason]:checked' ? ids['#review-acknowledgements'].findAll(c => c.dataset.reviewReason && c.checked) : [],
};
const calls = [];
global.fetch = async (url, opts = {}) => { calls.push({ url, opts });
  return url === '/api/manifest' ? { ok: true, json: async () => payload } : { ok: true, json: async () => ({ ok: true }) }; };
eval(fs.readFileSync(scriptPath, 'utf8'));
(async () => {
  await new Promise(r => setTimeout(r, 20));
  if (editedVoice) {
    const article = ids['#chapters'].children.find(c => c.tag === 'article');
    article.querySelector('[name=voice_id]').value = editedVoice;
  }
  if (ackChecked === 'true') {
    const control = ids['#review-acknowledgements'].find(c => c.dataset.reviewReason);
    if (control) control.checked = true;
  }
  await ids['#save'].listeners.click();
  await new Promise(r => setTimeout(r, 20));
  console.log(JSON.stringify({ body: JSON.parse(calls[calls.length - 1].opts.body),
    acknowledgementControls: ids['#review-acknowledgements'].findAll(c => c.dataset.reviewReason)
      .map(c => c.dataset.reviewReason), damagedHidden: ids['#damaged'].hidden }));
})();
"""


def _manifest(**kwargs):
    return BookManifest(
        schema_version=3,
        input_sha256="x",
        title="Book",
        source_path="source.pdf",
        blocks=[
            DocumentBlock(id="b1", text="One.", page_index=0),
            DocumentBlock(id="b2", text="Two.", page_index=0),
        ],
        chapters=[
            Chapter(
                id="c1",
                number=1,
                title="One",
                start_block=0,
                end_block=1,
                confidence=1,
                voice_id="Jasper",
            ),
            Chapter(id="c2", number=2, title="Two", start_block=1, end_block=2, confidence=1),
        ],
        **kwargs,
    )


def _run_page(tmp_path, manifest, *, acknowledged=False, edited_voice=None):
    script = (
        _HTML.split("<script>", 1)[1]
        .split("</script>", 1)[0]
        .replace("__TOKEN__", '"t"')
        .replace("__REASON_LABELS__", json.dumps(REASON_LABELS))
    )
    (tmp_path / "page.js").write_text(script, encoding="utf-8")
    (tmp_path / "payload.json").write_text(json.dumps(_review_payload(manifest)), encoding="utf-8")
    (tmp_path / "harness.js").write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        [
            NODE,
            str(tmp_path / "harness.js"),
            str(tmp_path / "page.js"),
            str(tmp_path / "payload.json"),
            str(acknowledged).lower(),
            edited_voice or "",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def test_page_script_names_voice_id_in_the_request_it_builds():
    assert "voice_id:card.querySelector('[name=voice_id]').value" in _HTML
    assert "acknowledge" in _HTML and "__REASON_LABELS__" in _HTML
    assert set(REASON_LABELS) == {"damaged_source", "ambiguous_page_numbers"}


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_unchanged_save_posts_the_loaded_voice_and_no_acknowledgement(tmp_path):
    posted = _run_page(tmp_path, _manifest())["body"]
    assert [row["voice_id"] for row in posted["chapters"]] == ["Jasper", ""]
    assert posted["acknowledge"] == []


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_page_script_posts_kept_and_edited_voices_to_server(tmp_path):
    manifest = _manifest()
    manifest.chapters[1].voice_id = "Jasper"
    posted = _run_page(tmp_path, manifest, edited_voice="Bella")["body"]
    assert [row["voice_id"] for row in posted["chapters"]] == ["Bella", "Jasper"]


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
@pytest.mark.parametrize("reason", ["damaged_source", "ambiguous_page_numbers"])
def test_book_wide_checkbox_is_shown_and_posted_only_when_ticked(tmp_path, reason):
    manifest = _manifest(review_required=[reason])
    unticked = _run_page(tmp_path, manifest)
    assert unticked["acknowledgementControls"] == [reason]
    assert unticked["body"]["acknowledge"] == []
    ticked = _run_page(tmp_path, manifest, acknowledged=True)
    assert ticked["body"]["acknowledge"] == [reason]
    assert _run_page(tmp_path, _manifest())["acknowledgementControls"] == []
