"""Tests for P2 vector store + hashing embeddings + embedding-augmented retrieval."""

import pytest

from evoagent.retrieval.code_retriever import CodeRetriever
from evoagent.retrieval.embeddings import HashingEmbeddingModel
from evoagent.retrieval.vector_store import PersistentVectorStore


def test_vector_store_add_and_search():
    store = PersistentVectorStore()
    store.add("a", [1.0, 0.0, 0.0], text="alpha")
    store.add("b", [0.0, 1.0, 0.0], text="beta")
    store.add("c", [0.9, 0.1, 0.0], text="near-alpha")
    hits = store.search([1.0, 0.0, 0.0], top_k=2)
    assert hits[0]["id"] == "a"
    assert hits[1]["id"] == "c"
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)
    assert len(store) == 3


def test_vector_store_upsert_and_delete():
    store = PersistentVectorStore()
    store.add("x", [1.0, 0.0], text="first")
    store.add("x", [0.0, 1.0], text="updated")
    assert len(store) == 1
    hits = store.search([0.0, 1.0], top_k=1)
    assert hits[0]["text"] == "updated"
    assert store.delete("x") is True
    assert len(store) == 0
    assert store.delete("x") is False


def test_vector_store_persistence(tmp_path):
    store = PersistentVectorStore(tmp_path / "vs")
    store.add("a", [1.0, 2.0, 2.0], text="hello", metadata={"k": "v"})
    store.save()
    reloaded = PersistentVectorStore(tmp_path / "vs")
    assert len(reloaded) == 1
    hits = reloaded.search([1.0, 2.0, 2.0], top_k=1)
    assert hits[0]["id"] == "a"
    assert hits[0]["metadata"] == {"k": "v"}
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)


def test_hashing_embedding_similarity():
    m = HashingEmbeddingModel(dim=256)
    v1 = m.embed_text("authenticate user login password")
    v2 = m.embed_text("user authentication and login")
    v3 = m.embed_text("matrix multiplication linear algebra")

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    # Shared tokens -> higher similarity than an unrelated sentence.
    assert cos(v1, v2) > cos(v1, v3)
    # Deterministic + L2-normalized.
    assert m.embed_text("same") == m.embed_text("same")
    assert cos(v1, v1) == pytest.approx(1.0, abs=1e-6)


def test_hashing_embedding_dim_validation():
    with pytest.raises(ValueError):
        HashingEmbeddingModel(dim=4)


def _workspace(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    '''Verify the user's credentials and issue a session token.'''\n"
        "    return _check(username, password)\n"
    )
    (tmp_path / "geometry.py").write_text(
        "def area_of_circle(radius):\n"
        "    return 3.14159 * radius * radius\n"
    )


def test_code_retriever_embeddings_enabled(tmp_path):
    _workspace(tmp_path)
    r = CodeRetriever(tmp_path, use_embeddings=True)
    n = r.build_index()
    assert n > 0
    # A semantically-phrased query (no exact keyword 'authenticate_user').
    hits = r.search("verify credentials and sign in", top_k=3)
    assert hits
    assert hits[0].path.endswith("auth.py")


def test_code_retriever_embeddings_uses_vector_store(tmp_path):
    _workspace(tmp_path)
    store = PersistentVectorStore()
    r = CodeRetriever(tmp_path, use_embeddings=True, vector_store=store)
    r.build_index()
    # The provided vector store was populated with one entry per chunk.
    assert len(store) >= 2


def test_code_retriever_default_no_embeddings(tmp_path):
    _workspace(tmp_path)
    r = CodeRetriever(tmp_path)
    r.build_index()
    assert r._vectors is None
    hits = r.search("authenticate_user", top_k=2)
    assert hits[0].path.endswith("auth.py")
