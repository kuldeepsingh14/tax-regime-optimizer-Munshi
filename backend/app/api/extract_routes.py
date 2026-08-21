"""Extraction endpoints.

Extraction and computation are deliberately separate endpoints. The user must
confirm extracted values before anything is computed — we never compute
silently on machine-extracted numbers.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.extraction.graph import run_extraction
from app.extraction.llm import GroqClient, LLMClient
from app.reconciliation.graph import run_reconciliation

log = logging.getLogger("taxopt.extract")
router = APIRouter(prefix="/api/v1", tags=["extraction"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FILES = 3


def get_llm() -> LLMClient | None:
    """Groq if configured, otherwise None — the graph degrades to regex-only
    and escalates to human review rather than failing."""
    if not os.getenv("GROQ_API_KEY"):
        return None
    try:
        return GroqClient()
    except Exception as e:
        log.warning("LLM unavailable, falling back to regex-only: %s", e)
        return None


def _serialise(value) -> str:
    return str(value)


@router.post("/extract")
async def extract(files: list[UploadFile] = File(...)) -> dict:
    """Upload Form 16, and optionally AIS and 26AS.

    Returns extracted fields, any conflicts between documents, and the fields
    the user must confirm. Nothing is persisted.
    """
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"At most {MAX_FILES} documents per request")

    llm = get_llm()
    documents: dict[str, dict] = {}
    per_document: list[dict] = []

    for upload in files:
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{upload.filename} exceeds 10 MB")
        if not data:
            raise HTTPException(400, f"{upload.filename} is empty")

        state = run_extraction(data=data, llm=llm)
        doc_type = state.get("doc_type", "unknown")
        extracted = state.get("extracted", {})

        if doc_type != "unknown" and extracted:
            documents[doc_type] = extracted

        per_document.append(
            {
                "filename": upload.filename,
                "doc_type": doc_type,
                "strategy_used": state.get("strategy"),
                "attempts": state.get("attempts"),
                "needs_human_review": state.get("needs_human", False),
                "validation_errors": state.get("validation_errors", []),
                "fields": {k: _serialise(v) for k, v in extracted.items()},
                "trace": state.get("trace", []),
            }
        )

    reconciliation = None
    if len(documents) > 1:
        rec = run_reconciliation(documents)
        reconciliation = {
            "merged": {k: _serialise(v) for k, v in rec.get("merged", {}).items()},
            "conflicts": [c.to_dict() for c in rec.get("conflicts", [])],
            "needs_user_confirmation": rec.get("needs_user_confirmation", []),
            "trace": rec.get("trace", []),
        }

    return {
        "documents": per_document,
        "reconciliation": reconciliation,
        "llm_available": llm is not None,
        "note": "Confirm every field before computing. Nothing has been stored.",
    }
