"""Tests for P1.3 deterministic-first code retrieval."""

import pytest

from evoagent.retrieval.code_retriever import (
    CodeRetriever,
    _py_chunks,
    _split_identifier,
    _text_chunks,
)
from evoagent.tools.navigation_tools import CodeSearchTool


def test_split_identifier_snake_and_camel():
    assert _split_identifier("CodeRetriever") == ["code", "retriever"]
    assert _split_identifier("build_index") == ["build", "index"]
    assert _split_identifier("evoagent/retrieval/keyword.py") == [
        "evoagent", "retrieval", "keyword", "py",
    ]


def test_py_chunks_extracts_symbols_with_lines():
    src = (
        "import os\n"
        "\n"
        "CONST = 1\n"
        "\n"
        "def alpha(x):\n"
        "    return x\n"
        "\n"
        "class Beta:\n"
        "    def method(self):\n"
        "        return 2\n"
    )
    chunks = _py_chunks("m.py", src)
    kinds = {(c.kind, c.name) for c in chunks}
    assert ("function", "alpha") in kinds
    assert ("class", "Beta") in kinds
    # module-level chunk(s) capture imports/constants
    assert any(c.kind == "module" for c in chunks)
    alpha = next(c for c in chunks if c.name == "alpha")
    assert alpha.start_line == 5
    assert "return x" in alpha.text


def test_py_chunks_falls_back_on_syntax_error():
    chunks = _py_chunks("bad.py", "def (:\n  pass\n")
    # Unparseable → text chunks (non-empty), not a crash.
    assert chunks
    assert all(c.kind == "text" for c in chunks)


def test_text_chunks_windows():
    src = "\n".join(f"line {i}" for i in range(200))
    chunks = _text_chunks("notes.txt", src, window=80, overlap=20)
    assert len(chunks) >= 3
    assert chunks[0].start_line == 1
    assert chunks[0].kind == "text"


def _build_workspace(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    '''Check a user's credentials and return a token.'''\n"
        "    return verify(username, password)\n"
        "\n"
        "def verify(u, p):\n"
        "    return True\n"
    )
    (tmp_path / "pkg" / "math_utils.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
    )
    (tmp_path / "README.md").write_text("# Project\nHandles user authentication and math.\n")


def test_retriever_finds_relevant_symbol(tmp_path):
    _build_workspace(tmp_path)
    r = CodeRetriever(tmp_path)
    n = r.build_index()
    assert n > 0
    hits = r.search("authenticate user login", top_k=5)
    assert hits
    top = hits[0]
    assert top.path.endswith("auth.py")
    assert "authenticate_user" in top.text


def test_retriever_ranks_by_name_bonus(tmp_path):
    _build_workspace(tmp_path)
    r = CodeRetriever(tmp_path)
    r.build_index()
    hits = r.search("multiply", top_k=5)
    assert hits
    assert hits[0].name == "multiply"


def test_retriever_empty_query(tmp_path):
    _build_workspace(tmp_path)
    r = CodeRetriever(tmp_path)
    r.build_index()
    assert r.search("   ", top_k=5) == []


@pytest.mark.asyncio
async def test_code_search_tool(tmp_path):
    _build_workspace(tmp_path)
    tool = CodeSearchTool(tmp_path)
    res = await tool.run(query="authenticate user")
    assert res.success
    assert "auth.py" in res.output
    assert res.metadata["results"] >= 1


@pytest.mark.asyncio
async def test_code_search_tool_no_results(tmp_path):
    (tmp_path / "only.py").write_text("def foo():\n    return 1\n")
    tool = CodeSearchTool(tmp_path)
    res = await tool.run(query="zzzzzzz_nonexistent_term_qqq")
    assert res.success
    assert "No relevant code" in res.output
