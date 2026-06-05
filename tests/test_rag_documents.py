"""Tests for document loading and chunking."""

import tempfile
from pathlib import Path

import pytest

from evoagent.rag.chunker import SimpleTextChunker
from evoagent.rag.loaders import DirectoryLoader, TextLoader


@pytest.fixture
def doc_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "readme.md").write_text("# Hello\nWorld")
        (root / "config.yaml").write_text("key: value")
        (root / "script.py").write_text("print(1)")
        (root / "data.json").write_text('{"a": 1}')
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("git")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "x.pyc").write_text("cache")
        yield root


def test_text_loader_loads_txt():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        p = f.name
    loader = TextLoader()
    doc = loader.load(p)
    assert doc is not None
    assert "hello world" in doc.text
    Path(p).unlink()


def test_directory_loader_loads_all(doc_dir):
    loader = DirectoryLoader()
    docs = loader.load(doc_dir)
    assert len(docs) >= 3  # md, yaml, py, json


def test_directory_loader_skips_git(doc_dir):
    loader = DirectoryLoader()
    docs = loader.load(doc_dir)
    sources = [d.source for d in docs]
    assert not any(".git" in s for s in sources)


def test_directory_loader_skips_pycache(doc_dir):
    loader = DirectoryLoader()
    docs = loader.load(doc_dir)
    sources = [d.source for d in docs]
    assert not any("__pycache__" in s for s in sources)


def test_chunker_splits_text():
    chunker = SimpleTextChunker(chunk_size=10, chunk_overlap=2)
    chunks = chunker.chunk_text("abcdefghijklmnopqrstuvwxyz")
    assert len(chunks) >= 2
    assert all(len(c.text) <= 10 for c in chunks)


def test_chunker_preserves_metadata():
    chunker = SimpleTextChunker()
    chunks = chunker.chunk_text("hello", source="test.md", metadata={"author": "me"})
    assert len(chunks) == 1
    assert chunks[0].metadata["source"] == "test.md"
    assert chunks[0].metadata["author"] == "me"
