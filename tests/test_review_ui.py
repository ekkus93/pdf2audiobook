"""Loopback chapter review UI validates edits before writing manifests."""

import json
import threading
import urllib.error
import urllib.request

import pymupdf
import pytest

from pdf2audiobook.config import Settings
from pdf2audiobook.pipeline import analyze_book
from pdf2audiobook.review_ui import (
    _expected_authorities,
    create_review_server,
    save_chapter_updates,
)
from pdf2audiobook.workspace import read_manifest, write_manifest


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


def _page_save_body(chapters):
    """Mirror the page's JSON.stringify({chapters}) field builder."""
    return json.dumps(
        {
            "chapters": [
                {
                    "id": chapter["id"],
                    "title": chapter["title"],
                    "start_block": chapter["start_block"],
                    "end_block": chapter["end_block"],
                    "voice_id": chapter["voice_id"],
                }
                for chapter in chapters
            ]
        }
    ).encode()


def test_review_server_authenticates_api_and_saves_validated_boundaries(tmp_path):
    manifest_path = _manifest(tmp_path)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].voice_id = "Jasper"
    manifest.chapters[1].voice_id = "Bella"
    write_manifest(manifest_path, manifest)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(url + "/", timeout=3) as response:
            assert response.status == 200
            page = response.read().decode()
            assert "Chapter review" in page
            assert "voice_id:card.querySelector('[name=voice_id]').value" in page
            assert "start_block:Number(card.querySelector('[name=start]').value)" in page
        try:
            urllib.request.urlopen(url + "/api/manifest", timeout=3)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("manifest API must require a bearer token")

        headers = {"Authorization": f"Bearer {server.review_token}"}
        request = urllib.request.Request(url + "/api/manifest", headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            request_payload = json.loads(response.read())
        chapters = [
            {
                "id": chapter["id"],
                "title": chapter["title"],
                "start_block": chapter["start_block"],
                "end_block": chapter["end_block"],
                "voice_id": chapter["voice_id"],
            }
            for chapter in request_payload["chapters"]
        ]
        assert len(chapters) == 2
        save_request = urllib.request.Request(
            url + "/api/chapters",
            data=_page_save_body(chapters),
            method="POST",
            headers={
                **headers,
                "Origin": url,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(save_request, timeout=3) as response:
            assert json.loads(response.read()) == {"ok": True}
        assert [chapter.voice_id for chapter in read_manifest(manifest_path).chapters] == [
            "Jasper",
            "Bella",
        ]

        chapters[0]["title"] = "Reviewed First Chapter"
        chapters[0]["voice_id"] = "Jasper"
        chapters[1]["voice_id"] = "Bella"
        chapters[0]["end_block"] += 1
        chapters[1]["start_block"] += 1
        save_request = urllib.request.Request(
            url + "/api/chapters",
            data=_page_save_body(chapters),
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


def test_review_server_accepts_host_without_port_on_port_80(tmp_path, monkeypatch):
    from pdf2audiobook import review_ui

    manifest_path = _manifest(tmp_path)

    class Port80AuthorityServer(review_ui.ThreadingHTTPServer):
        def __init__(self, address, handler):
            super().__init__((address[0], 0), handler)
            self.actual_port = self.server_address[1]
            # The test runner may not have permission to bind a privileged port.
            # Preserve the configured port for Host-authority validation.
            self.server_address = (address[0], 80)

    monkeypatch.setattr(review_ui, "ThreadingHTTPServer", Port80AuthorityServer)
    server = review_ui.create_review_server(manifest_path, port=80)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.actual_port}/", headers={"Host": "127.0.0.1"}
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            assert response.status == 200
            assert b"Chapter review" in response.read()
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
    with pytest.raises(ValueError, match="IPv6"):
        create_review_server(manifest_path, host="::1", port=0)


def test_review_server_accepts_implicit_port_80_authority():
    assert _expected_authorities("127.0.0.1", 80) == {"127.0.0.1", "127.0.0.1:80"}


def test_review_page_offers_acknowledgement_control_for_ambiguous_pagination(tmp_path):
    manifest_path = _manifest(tmp_path)
    manifest = read_manifest(manifest_path)
    manifest.review_required = ["ambiguous_page_numbers"]
    write_manifest(manifest_path, manifest)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(url + "/", timeout=3) as response:
            page = response.read().decode()
        assert "ambiguous_page_numbers" in page
        assert "ambiguous page-number cleanup" in page
        assert "checkbox.type='checkbox'" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_review_server_rejects_mismatched_post_origin(tmp_path):
    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    request = urllib.request.Request(
        url + "/api/chapters",
        data=b'{"chapters":[]}',
        method="POST",
        headers={
            "Authorization": f"Bearer {server.review_token}",
            "Origin": "http://attacker.example",
            "Content-Type": "application/json",
        },
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 403
        assert "First chapter prose" not in exc.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_review_server_rejects_wrong_host_before_token_or_manifest_access(tmp_path):
    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for path, method, body in (
            ("/", "GET", None),
            ("/api/manifest", "GET", None),
            ("/api/chapters", "POST", b'{"chapters":[]}'),
        ):
            headers = {"Host": "rebinding.example"}
            if path.startswith("/api/"):
                headers["Authorization"] = f"Bearer {server.review_token}"
            if method == "POST":
                headers["Origin"] = url
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(url + path, data=body, method=method, headers=headers)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(request, timeout=3)
            response_body = exc.value.read().decode()
            assert exc.value.code == 421
            assert server.review_token not in response_body
            assert "First chapter prose" not in response_body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_review_server_rejects_mismatched_get_origin(tmp_path):
    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    request = urllib.request.Request(
        url + "/api/manifest",
        headers={
            "Authorization": f"Bearer {server.review_token}",
            "Origin": "http://attacker.example",
        },
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 403
        body = exc.value.read().decode()
        assert "First chapter prose" not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_review_server_rejects_non_ascii_auth_and_oversized_body(tmp_path, monkeypatch):
    import http.client

    manifest_path = _manifest(tmp_path)
    server = create_review_server(manifest_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    url = f"http://{host}:{port}"
    try:
        connection = http.client.HTTPConnection(host, port, timeout=3)
        connection.request("GET", "/api/manifest", headers={"Authorization": "Bearer \xff"})
        response = connection.getresponse()
        assert response.status == 401
        assert "First chapter prose" not in response.read().decode()
        connection.close()

        connection = http.client.HTTPConnection(host, port, timeout=3)
        connection.request(
            "POST",
            "/api/chapters",
            body=b'{"chapters":[]}',
            headers={
                "Authorization": "Bearer \xff",
                "Origin": url,
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        assert response.status == 401
        assert "First chapter prose" not in response.read().decode()
        connection.close()

        monkeypatch.setattr("pdf2audiobook.review_ui._MAX_REQUEST_BYTES", 4)
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
        assert exc.value.code == 413
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_missing_voice_id_is_unchanged_and_empty_clears(tmp_path):
    manifest_path = _manifest(tmp_path)
    manifest = read_manifest(manifest_path)
    manifest.chapters[0].voice_id = "Jasper"
    write_manifest(manifest_path, manifest)
    updates = [
        {
            "id": chapter.id,
            "title": chapter.title,
            "start_block": chapter.start_block,
            "end_block": chapter.end_block,
        }
        for chapter in manifest.chapters
    ]
    save_chapter_updates(manifest_path, updates)
    assert read_manifest(manifest_path).chapters[0].voice_id == "Jasper"
    updates[0]["voice_id"] = ""
    save_chapter_updates(manifest_path, updates)
    assert read_manifest(manifest_path).chapters[0].voice_id is None
