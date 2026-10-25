"""Loopback chapter review UI validates edits before writing manifests."""

import json
import threading
import urllib.error
import urllib.request

import pymupdf
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.review_ui import create_review_server
from pdf2audiobook.workspace import read_manifest


def _manifest(tmp_path):
    source = tmp_path / "review.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((80, 80), "Chapter One")
    page.insert_text((80, 130), "First chapter prose.")
    page.insert_text((80, 180), "Chapter Two")
    page.insert_text((80, 230), "Second chapter prose.")
    document.save(source)
    document.close()
    settings = Settings.model_validate(
        {
            "general": {"output_dir": str(tmp_path / "out")},
            "llm": {"enabled": False},
        }
    )
    return analyze_book(source, settings)


def test_review_server_authenticates_api_and_saves_validated_boundaries(tmp_path):
    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(url + "/", timeout=3) as response:
            assert response.status == 200
            assert "Chapter review" in response.read().decode()
        try:
            urllib.request.urlopen(url + "/api/manifest", timeout=3)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("manifest API must require a bearer token")

        headers = {"Authorization": f"Bearer {server.review_token}"}
        request = urllib.request.Request(url + "/api/manifest", headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
        chapters = payload["chapters"]
        assert len(chapters) == 2
        chapters[0]["title"] = "Reviewed First Chapter"
        chapters[0]["voice_id"] = "Jasper"
        chapters[1]["voice_id"] = "Bella"
        chapters[0]["end_block"] += 1
        chapters[1]["start_block"] += 1
        body = json.dumps({"chapters": chapters}).encode()
        save_request = urllib.request.Request(
            url + "/api/chapters",
            data=body,
            method="POST",
            headers={
                **headers,
                "Origin": url,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(save_request, timeout=3) as response:
            assert json.loads(response.read()) == {"ok": True}

        saved = read_manifest(manifest_path)
        assert saved.chapters[0].title == "Reviewed First Chapter"
        assert [chapter.voice_id for chapter in saved.chapters] == ["Jasper", "Bella"]
        assert all(chapter.manually_approved for chapter in saved.chapters)
        assert "Chapter Two" in (manifest_path.parent / "chapters" / "001.txt").read_text()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_review_server_rejects_invalid_ranges_and_non_loopback_bind(tmp_path):
    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(
            url + "/api/chapters",
            data=b'{"chapters":[]}',
            method="POST",
            headers={
                "Authorization": f"Bearer {server.review_token}",
                "Origin": url,
                "Content-Type": "application/json",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    with pytest.raises(ValueError, match="loopback"):
        create_review_server(manifest_path, host="0.0.0.0", port=0)
