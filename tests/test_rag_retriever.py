"""Tests for RAG retrieval."""

import pytest

from evoagent.rag.chunker import SimpleTextChunker
from evoagent.rag.document import Document
from evoagent.rag.index import KeywordIndex
from evoagent.rag.retriever import KeywordRetriever


@pytest.fixture
def retriever():
    idx = KeywordIndex()
    chunker = SimpleTextChunker(chunk_size=100, chunk_overlap=20)
    docs = [
        Document(text="Python is a programming language used for AI and data science.", source="a.txt"),
        Document(text="EvoAgent is built in Python and uses DeepSeek for LLM calls.", source="b.txt"),
        Document(text="The weather today is sunny with a high of 25 degrees.", source="c.txt"),
    ]
    for doc in docs:
        chunks = chunker.chunk_document(doc)
        idx.add_documents(chunks)
    return KeywordRetriever(index=idx)


def test_keyword_index_search(retriever):
    results = retriever.retrieve("python ai", top_k=3)
    assert len(results) >= 1
    assert any("Python" in r.text for r in results)


def test_keyword_index_top_k(retriever):
    results = retriever.retrieve("python", top_k=1)
    assert len(results) <= 1


def test_keyword_index_empty_query(retriever):
    results = retriever.retrieve("")
    assert results == []


def test_keyword_index_no_match(retriever):
    results = retriever.retrieve("zzzznonexistent")
    assert results == []
