"""Q&A endpoints with server-sent event streaming.

The index is built lazily on first use, not at import. Render's free tier
spins down after idle; building the index at module import would add it to
every cold start even for requests that never ask a question.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.extract_routes import get_llm
from app.rag.corpus import load_corpus
from app.rag.graph import run_qa
from app.rag.ingest import chunk_document, ingest
from app.rag.store import Embedder, InMemoryStore, LexicalEmbedder, VectorStore

log = logging.getLogger("taxopt.qa")
router = APIRouter(prefix="/api/v1", tags=["qa"])

_INDEX: tuple[Embedder, VectorStore] | None = None


def _make_embedder(chunks) -> Embedder:
    """Choose the embedder, explicitly.

    EMBEDDER=fastembed  dense vectors, best quality, needs the ONNX model cached
    EMBEDDER=lexical    TF-IDF, zero download, instant start
    EMBEDDER=auto       try FastEmbed, fall back (default)

    Why this is a setting and not just a try/except: FastEmbed retries a failed
    model download with exponential backoff totalling ~40 seconds before
    raising. On a platform that sleeps when idle, that lands on the user as a
    40-second cold start every time. If the model can't be cached at build
    time, set EMBEDDER=lexical and start instantly.
    """
    choice = os.getenv("EMBEDDER", "auto").lower()

    if choice == "lexical":
        log.info("using lexical embeddings (EMBEDDER=lexical)")
        return LexicalEmbedder().fit([c.text for c in chunks])

    try:
        from app.rag.store import FastEmbedder

        embedder = FastEmbedder()
        log.info("using FastEmbed embeddings")
        return embedder
    except Exception as e:
        if choice == "fastembed":
            # Explicitly requested and unavailable: that is a deploy error,
            # not something to paper over silently.
            raise RuntimeError(
                "EMBEDDER=fastembed but the model could not be loaded. "
                "Cache it at build time or set EMBEDDER=lexical."
            ) from e
        log.warning("FastEmbed unavailable (%s); using lexical embeddings", e)
        return LexicalEmbedder().fit([c.text for c in chunks])


def build_index() -> tuple[Embedder, VectorStore]:
    """Embedder and store, chosen by what the environment provides.

    FastEmbed + Pinecone in production. Lexical + in-memory when neither is
    configured — which keeps the app fully functional on a bare checkout with
    no API keys, and is a genuine cold-start fallback rather than a stub.
    """
    docs = load_corpus()
    chunks = [c for d in docs for c in chunk_document(d)]

    embedder = _make_embedder(chunks)

    store: VectorStore
    if os.getenv("PINECONE_API_KEY"):
        try:
            from app.rag.store import PineconeStore

            store = PineconeStore()
            log.info("using Pinecone vector store")
        except Exception as e:
            log.warning("Pinecone unavailable (%s); using in-memory store", e)
            store = InMemoryStore()
    else:
        store = InMemoryStore()

    if isinstance(store, InMemoryStore):
        count = ingest(docs, embedder, store)
        log.info("ingested %d chunks in memory", count)

    return embedder, store


def get_index() -> tuple[Embedder, VectorStore]:
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index()
    return _INDEX


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/ask")
async def ask(req: AskRequest) -> StreamingResponse:
    """Answer a tax-law question. Streams tokens over SSE.

    The graph runs to completion first, then the answer is streamed. True
    token-level streaming would require plumbing the stream through every
    node; the graph's value is its branching, and a user watching a spinner
    for two seconds is a fair trade for retries that actually work.
    """
    embedder, store = get_index()
    llm = get_llm()

    async def stream():
        try:
            state = await asyncio.to_thread(
                run_qa, req.question, embedder, store, llm, None
            )
        except Exception as e:
            log.exception("qa failed")
            yield _sse("error", {"message": f"Could not answer: {e}"})
            return

        yield _sse(
            "meta",
            {
                "route": state.get("route"),
                "rewrites": state.get("rewrites", 0),
                "used_web": state.get("used_web", False),
                "grounded": state.get("grounded", False),
            },
        )

        answer = state.get("answer", "")
        for i in range(0, len(answer), 24):
            yield _sse("token", {"text": answer[i : i + 24]})
            await asyncio.sleep(0.015)

        yield _sse(
            "done",
            {
                "citations": state.get("citations", []),
                "sources": [
                    {
                        "section": d.chunk.metadata.get("section"),
                        "title": d.chunk.metadata.get("title"),
                        "score": round(d.score, 3),
                    }
                    for d in state.get("documents", [])
                ],
                "trace": state.get("trace", []),
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/index/status")
def index_status() -> dict:
    embedder, store = get_index()
    return {
        "embedder": type(embedder).__name__,
        "store": type(store).__name__,
        "chunks": len(store) if isinstance(store, InMemoryStore) else None,
    }
