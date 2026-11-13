"""Names tests patch on `pipeline` must reach code moved out of it (module split spec M5).

`conversion.py` (and `analysis.py`, once the analysis code moves there) get those
names through a services record built in `pipeline.py`. A direct import would
bypass the patch silently, so the test that relies on it would test nothing.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "pdf2audiobook"
PATCH = re.compile(r"""setattr\(\s*(?:"pdf2audiobook\.pipeline\.(\w+)"|pipeline\s*,\s*"(\w+)")""")

# Module -> patched names it may use directly, with the reason.
DIRECT_USE_ALLOWED = {
    # The tests that patch these on `pipeline` exercise analysis only.
    "conversion.py": {"digest_file", "write_json"},
    "analysis.py": set(),
}


def patched_pipeline_names() -> set[str]:
    names = set()
    for path in (ROOT / "tests").glob("*.py"):
        for match in PATCH.finditer(path.read_text(encoding="utf-8")):
            names.add(match.group(1) or match.group(2))
    return names


def direct_uses(source: str, names: set[str]) -> set[str]:
    """Patched names the module binds at top level and then uses as bare names."""
    tree = ast.parse(source)
    bound = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            bound |= {target.id for target in node.targets if isinstance(target, ast.Name)}
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return bound & used & names


def test_the_scan_finds_the_patched_pipeline_names():
    names = patched_pipeline_names()
    assert {"propose_chapters", "read_manifest", "synthesize_chunks"} <= names


def test_moved_pipeline_code_uses_patched_names_only_through_services():
    names = patched_pipeline_names()
    for module, allowed in DIRECT_USE_ALLOWED.items():
        path = PACKAGE / module
        if not path.exists():
            continue
        unexpected = direct_uses(path.read_text(encoding="utf-8"), names) - allowed
        assert not unexpected, f"{module} uses patched pipeline names directly: {unexpected}"


def test_the_guard_catches_a_direct_import():
    source = "from pdf2audiobook.document.structure import propose_chapters\npropose_chapters()\n"
    assert direct_uses(source, patched_pipeline_names()) == {"propose_chapters"}
