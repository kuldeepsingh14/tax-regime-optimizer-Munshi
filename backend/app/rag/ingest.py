"""Corpus ingestion.

Statutory text chunks badly with naive fixed-size splitting: a section's
proviso ends up divorced from the rule it qualifies, and the retrieved chunk
is then actively misleading rather than merely unhelpful.

So we chunk on section boundaries first, and only split further when a section
is genuinely too long — carrying the section heading into every sub-chunk so
each one is self-describing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.store import Chunk, Embedder, VectorStore

MAX_CHARS = 1200
OVERLAP = 150

# "Section 80C." / "80CCD(1B)." / "Section 24."
_SECTION_RE = re.compile(
    r"^\s*(?:Section\s+)?(\d{1,3}[A-Z]{0,4}(?:\(\d+[A-Z]?\))?)\s*[.\u2014-]\s*(.+)$",
    re.M,
)


@dataclass(frozen=True)
class Document:
    title: str
    text: str
    source: str
    doc_type: str = "act"   # act | circular | rule


def split_into_sections(text: str) -> list[tuple[str, str]]:
    """Return (section_label, body) pairs. Falls back to one unlabelled block."""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [("", text.strip())]

    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        label = match.group(1)
        body = text[match.start() : end].strip()
        sections.append((label, body))

    return sections


def window(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Split oversized text on sentence boundaries where possible."""
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(". ", start + max_chars // 2, end)
            if boundary != -1:
                end = boundary + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [p for p in pieces if p]


def chunk_document(doc: Document) -> list[Chunk]:
    chunks: list[Chunk] = []

    for section_label, body in split_into_sections(doc.text):
        heading = body.split("\n", 1)[0][:120]

        for i, piece in enumerate(window(body)):
            # Carry the heading into continuation chunks so a retrieved
            # fragment always says what it is about.
            text = piece if i == 0 else f"[{section_label} — {heading}]\n{piece}"
            chunk_id = f"{doc.source}:{section_label or 'x'}:{i}"
            chunks.append(
                Chunk(
                    id=chunk_id,
                    text=text,
                    metadata={
                        "section": section_label,
                        "title": doc.title,
                        "source": doc.source,
                        "doc_type": doc.doc_type,
                    },
                )
            )

    return chunks


def ingest(
    docs: list[Document], embedder: Embedder, store: VectorStore, batch: int = 64
) -> int:
    """Chunk, embed, and upsert. Returns the number of chunks written."""
    chunks: list[Chunk] = []
    for doc in docs:
        chunks.extend(chunk_document(doc))

    total = 0
    for i in range(0, len(chunks), batch):
        window_chunks = chunks[i : i + batch]
        vectors = embedder.embed([c.text for c in window_chunks])
        total += store.upsert(window_chunks, vectors)

    return total
