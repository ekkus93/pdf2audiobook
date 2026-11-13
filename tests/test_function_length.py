"""Guard against long functions growing back (long function split spec S10)."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
MAX_FUNCTION_LINES = 100

# Functions over the limit, each with its line count as a ceiling. An entry
# may shrink but never grow; remove it once its function is split. Keys are
# "<path under src>::<qualified name>".
ALLOWLIST = {
    # Split by docs/PDF2AUDIOBOOK_LONG_FUNCTION_SPLIT_TODO.md (spec §1).
    "pdf2audiobook/conversion.py::_convert_analyzed_book": 421,
    "pdf2audiobook/audio/__init__.py::synthesize_chunks": 308,
    "pdf2audiobook/llm/cache.py::CachedLLMProvider._complete_json_call": 264,
    "pdf2audiobook/llm/provider.py::OpenAICompatibleProvider._complete_json_request": 262,
    "pdf2audiobook/pdf.py::extract_pdf": 225,
    "pdf2audiobook/cli.py::convert": 140,
    # Not in the split spec's scope; see the TODO's notes.
    "pdf2audiobook/llm/structure.py::propose_llm_contents_boundaries": 234,
    "pdf2audiobook/review_ui.py::create_review_server": 163,
    "pdf2audiobook/llm/__init__.py::propose_llm_narration": 142,
    "pdf2audiobook/cli.py::pack_m4b": 134,
    "pdf2audiobook/audio/encoding.py::encode_m4b": 132,
    "pdf2audiobook/llm/__init__.py::propose_llm_cleanup": 126,
    "pdf2audiobook/llm/structure.py::detect_llm_headings": 116,
    "pdf2audiobook/pdf.py::_footnote_line_indices": 112,
    "pdf2audiobook/document/structure.py::_printed_contents": 110,
    "pdf2audiobook/llm/__init__.py::propose_llm_classification": 109,
    "pdf2audiobook/reading_order.py::order_two_columns": 108,
    "pdf2audiobook/llm/equations.py::propose_llm_equation_readings": 107,
    "pdf2audiobook/llm/budget.py::BookLLMBudgetLedger._stats": 107,
    "pdf2audiobook/cli.py::batch": 106,
}


def _is_typer_command(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "command":
            return True
    return False


def function_lengths(root: Path = SOURCE_ROOT) -> dict[str, int]:
    """Line counts of every function, nested functions included in their parent.

    Typer commands are measured from their first body statement, so their
    option declarations do not count.
    """
    lengths: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root).as_posix()

        def visit(node: ast.AST, prefix: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"{prefix}{child.name}"
                    start = child.body[0].lineno if _is_typer_command(child) else child.lineno
                    lengths[f"{relative}::{name}"] = child.end_lineno - start + 1
                    visit(child, f"{name}.")
                elif isinstance(child, ast.ClassDef):
                    visit(child, f"{prefix}{child.name}.")
                else:
                    visit(child, prefix)

        visit(tree, "")
    return lengths


def test_no_function_exceeds_its_line_limit():
    lengths = function_lengths()
    too_long = {
        name: length
        for name, length in lengths.items()
        if length > ALLOWLIST.get(name, MAX_FUNCTION_LINES)
    }
    assert not too_long, f"functions over their line limit: {too_long}"


def test_allowlist_names_only_existing_functions_still_over_the_limit():
    lengths = function_lengths()
    stale = {
        name: lengths.get(name)
        for name in ALLOWLIST
        if lengths.get(name) is None or lengths[name] <= MAX_FUNCTION_LINES
    }
    assert not stale, f"remove these allowlist entries: {stale}"
