"""LLM boundary.

The model sits behind a Protocol so the extraction graph can be tested without
network access, an API key, or nondeterminism. This is not a testing
convenience bolted on afterwards — it is why the graph is testable at all.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from typing import Protocol

from app.extraction.patterns import CANONICAL_FIELDS, _MONEY_FIELDS, parse_amount

_SYSTEM = (
    "You extract structured fields from Indian tax documents. "
    "Respond with ONLY a JSON object. No prose, no markdown fences. "
    "Use null for fields you cannot find. Never guess or compute values — "
    "report only what is literally present in the document."
)

_SCHEMA_HINT = json.dumps({f: None for f in CANONICAL_FIELDS}, indent=2)


def build_prompt(text: str, doc_type: str, verbose: bool) -> str:
    instruction = (
        "Read the document carefully. Some employers use non-standard layouts, "
        "so look for values in tables and multi-line labels as well as inline. "
        if verbose
        else ""
    )
    return (
        f"Document type: {doc_type}\n\n"
        f"{instruction}"
        f"Extract these fields:\n{_SCHEMA_HINT}\n\n"
        f"Document text:\n---\n{text[:12000]}\n---"
    )


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class GroqClient:
    """Production client. Requires GROQ_API_KEY."""

    def __init__(self, model: str = "openai/gpt-oss-120b") -> None:
        self.model = model
        self._key = os.getenv("GROQ_API_KEY")
        if not self._key:
            raise RuntimeError("GROQ_API_KEY is not set")

    def complete(self, system: str, user: str) -> str:
        from groq import Groq

        client = Groq(api_key=self._key)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0,  # extraction is not a creative task
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or "{}"


class ScriptedClient:
    """Deterministic stand-in for tests.

    Returns queued responses in order, so a test can script the exact sequence
    of model behaviours — including a bad first response that forces a retry.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            return "{}"
        return self._responses.pop(0)


def parse_llm_json(raw: str) -> dict:
    """Parse model output defensively.

    Models wrap JSON in fences despite instructions, so strip them. A parse
    failure returns {} rather than raising — the graph treats an empty
    extraction as a validation failure and retries, which is the correct
    recovery path.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return {}

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    out: dict = {}
    for key, value in data.items():
        if value is None or key not in CANONICAL_FIELDS:
            continue
        if key in _MONEY_FIELDS:
            parsed = parse_amount(str(value)) if not isinstance(value, Decimal) else value
            if parsed is not None:
                out[key] = parsed
        else:
            out[key] = str(value).strip()
    return out


def extract_with_llm(
    client: LLMClient, text: str, doc_type: str, verbose: bool = False
) -> dict:
    return parse_llm_json(client.complete(_SYSTEM, build_prompt(text, doc_type, verbose)))
