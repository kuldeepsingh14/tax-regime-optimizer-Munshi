"""Graph A — Document Extraction.

    ingest -> classify -> extract -> validate -> [conditional]
                            ^                        |
                            |                        v
                        escalate <--------------- retry?
                                                     |
                                                     v
                                              human_review -> END

Why LangGraph and not a chain: the retry edge is conditional on validation
output AND changes strategy on retry (regex -> llm -> llm_verbose), with a
bounded attempt count and a terminal human-in-the-loop path. That is a cycle
plus a branch on state plus terminal escalation. A linear chain cannot express
it without hand-rolling the same machinery, worse.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.extraction.llm import LLMClient, extract_with_llm
from app.extraction.patterns import (
    classify_document,
    coverage,
    extract_with_regex,
    pdf_to_text,
)

MAX_ATTEMPTS = 3
MIN_COVERAGE = 0.4

Strategy = Literal["regex", "llm", "llm_verbose"]
STRATEGY_LADDER: tuple[Strategy, ...] = ("regex", "llm", "llm_verbose")


class ExtractionState(TypedDict, total=False):
    # inputs
    raw_bytes: bytes
    filename: str
    # derived
    text: str
    doc_type: str
    extracted: dict
    # control
    strategy: Strategy
    attempts: int
    validation_errors: Annotated[list[str], lambda a, b: b]
    needs_human: bool
    trace: Annotated[list[str], lambda a, b: a + b]


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_TAN_RE = re.compile(r"^[A-Z]{4}\d{5}[A-Z]$")


def validate_extraction(extracted: dict) -> list[str]:
    """Structural and arithmetic sanity checks.

    These are the checks that make the retry loop meaningful: without them the
    graph would accept any output the model produced.
    """
    errors: list[str] = []

    if not extracted:
        return ["no fields extracted"]

    if "gross_salary" not in extracted:
        errors.append("gross_salary missing — cannot compute without it")

    pan = extracted.get("pan")
    if pan and not _PAN_RE.match(str(pan).upper()):
        errors.append(f"PAN malformed: {pan}")

    tan = extracted.get("employer_tan")
    if tan and not _TAN_RE.match(str(tan).upper()):
        errors.append(f"TAN malformed: {tan}")

    gross = extracted.get("gross_salary")
    if isinstance(gross, Decimal):
        if gross <= 0:
            errors.append("gross_salary must be positive")
        elif gross > Decimal("1000000000"):
            errors.append("gross_salary implausibly large — likely a parse error")

        # Components cannot exceed the whole.
        for component in ("basic", "hra_received"):
            value = extracted.get(component)
            if isinstance(value, Decimal) and value > gross:
                errors.append(f"{component} exceeds gross_salary")

        tds = extracted.get("tds_deducted")
        if isinstance(tds, Decimal) and tds > gross:
            errors.append("tds_deducted exceeds gross_salary")

    if coverage(extracted) < MIN_COVERAGE:
        errors.append(f"coverage {coverage(extracted):.0%} below {MIN_COVERAGE:.0%}")

    return errors


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------

def node_ingest(state: ExtractionState) -> dict:
    data = state.get("raw_bytes", b"")
    try:
        text = pdf_to_text(data) if data else state.get("text", "")
    except Exception as e:  # corrupt PDF, encrypted, etc.
        return {
            "text": "",
            "validation_errors": [f"could not read PDF: {e}"],
            "needs_human": True,
            "trace": ["ingest: failed"],
        }

    if not text.strip():
        return {
            "text": "",
            "validation_errors": ["no extractable text — likely a scanned image"],
            "needs_human": True,
            "trace": ["ingest: empty text"],
        }

    return {"text": text, "trace": [f"ingest: {len(text)} chars"]}


def node_classify(state: ExtractionState) -> dict:
    doc_type = classify_document(state.get("text", ""))
    return {"doc_type": doc_type, "trace": [f"classify: {doc_type}"]}


def make_extract_node(llm: LLMClient | None):
    def node_extract(state: ExtractionState) -> dict:
        strategy = state.get("strategy", "regex")
        text = state.get("text", "")
        doc_type = state.get("doc_type", "unknown")
        attempts = state.get("attempts", 0) + 1

        if strategy == "regex":
            extracted = extract_with_regex(text, doc_type)
        else:
            if llm is None:
                return {
                    "extracted": state.get("extracted", {}),
                    "attempts": attempts,
                    "validation_errors": ["LLM fallback unavailable"],
                    "needs_human": True,
                    "trace": [f"extract[{strategy}]: no LLM configured"],
                }
            extracted = extract_with_llm(
                llm, text, doc_type, verbose=(strategy == "llm_verbose")
            )
            # Regex results are kept where the model returned nothing: a union
            # is strictly better than either source alone.
            extracted = {**state.get("extracted", {}), **extracted}

        return {
            "extracted": extracted,
            "attempts": attempts,
            "trace": [
                f"extract[{strategy}]: {len(extracted)} fields, "
                f"coverage {coverage(extracted):.0%}"
            ],
        }

    return node_extract


def node_validate(state: ExtractionState) -> dict:
    errors = validate_extraction(state.get("extracted", {}))
    return {
        "validation_errors": errors,
        "trace": [f"validate: {len(errors)} error(s)"],
    }


def node_escalate(state: ExtractionState) -> dict:
    """Move one rung up the strategy ladder."""
    current = state.get("strategy", "regex")
    index = STRATEGY_LADDER.index(current)
    nxt = STRATEGY_LADDER[min(index + 1, len(STRATEGY_LADDER) - 1)]
    return {"strategy": nxt, "trace": [f"escalate: {current} -> {nxt}"]}


def node_human_review(state: ExtractionState) -> dict:
    """Terminal. Whatever was extracted is handed to the user to correct.

    Partial extraction is still useful — it pre-fills the form even when it
    fails validation. The user confirms every field regardless.
    """
    return {"needs_human": True, "trace": ["human_review: manual confirmation required"]}


# --------------------------------------------------------------------------
# conditional edges
# --------------------------------------------------------------------------

def route_after_ingest(state: ExtractionState) -> str:
    return "human_review" if state.get("needs_human") else "classify"


def route_after_validate(state: ExtractionState) -> str:
    if not state.get("validation_errors"):
        return "done"
    if state.get("attempts", 0) >= MAX_ATTEMPTS:
        return "human_review"
    if state.get("strategy") == STRATEGY_LADDER[-1]:
        return "human_review"  # ladder exhausted
    return "escalate"


# --------------------------------------------------------------------------
# graph
# --------------------------------------------------------------------------

def build_extraction_graph(llm: LLMClient | None = None):
    g = StateGraph(ExtractionState)

    g.add_node("ingest", node_ingest)
    g.add_node("classify", node_classify)
    g.add_node("extract", make_extract_node(llm))
    g.add_node("validate", node_validate)
    g.add_node("escalate", node_escalate)
    g.add_node("human_review", node_human_review)

    g.set_entry_point("ingest")
    g.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {"classify": "classify", "human_review": "human_review"},
    )
    g.add_edge("classify", "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges(
        "validate",
        route_after_validate,
        {"done": END, "escalate": "escalate", "human_review": "human_review"},
    )
    g.add_edge("escalate", "extract")   # the cycle
    g.add_edge("human_review", END)

    return g.compile()


def run_extraction(
    data: bytes | None = None,
    text: str | None = None,
    llm: LLMClient | None = None,
) -> ExtractionState:
    graph = build_extraction_graph(llm)
    initial: ExtractionState = {
        "raw_bytes": data or b"",
        "text": text or "",
        "extracted": {},
        "strategy": "regex",
        "attempts": 0,
        "validation_errors": [],
        "needs_human": False,
        "trace": [],
    }
    return graph.invoke(initial)
