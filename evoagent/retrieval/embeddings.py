"""BaseEmbeddingModel and embedding implementations for text vectors."""

import hashlib
import math
import re
from abc import ABC, abstractmethod


class BaseEmbeddingModel(ABC):
    """Abstract embedding model for generating text vectors."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate embedding vector for a single text."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for multiple texts."""
        return [self.embed_text(t) for t in texts]


class MockEmbeddingModel(BaseEmbeddingModel):
    """Deterministic mock embedding using SHA256 hash → 64-dim vectors.

    No network calls, always returns the same vector for the same text.
    """

    DIM = 64

    def embed_text(self, text: str) -> list[float]:
        vec: list[float] = []
        block = 0
        # A single SHA-256 digest yields only 8 four-byte values; hash
        # additional salted blocks until every dimension has real signal
        # (instead of zero-padding 56 of 64 dims).
        while len(vec) < self.DIM:
            h = hashlib.sha256(f"{block}:{text}".encode()).digest()
            for i in range(0, len(h), 4):
                if len(vec) >= self.DIM:
                    break
                val = int.from_bytes(h[i:i + 4], "big") / (2**32)
                vec.append(val * 2 - 1)
            block += 1
        return vec


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    return _TOKEN_RE.findall(lowered) + _CJK_RE.findall(lowered)


class HashingEmbeddingModel(BaseEmbeddingModel):
    """Deterministic feature-hashing (bag-of-words) embedding.

    Uses the hashing trick: each token is hashed to a dimension with a signed
    bucket, then the vector is L2-normalized. Unlike the per-text hash of
    :class:`MockEmbeddingModel`, texts that share tokens get overlapping
    dimensions and therefore meaningful (lexical-semantic) cosine similarity —
    suitable for augmenting deterministic code retrieval without any network
    calls or external models.
    """

    def __init__(self, dim: int = 256):
        if dim < 8:
            raise ValueError("dim must be >= 8")
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = hashlib.md5(tok.encode()).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if (h[4] & 1) else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]
