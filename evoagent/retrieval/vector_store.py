"""PersistentVectorStore — a small on-disk cosine-similarity vector database.

Stores (id, vector, text, metadata) records, searches by cosine similarity, and
persists atomically to a JSON file. Uses numpy for the similarity math when it
is available, falling back to pure Python otherwise. Vectors are L2-normalized
on insert so search is a single dot product.
"""

import json
import math
import os
from pathlib import Path
from typing import Any

try:  # optional acceleration
    import numpy as _np
except Exception:  # pragma: no cover - numpy is usually present
    _np = None

_STORE_FILE = "vectors.json"


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return list(vec)
    return [v / norm for v in vec]


class PersistentVectorStore:
    """An append/upsert cosine vector store with optional disk persistence."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._ids: list[str] = []
        self._texts: list[str] = []
        self._meta: list[dict[str, Any]] = []
        self._vectors: list[list[float]] = []  # stored normalized
        self._pos: dict[str, int] = {}
        self._matrix = None  # cached numpy matrix
        if self.path and (self.path / _STORE_FILE).exists():
            self.load()

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def dim(self) -> int:
        return len(self._vectors[0]) if self._vectors else 0

    def add(self, id: str, vector: list[float], text: str = "",
            metadata: dict[str, Any] | None = None) -> None:
        norm_vec = _normalize(vector)
        if id in self._pos:
            i = self._pos[id]
            self._vectors[i] = norm_vec
            self._texts[i] = text
            self._meta[i] = metadata or {}
        else:
            self._pos[id] = len(self._ids)
            self._ids.append(id)
            self._vectors.append(norm_vec)
            self._texts.append(text)
            self._meta.append(metadata or {})
        self._matrix = None

    def add_many(self, items: list[dict[str, Any]]) -> None:
        for it in items:
            self.add(it["id"], it["vector"], it.get("text", ""), it.get("metadata"))

    def delete(self, id: str) -> bool:
        if id not in self._pos:
            return False
        i = self._pos.pop(id)
        for seq in (self._ids, self._texts, self._meta, self._vectors):
            seq.pop(i)
        # Reindex positions after the removed element.
        self._pos = {cid: idx for idx, cid in enumerate(self._ids)}
        self._matrix = None
        return True

    def clear(self) -> None:
        self._ids.clear()
        self._texts.clear()
        self._meta.clear()
        self._vectors.clear()
        self._pos.clear()
        self._matrix = None

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        if not self._vectors:
            return []
        q = _normalize(query_vector)
        if _np is not None:
            if self._matrix is None:
                self._matrix = _np.asarray(self._vectors, dtype=float)
            sims = self._matrix @ _np.asarray(q, dtype=float)
            order = sims.argsort()[::-1][:top_k]
            return [
                {"id": self._ids[i], "text": self._texts[i],
                 "score": float(sims[i]), "metadata": self._meta[i]}
                for i in order
            ]
        scored = [
            (sum(a * b for a, b in zip(vec, q, strict=True)), i)
            for i, vec in enumerate(self._vectors)
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            {"id": self._ids[i], "text": self._texts[i], "score": float(s),
             "metadata": self._meta[i]}
            for s, i in scored[:top_k]
        ]

    def save(self) -> None:
        if self.path is None:
            raise ValueError("No path configured for this vector store.")
        self.path.mkdir(parents=True, exist_ok=True)
        data = {
            "records": [
                {"id": self._ids[i], "text": self._texts[i],
                 "metadata": self._meta[i], "vector": self._vectors[i]}
                for i in range(len(self._ids))
            ]
        }
        target = self.path / _STORE_FILE
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(tmp, target)

    def load(self) -> None:
        if self.path is None:
            return
        target = self.path / _STORE_FILE
        if not target.exists():
            return
        data = json.loads(target.read_text(encoding="utf-8"))
        self.clear()
        for rec in data.get("records", []):
            # Stored vectors are already normalized; keep them as-is.
            self._pos[rec["id"]] = len(self._ids)
            self._ids.append(rec["id"])
            self._vectors.append(list(rec["vector"]))
            self._texts.append(rec.get("text", ""))
            self._meta.append(rec.get("metadata", {}))
