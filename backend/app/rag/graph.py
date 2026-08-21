"""Graph C — Tax Q&A (Agentic RAG).

                      ┌────────┐
                      │ router │
                      └───┬────┘
          computation ────┼──── out_of_scope
                │         │            │
                ▼         ▼            ▼
          deterministic  retrieve    refuse
                │         │
                ▼         ▼
               END      grade ──── relevant ──> generate ──> verify ──> END
                          │                        ▲            │
                    irrelevant                     │       ungrounded
                          │                        │            │
                    rewrites<2 ──> rewrite ────────┘            │
                          │            │                        │
                    rewrites>=2        └──> retrieve            │
                          │                                     │
                          └──> web_search ─────> generate <─────┘

THE ROUTER IS THE POINT. "What is my tax on 14 lakhs?" must NOT go to
retrieval — it goes to the deterministic engine. The router enforces the
project's governing principle at the entry point: the LLM answers questions
about the law, never questions about arithmetic.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.extraction.llm import LLMClient
from app.rag.store import Chunk, Embedder, ScoredChunk, VectorStore

MAX_REWRITES = 2
TOP_K = 4
RELEVANCE_FLOOR = 0.12

Route = Literal["law", "computation", "out_of_scope"]


class QAState(TypedDict, total=False):
    question: str
    query: str
    route: Route
    documents: list[ScoredChunk]
    grade: str
    rewrites: int
    used_web: bool
    answer: str
    citations: Annotated[list[str], lambda a, b: b]
    grounded: bool
    regenerated: bool
    trace: Annotated[list[str], lambda a, b: a + b]


# --------------------------------------------------------------------------
# routing — deterministic first, LLM only for genuine ambiguity
# --------------------------------------------------------------------------

_COMPUTATION_SIGNALS = (
    r"\bmy tax\b", r"\bhow much (?:tax|will i|do i)\b", r"\bcalculate\b",
    r"\bwhich regime (?:should|is better)\b", r"\bcompute\b",
    r"\bwhat.{0,20}\btax\b.{0,20}\bon\b",
)

# An amount alone is NOT a computation signal. "marginal relief above 12 lakh"
# is a question about the law; "my tax on 12 lakh" is a calculation. The
# amount only counts when it appears alongside first-person intent.
_AMOUNT_RE = r"\b\d+(?:\.\d+)?\s*(?:lakh|lakhs|lpa|crore|cr)\b"
_PERSONAL_RE = r"\b(?:i|my|me|i'?m)\b"


_TAX_VOCABULARY = (
    # Bare "tax" was missing, so "what are the tax rules" fell to out_of_scope.
    r"\btax(es|ed|able|ation|payer)?\b",
    r"\bgratuity\b", r"\bpension\b", r"\bsalary\b", r"\bhome\s+loan\b",
    r"\b80[a-z]{1,4}\b", r"\bsection\b", r"\bhra\b", r"\bregime\b",
    r"\bdeduction[s]?\b", r"\bexemption[s]?\b", r"\brebate\b",
    r"\bcess\b", r"\bsurcharge\b", r"\bmarginal\s+relief\b",
    r"\b87a\b", r"\b24\(?b\)?\b", r"\b115bac\b", r"\b16\(?ia\)?\b",
    r"\b10\(?13a\)?\b", r"\bnps\b", r"\bppf\b", r"\bepf\b", r"\belss\b",
    r"\bslab[s]?\b", r"\bstandard\s+deduction\b",
)


def classify_route(question: str) -> Route:
    q = question.lower()

    if any(re.search(p, q) for p in _COMPUTATION_SIGNALS):
        return "computation"
    if re.search(_AMOUNT_RE, q) and re.search(_PERSONAL_RE, q):
        return "computation"
    if any(re.search(p, q) for p in _TAX_VOCABULARY):
        return "law"
    return "out_of_scope"


def node_router(state: QAState) -> dict:
    route = classify_route(state.get("question", ""))
    return {
        "route": route,
        "query": state.get("question", ""),
        "trace": [f"router: {route}"],
    }


def route_from_router(state: QAState) -> str:
    return state.get("route", "out_of_scope")


# --------------------------------------------------------------------------
# retrieval and grading
# --------------------------------------------------------------------------

def make_retrieve_node(embedder: Embedder, store: VectorStore):
    def node_retrieve(state: QAState) -> dict:
        query = state.get("query") or state.get("question", "")
        vector = embedder.embed([query])[0]
        docs = store.query(vector, TOP_K)
        return {
            "documents": docs,
            "trace": [
                f"retrieve: {len(docs)} chunk(s), "
                f"best {docs[0].score:.2f}" if docs else "retrieve: 0 chunks"
            ],
        }

    return node_retrieve


def node_grade(state: QAState) -> dict:
    """Relevance grading on retrieval score.

    Deliberately deterministic rather than an LLM call: an extra model
    round-trip per query is real latency and cost, and the score already
    carries the signal. The LLM-grader variant is a one-line swap if the
    threshold proves too blunt.
    """
    docs = state.get("documents", [])
    keep = [d for d in docs if d.score >= RELEVANCE_FLOOR]
    grade = "relevant" if keep else "irrelevant"
    # Never drop to an empty list: downstream nodes index documents[0].
    fallback = docs[:1] if docs else []
    return {
        "documents": keep or fallback,
        "grade": grade,
        "trace": [f"grade: {grade} ({len(keep)}/{len(docs)} above floor)"],
    }


def route_from_grade(state: QAState) -> str:
    if state.get("grade") == "relevant":
        return "generate"
    if state.get("rewrites", 0) >= MAX_REWRITES:
        return "web_search"
    return "rewrite"


# --------------------------------------------------------------------------
# self-correction
# --------------------------------------------------------------------------

_REWRITE_SYSTEM = (
    "You rewrite user questions into search queries for an Indian income-tax "
    "corpus. Expand colloquial terms into statutory vocabulary. "
    "Respond with ONLY the rewritten query, no explanation."
)


def make_rewrite_node(llm: LLMClient | None):
    def node_rewrite(state: QAState) -> dict:
        original = state.get("query", "")
        attempts = state.get("rewrites", 0) + 1

        if llm is None:
            # Degraded rewrite: strip filler words to broaden the query.
            rewritten = re.sub(
                r"\b(?:can i|do i|is it|the|a|an|my|please|tell me)\b",
                " ",
                original,
                flags=re.I,
            )
            rewritten = re.sub(r"\s+", " ", rewritten).strip() or original
        else:
            rewritten = llm.complete(_REWRITE_SYSTEM, original).strip() or original

        return {
            "query": rewritten,
            "rewrites": attempts,
            "trace": [f"rewrite #{attempts}: {rewritten[:60]}"],
        }

    return node_rewrite


def make_web_search_node(search):
    """Last resort when the corpus cannot answer — typically recent
    amendments not yet in the ingested Act."""

    def node_web_search(state: QAState) -> dict:
        query = state.get("query", "")
        if search is None:
            return {
                "used_web": False,
                "trace": ["web_search: unavailable, answering from weak retrieval"],
            }

        results = search(query)
        docs = [
            ScoredChunk(
                chunk=Chunk(
                    id=r["url"],
                    text=r["snippet"],
                    metadata={"source": r["url"], "section": r.get("title", "web")},
                ),
                score=0.5,
            )
            for r in results
        ]

        return {
            "documents": docs or state.get("documents", []),
            "used_web": True,
            "trace": [f"web_search: {len(results)} result(s)"],
        }

    return node_web_search


# --------------------------------------------------------------------------
# generation and verification
# --------------------------------------------------------------------------

_ANSWER_SYSTEM = (
    "You answer questions about Indian income tax using ONLY the provided "
    "excerpts. Cite the section number for every claim, like [80C]. "
    "If the excerpts do not answer the question, say so plainly rather than "
    "guessing. Never compute a tax figure — direct the user to the calculator "
    "instead. Keep answers under 150 words."
)


def _format_context(docs: list[ScoredChunk]) -> str:
    return "\n\n".join(
        f"[{d.chunk.metadata.get('section') or d.chunk.metadata.get('source', '?')}] "
        f"{d.chunk.text}"
        for d in docs
    )


def make_generate_node(llm: LLMClient | None):
    def node_generate(state: QAState) -> dict:
        docs = state.get("documents", [])
        context = _format_context(docs)
        citations = [
            d.chunk.metadata.get("section") or d.chunk.metadata.get("source", "")
            for d in docs
        ]
        citations = [c for c in citations if c]

        if llm is None:
            excerpt = docs[0].chunk.text[:400] if docs else "(no matching provision found)"
            answer = (
                "Answer generation is unavailable, but the most relevant "
                f"provision found was:\n\n{excerpt}"
            )
        else:
            prompt = f"Question: {state.get('question')}\n\nExcerpts:\n{context}"
            answer = llm.complete(_ANSWER_SYSTEM, prompt).strip()

        return {
            "answer": answer,
            "citations": citations,
            "trace": [f"generate: {len(answer)} chars, {len(citations)} citation(s)"],
        }

    return node_generate


def node_verify(state: QAState) -> dict:
    """Groundedness check: does the answer cite anything it was given?

    Cheap and deterministic. Catches the common failure where the model
    answers confidently from parametric memory and ignores the excerpts.
    """
    answer = state.get("answer", "")
    citations = state.get("citations", [])

    if not answer:
        return {"grounded": False, "trace": ["verify: empty answer"]}

    cited = re.findall(r"\[([^\]]{1,40})\]", answer)
    declined = re.search(
        r"do(?:es)? not (?:answer|contain|cover)|cannot find|not (?:enough|sufficient)",
        answer,
        re.I,
    )

    grounded = bool(cited) or bool(declined) or not citations
    return {
        "grounded": grounded,
        "trace": [f"verify: {'grounded' if grounded else 'ungrounded'}"],
    }


def route_from_verify(state: QAState) -> str:
    if state.get("grounded") or state.get("regenerated"):
        return "done"
    return "regenerate"


def node_mark_regenerated(state: QAState) -> dict:
    return {"regenerated": True, "trace": ["regenerate: one retry only"]}


# --------------------------------------------------------------------------
# terminal nodes for non-law routes
# --------------------------------------------------------------------------

def node_computation(state: QAState) -> dict:
    return {
        "answer": (
            "That's a calculation, not a question about the law — so it goes to "
            "the calculator rather than the assistant. Enter your salary and "
            "deductions above and both regimes are computed exactly, with the "
            "full working shown."
        ),
        "citations": [],
        "grounded": True,
        "trace": ["computation: routed to deterministic engine"],
    }


def node_refuse(state: QAState) -> dict:
    return {
        "answer": (
            "I can only answer questions about Indian income tax — deductions, "
            "exemptions, regimes, and the relevant sections."
        ),
        "citations": [],
        "grounded": True,
        "trace": ["out_of_scope: declined"],
    }


# --------------------------------------------------------------------------
# graph
# --------------------------------------------------------------------------

def build_qa_graph(
    embedder: Embedder,
    store: VectorStore,
    llm: LLMClient | None = None,
    search=None,
):
    g = StateGraph(QAState)

    g.add_node("router", node_router)
    g.add_node("retrieve", make_retrieve_node(embedder, store))
    g.add_node("grade_docs", node_grade)
    g.add_node("rewrite", make_rewrite_node(llm))
    g.add_node("web_search", make_web_search_node(search))
    g.add_node("generate", make_generate_node(llm))
    g.add_node("verify", node_verify)
    g.add_node("mark_regenerated", node_mark_regenerated)
    g.add_node("computation", node_computation)
    g.add_node("refuse", node_refuse)

    g.set_entry_point("router")
    g.add_conditional_edges(
        "router",
        route_from_router,
        {"law": "retrieve", "computation": "computation", "out_of_scope": "refuse"},
    )
    g.add_edge("retrieve", "grade_docs")

    g.add_conditional_edges(
    "grade_docs",
    route_from_grade,
    {"generate": "generate", "rewrite": "rewrite", "web_search": "web_search"},
    )
    g.add_edge("rewrite", "retrieve")        # self-correction cycle
    g.add_edge("web_search", "generate")
    g.add_edge("generate", "verify")
    g.add_conditional_edges(
        "verify",
        route_from_verify,
        {"done": END, "regenerate": "mark_regenerated"},
    )
    g.add_edge("mark_regenerated", "generate")   # bounded regeneration cycle
    g.add_edge("computation", END)
    g.add_edge("refuse", END)

    return g.compile()


def run_qa(
    question: str,
    embedder: Embedder,
    store: VectorStore,
    llm: LLMClient | None = None,
    search=None,
) -> QAState:
    graph = build_qa_graph(embedder, store, llm, search)
    return graph.invoke(
        {
            "question": question,
            "query": question,
            "documents": [],
            "rewrites": 0,
            "used_web": False,
            "citations": [],
            "grounded": False,
            "regenerated": False,
            "trace": [],
        }
    )
