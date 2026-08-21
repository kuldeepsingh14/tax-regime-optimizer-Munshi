"""Retrieval infrastructure.

Two Protocols — Embedder and VectorStore — so the RAG graph can be tested
without network, an API key, or a 500 MB model download. The in-memory store
is not a toy: it is the reason every branch of Graph C is deterministically
testable.

MEMORY NOTE: Render's free tier gives 512 MB. sentence-transformers pulls in
PyTorch (~800 MB installed) and will not fit. FastEmbed runs the same
all-MiniLM-L6-v2 weights through ONNX Runtime in roughly 50 MB. This is the
single most important dependency decision in the project.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Protocol

EMBED_DIM = 384  # all-MiniLM-L6-v2


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


# --------------------------------------------------------------------------
# embedding
# --------------------------------------------------------------------------

class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """Production embedder. ONNX, no PyTorch, fits in Render's memory budget."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._model.embed(texts)]


class LexicalEmbedder:
    """TF-IDF lexical embedder. No model download, no network, deterministic.

    Two jobs. In tests it makes every branch of the RAG graph reproducible
    without a 90 MB download. In production it is the cold-start fallback:
    Render spins down after idle, and a first request that would otherwise
    block on loading an ONNX model can be served lexically instead.

    Lexical retrieval genuinely works on statutory text because the
    vocabulary is precise and near-unique — "80CCD", "marginal relief",
    "surcharge" are exact tokens, not paraphrases. It degrades on
    conversational phrasing, which is what the rewrite node exists to fix.
    """

    def __init__(self, dim: int = 8192) -> None:
        self.dim = dim
        self._idf: dict[str, float] = {}
        self._docs = 0

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def fit(self, corpus: list[str]) -> "LexicalEmbedder":
        """Learn inverse document frequency so common words stop dominating."""
        self._docs = len(corpus) or 1
        seen: dict[str, int] = {}
        for text in corpus:
            for token in set(self._tokens(text)):
                seen[token] = seen.get(token, 0) + 1
        self._idf = {
            token: math.log((self._docs + 1) / (count + 1)) + 1.0
            for token, count in seen.items()
        }
        return self

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        counts: dict[str, int] = {}
        for token in self._tokens(text):
            counts[token] = counts.get(token, 0) + 1

        vec = [0.0] * self.dim
        for token, count in counts.items():
            weight = (1.0 + math.log(count)) * self._idf.get(token, 1.0)
            vec[hash(token) % self.dim] += weight

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# Backwards-compatible alias
HashEmbedder = LexicalEmbedder


# --------------------------------------------------------------------------
# vector store
# --------------------------------------------------------------------------

class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> int: ...
    def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class InMemoryStore:
    """Test double, and a viable fallback when Pinecone is not configured.

    The Act corpus is small enough (a few hundred chunks) that brute-force
    cosine search is genuinely fast. Pinecone is for scale we may never need.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        for chunk, vector in zip(chunks, vectors):
            self._chunks[chunk.id] = chunk
            self._vectors[chunk.id] = vector
        return len(chunks)

    def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=self._chunks[cid], score=cosine(vector, vec))
            for cid, vec in self._vectors.items()
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._chunks)


class PineconeStore:
    """Production store. Corpus only — never user data.

    Form 16 contents are processed in memory and discarded; nothing about a
    taxpayer is ever embedded or persisted.
    """

    def __init__(self, index_name: str = "tax-act") -> None:
        from pinecone import Pinecone

        key = os.getenv("PINECONE_API_KEY")
        if not key:
            raise RuntimeError("PINECONE_API_KEY is not set")
        self._index = Pinecone(api_key=key).Index(index_name)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        payload = [
            {
                "id": chunk.id,
                "values": vector,
                "metadata": {**chunk.metadata, "text": chunk.text},
            }
            for chunk, vector in zip(chunks, vectors)
        ]
        for i in range(0, len(payload), 100):  # Pinecone batch limit
            self._index.upsert(vectors=payload[i : i + 100])
        return len(payload)

    def query(self, vector: list[float], top_k: int) -> list[ScoredChunk]:
        response = self._index.query(
            vector=vector, top_k=top_k, include_metadata=True
        )
        out = []
        for match in response.get("matches", []):
            meta = dict(match.get("metadata") or {})
            text = meta.pop("text", "")
            out.append(
                ScoredChunk(
                    chunk=Chunk(id=match["id"], text=text, metadata=meta),
                    score=float(match.get("score", 0.0)),
                )
            )
        return out
