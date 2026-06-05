"""Tests for QueryEngine and CitationBuilder."""

import tempfile
from pathlib import Path

import pytest

from evoagent.rag.citations import CitationBuilder
from evoagent.rag.document import DocumentChunk
from evoagent.rag.query_engine import QueryEngine


@pytest.fixture
def doc_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "readme.md").write_text("# EvoAgent\nEvoAgent is a Python agent framework. It supports DeepSeek and OpenAI.")
        (root / "faq.md").write_text("## FAQ\nQ: What model does the planner use?\nA: deepseek-reasoner by default.")
        yield root


def test_query_engine_ingest(doc_dir):
    qe = QueryEngine(chunk_size=200)
    count = qe.ingest_path(doc_dir)
    assert count >= 1


def test_query_engine_retrieve(doc_dir):
    qe = QueryEngine(chunk_size=200)
    qe.ingest_path(doc_dir)
    chunks = qe.retrieve("planner model", top_k=2)
    assert len(chunks) >= 1
    assert any("deepseek-reasoner" in c.text for c in chunks)


def test_query_engine_build_context(doc_dir):
    qe = QueryEngine(chunk_size=200)
    qe.ingest_path(doc_dir)
    ctx = qe.build_context("Python framework", top_k=2)
    assert "## Retrieved Documents" in ctx
    assert "EvoAgent" in ctx


def test_citation_builder():
    chunk = DocumentChunk(
        text="hello world",
        document_id="doc_1",
        start_char=10,
        end_char=21,
        metadata={"source": "test.md"},
    )
    label = CitationBuilder.format_citation(chunk)
    assert "test.md" in label
    assert "C10" in label


def test_citation_builder_block():
    chunks = [
        DocumentChunk(text="first chunk", metadata={"source": "a.md"}, start_char=0, end_char=11),
        DocumentChunk(text="second chunk", metadata={"source": "b.md"}, start_char=0, end_char=12),
    ]
    block = CitationBuilder.format_block(chunks)
    assert "## Sources" in block
    assert "a.md" in block
    assert "b.md" in block


def test_citation_builder_empty():
    assert CitationBuilder.format_block([]) == ""
