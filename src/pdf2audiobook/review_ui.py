"""Loopback-only browser editor for reviewed chapter titles and boundaries."""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pdf2audiobook.document.structure import chapter_coverage_report, render_chapter_texts
from pdf2audiobook.errors import ExtractionError
from pdf2audiobook.models import BookManifest
from pdf2audiobook.workspace import read_manifest, write_manifest

_MAX_REQUEST_BYTES = 1024 * 1024
_MAX_PREVIEW_CHARS = 1200

_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>pdf2audiobook chapter review</title>
<style>
body{font:16px system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#222}
article{border:1px solid #bbb;border-radius:8px;padding:1rem;margin:1rem 0}
label{display:inline-grid;gap:.25rem;margin:.3rem 1rem .3rem 0}input{font:inherit;padding:.35rem}
pre{white-space:pre-wrap;background:#f4f4f4;padding:.75rem;max-height:16rem;overflow:auto}
button{font:inherit;padding:.6rem 1rem}#status{margin-left:1rem}
</style>
<h1>Chapter review</h1><p>Adjust titles and zero-based, end-exclusive block boundaries. Saving
validates complete, non-overlapping coverage and marks the chapters manually approved.</p>
<main id="chapters">Loading manifest…</main><button id="save">Save reviewed boundaries</button>
<span id="status" role="status"></span>
<script>
const token=__TOKEN__;
const statusNode=document.querySelector('#status');
function addField(parent,label,name,value,type='text'){
 const wrap=document.createElement('label'); wrap.append(document.createTextNode(label));
 const input=document.createElement('input'); input.name=name; input.value=value; input.type=type;
 wrap.append(input); parent.append(wrap);
}
async function load(){
 const response=await fetch('/api/manifest',{headers:{Authorization:`Bearer ${token}`}});
 if(!response.ok) throw new Error('Could not load review data');
 const data=await response.json(); const root=document.querySelector('#chapters'); root.textContent='';
 const heading=document.createElement('h2'); heading.textContent=data.title; root.append(heading);
 for(const chapter of data.chapters){
  const card=document.createElement('article'); card.dataset.id=chapter.id;
  const title=document.createElement('h3'); title.textContent=`Chapter ${chapter.number}`; card.append(title);
  addField(card,'Title','title',chapter.title);
  addField(card,'Start block (inclusive)','start',chapter.start_block,'number');
  addField(card,'End block (exclusive)','end',chapter.end_block,'number');
  addField(card,'Speaker voice ID (optional)','voice_id',chapter.voice_id||'');
  const preview=document.createElement('pre'); preview.textContent=chapter.preview; card.append(preview);
  root.append(card);
 }
}
document.querySelector('#save').addEventListener('click',async()=>{
 try{
  const chapters=[...document.querySelectorAll('article')].map(card=>({
   id:card.dataset.id,title:card.querySelector('[name=title]').value,
   start_block:Number(card.querySelector('[name=start]').value),
   end_block:Number(card.querySelector('[name=end]').value),
   voice_id:card.querySelector('[name=voice_id]').value
  }));
  const response=await fetch('/api/chapters',{method:'POST',
   headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
   body:JSON.stringify({chapters})});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error||'Save failed');
  statusNode.textContent='Saved and approved. Derived chapter text was refreshed.';
 }catch(error){statusNode.textContent=error.message;}
});
load().catch(error=>{document.querySelector('#chapters').textContent=error.message;});
</script></html>"""


def _review_payload(manifest: BookManifest) -> dict[str, Any]:
    chapters = []
    for chapter in manifest.chapters:
        blocks = manifest.blocks[chapter.start_block : chapter.end_block]
        preview = "\n\n".join(block.text for block in blocks)[:_MAX_PREVIEW_CHARS]
        chapters.append(
            {
                "id": chapter.id,
                "number": chapter.number,
                "title": chapter.title,
                "start_block": chapter.start_block,
                "end_block": chapter.end_block,
                "voice_id": chapter.voice_id,
                "preview": preview,
            }
        )
    return {"title": manifest.title, "chapters": chapters}


def save_chapter_updates(manifest_path: Path, updates: Any) -> None:
    """Validate and atomically persist title/boundary edits from the local UI."""
    manifest = read_manifest(manifest_path)
    if not isinstance(updates, list) or len(updates) != len(manifest.chapters):
        raise ExtractionError("Review update must include every existing chapter")
    for chapter, update in zip(manifest.chapters, updates, strict=True):
        if not isinstance(update, dict) or update.get("id") != chapter.id:
            raise ExtractionError("Review update chapter identity is invalid")
        title = update.get("title")
        start = update.get("start_block")
        end = update.get("end_block")
        has_voice_id = "voice_id" in update
        voice_id = update.get("voice_id")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 256
            or isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end > len(manifest.blocks)
            or end <= start
            or (
                has_voice_id
                and voice_id is not None
                and (not isinstance(voice_id, str) or len(voice_id) > 128)
            )
        ):
            raise ExtractionError("Review update has an invalid title or block range")
        chapter.title = title.strip()
        chapter.start_block = start
        chapter.end_block = end
        chapter.manually_approved = True
        if has_voice_id:
            chapter.voice_id = (
                voice_id.strip() if isinstance(voice_id, str) and voice_id.strip() else None
            )
    chapter_coverage_report(manifest)
    write_manifest(manifest_path, manifest)
    render_chapter_texts(manifest, manifest_path.parent)


def create_review_server(
    manifest_path: Path, *, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """Build a loopback-only server; caller owns serve_forever and shutdown."""
    if host.casefold() == "localhost":
        host = "localhost"
    else:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise ValueError(
                "Review UI can only bind to a loopback IP address or localhost"
            ) from None
    resolved_manifest = manifest_path.resolve()
    token = secrets.token_urlsafe(32)
    expected_authority: str | None = None
    expected_origin: str | None = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            try:
                supplied_bytes = supplied.encode("latin-1", "strict")
            except (AttributeError, UnicodeEncodeError):
                return False
            return hmac.compare_digest(supplied_bytes, f"Bearer {token}".encode("ascii"))

        def _valid_host(self) -> bool:
            host_values = self.headers.get_all("Host", [])
            return len(host_values) == 1 and host_values[0] == expected_authority

        def _respond(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict[str, Any]) -> None:
            self._respond(
                status,
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if not self._valid_host():
                self._respond(421, b"Invalid request authority", "text/plain; charset=utf-8")
                return
            origin = self.headers.get("Origin")
            if route.startswith("/api/") and origin is not None and origin != expected_origin:
                self._json(403, {"error": "Forbidden"})
                return
            if route == "/":
                html = _HTML.replace("__TOKEN__", json.dumps(token)).encode("utf-8")
                self._respond(200, html, "text/html; charset=utf-8")
            elif route == "/api/manifest" and self._authorized():
                try:
                    self._json(200, _review_payload(read_manifest(resolved_manifest)))
                except Exception:
                    self._json(400, {"error": "Could not read the chapter manifest"})
            elif route.startswith("/api/") and not self._authorized():
                self._json(401, {"error": "Unauthorized"})
            else:
                self._json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            if not self._valid_host():
                self._respond(421, b"Invalid request authority", "text/plain; charset=utf-8")
                return
            if not self._authorized() or self.headers.get("Origin") != expected_origin:
                self._json(403, {"error": "Forbidden"})
                return
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > _MAX_REQUEST_BYTES:
                self._json(413, {"error": "Review update exceeds the request size limit"})
                return
            try:
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError
                save_chapter_updates(resolved_manifest, payload.get("chapters"))
            except Exception:
                self._json(400, {"error": "Review update was invalid; no changes were saved"})
                return
            self._json(200, {"ok": True})

    server = ThreadingHTTPServer((host, port), Handler)
    authority = f"[{host}]" if ":" in host else host
    expected_authority = f"{authority}:{server.server_address[1]}"
    expected_origin = f"http://{expected_authority}"
    server.review_token = token  # type: ignore[attr-defined]
    return server
