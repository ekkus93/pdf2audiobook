"""`review` ends cleanly, reports a busy port privately, and secret fields are declared (R78)."""

import socket

from pydantic import BaseModel, Field
from typer.testing import CliRunner

from pdf2audiobook.cli import app
from pdf2audiobook.config import _SECRET_CONFIG_PATHS, Settings, _secret_field_paths
from pdf2audiobook.models import BookManifest, Chapter, DocumentBlock
from pdf2audiobook.workspace import write_manifest

runner = CliRunner()


def _manifest(tmp_path):
    path = tmp_path / "manifest.json"
    write_manifest(
        path,
        BookManifest(
            schema_version=3,
            input_sha256="x",
            title="Book",
            source_path="source.pdf",
            blocks=[DocumentBlock(id="b", text="Text.", page_index=0)],
            chapters=[
                Chapter(id="c", number=1, title="One", start_block=0, end_block=1, confidence=1)
            ],
        ),
    )
    return path


def test_port_in_use_is_reported_without_internals(tmp_path):
    manifest = _manifest(tmp_path)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        result = runner.invoke(app, ["review", str(manifest), "--port", str(port)])
    assert result.exit_code == 2
    assert "Review server port is unavailable" in result.stderr
    assert "errno" not in result.stderr.lower() and "Address already in use" not in result.stderr


def test_ctrl_c_stops_the_review_server_normally(tmp_path, monkeypatch):
    closed = []

    class Server:
        server_address = ("127.0.0.1", 8765)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            closed.append(True)

    monkeypatch.setattr("pdf2audiobook.review_ui.create_review_server", lambda *_a, **_k: Server())
    result = runner.invoke(app, ["review", str(_manifest(tmp_path))])
    assert result.exit_code == 0, result.stderr
    assert "Review server stopped." in result.stderr
    assert closed == [True]


class _Inner(BaseModel):
    token: str | None = Field(default=None, json_schema_extra={"secret": True})
    plain: str = "x"


class _Outer(BaseModel):
    inner: _Inner = _Inner()
    key: str | None = Field(default=None, json_schema_extra={"secret": True})


def test_secret_paths_are_derived_from_marked_fields():
    assert _secret_field_paths(_Outer) == {"key", "inner.token"}


def test_declared_secret_paths_name_real_settings_fields():
    def resolve(path):
        model = Settings
        field = None
        for part in path.split("."):
            field = model.model_fields[part]
            model = field.annotation
        return field

    for path in _SECRET_CONFIG_PATHS:
        assert resolve(path) is not None
    assert "pdf.password" not in _SECRET_CONFIG_PATHS
