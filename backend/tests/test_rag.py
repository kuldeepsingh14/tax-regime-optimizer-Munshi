"""Graph C tests.

Deterministic throughout: LexicalEmbedder needs no download, InMemoryStore
needs no network, ScriptedClient needs no API key. Every branch of the RAG
state machine is exercised reproducibly.
"""

import pytest

from app.extraction.llm import ScriptedClient
from app.rag.corpus import load_corpus
from app.rag.graph import (
    MAX_REWRITES,
    classify_route,
    node_verify,
    route_from_grade,
    route_from_verify,
    run_qa,
)
from app.rag.ingest import Document, chunk_document, ingest, split_into_sections, window
from app.rag.store import Chunk, InMemoryStore, LexicalEmbedder, ScoredChunk, cosine


@pytest.fixture(scope="module")
def index():
    docs = load_corpus()
    chunks = [c for d in docs for c in chunk_document(d)]
    embedder = LexicalEmbedder().fit([c.text for c in chunks])
    store = InMemoryStore()
    ingest(docs, embedder, store)
    return embedder, store


# --------------------------------------------------------------------------
# routing — the guardrail that keeps the LLM out of arithmetic
# --------------------------------------------------------------------------

class TestRouter:
    @pytest.mark.parametrize(
        "question",
        [
            "How much tax will I pay?",
            "what is my tax on 12 lakh",
            "calculate my liability",
            "which regime should I pick",
        ],
    )
    def test_computation_questions_never_reach_retrieval(self, question):
        assert classify_route(question) == "computation"

    @pytest.mark.parametrize(
        "question",
        [
            "What is the 80C limit?",
            "marginal relief rebate 12 lakh",
            "surcharge threshold 50 lakh",
            "Can I claim HRA and home loan interest together?",
            "is employer NPS allowed in the new regime",
        ],
    )
    def test_law_questions_route_to_retrieval(self, question):
        assert classify_route(question) == "law"

    @pytest.mark.parametrize(
        "question",
        ["What is the capital of France?", "write me a poem", "who won the match"],
    )
    def test_unrelated_questions_declined(self, question):
        assert classify_route(question) == "out_of_scope"

    def test_amount_alone_is_not_a_computation_signal(self):
        """'12 lakh' in a question about the law must not hijack the route.

        The question needs tax vocabulary to be in scope at all; the point
        here is that the amount does not override it into 'computation'.
        """
        assert classify_route("what rebate applies above 12 lakh") == "law"
        assert classify_route("does surcharge start at 50 lakh") == "law"

    def test_computation_route_points_at_the_calculator(self, index):
        embedder, store = index
        result = run_qa("How much tax will I pay?", embedder, store)
        assert result["route"] == "computation"
        assert "calculator" in result["answer"].lower()
        assert result["documents"] == []


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------

class TestChunking:
    def test_splits_on_section_boundaries(self):
        text = "80C. First provision.\nDetail.\n80D. Second provision.\nMore."
        sections = split_into_sections(text)
        labels = [label for label, _ in sections]
        assert "80C" in labels and "80D" in labels

    def test_unlabelled_text_becomes_one_block(self):
        sections = split_into_sections("Just some prose with no section marker.")
        assert len(sections) == 1

    def test_short_text_is_not_split(self):
        assert len(window("short text")) == 1

    def test_long_text_is_split_with_overlap(self):
        pieces = window("word. " * 800)
        assert len(pieces) > 1

    def test_continuation_chunks_carry_the_heading(self):
        doc = Document(
            title="Long section",
            source="act/test",
            text="80X. Heading line here.\n" + ("Body sentence. " * 400),
        )
        chunks = chunk_document(doc)
        assert len(chunks) > 1
        assert "80X" in chunks[1].text

    def test_metadata_survives_chunking(self):
        chunks = chunk_document(
            Document(title="T", source="act/80C", text="80C. Body.")
        )
        assert all(c.metadata["source"] == "act/80C" for c in chunks)


# --------------------------------------------------------------------------
# embedding and store
# --------------------------------------------------------------------------

class TestRetrievalInfra:
    def test_embedding_is_deterministic(self):
        e = LexicalEmbedder().fit(["alpha beta", "gamma delta"])
        assert e.embed(["alpha beta"]) == e.embed(["alpha beta"])

    def test_embeddings_are_normalised(self):
        e = LexicalEmbedder().fit(["alpha beta gamma"])
        vec = e.embed(["alpha beta"])[0]
        assert abs(sum(v * v for v in vec) ** 0.5 - 1.0) < 1e-6

    def test_overlapping_text_scores_higher(self):
        e = LexicalEmbedder().fit(["deduction section limit", "unrelated words here"])
        a, b, c = e.embed(["deduction limit", "deduction section", "unrelated words"])
        assert cosine(a, b) > cosine(a, c)

    def test_store_returns_top_k_in_order(self):
        e = LexicalEmbedder().fit(["alpha", "beta", "gamma"])
        store = InMemoryStore()
        chunks = [Chunk(id=str(i), text=t) for i, t in enumerate(["alpha", "beta", "gamma"])]
        store.upsert(chunks, e.embed([c.text for c in chunks]))

        results = store.query(e.embed(["alpha"])[0], top_k=2)
        assert len(results) == 2
        assert results[0].score >= results[1].score
        assert results[0].chunk.text == "alpha"

    def test_upsert_is_idempotent(self):
        e = LexicalEmbedder().fit(["alpha"])
        store = InMemoryStore()
        chunk = [Chunk(id="same", text="alpha")]
        store.upsert(chunk, e.embed(["alpha"]))
        store.upsert(chunk, e.embed(["alpha"]))
        assert len(store) == 1


# --------------------------------------------------------------------------
# grading and self-correction
# --------------------------------------------------------------------------

class TestSelfCorrection:
    def test_relevant_grade_goes_straight_to_generate(self):
        assert route_from_grade({"grade": "relevant", "rewrites": 0}) == "generate"

    def test_irrelevant_grade_triggers_rewrite(self):
        assert route_from_grade({"grade": "irrelevant", "rewrites": 0}) == "rewrite"

    def test_rewrites_are_bounded_then_fall_back_to_web(self):
        state = {"grade": "irrelevant", "rewrites": MAX_REWRITES}
        assert route_from_grade(state) == "web_search"

    def test_rewrite_cycle_appears_in_trace(self, index):
        embedder, store = index
        result = run_qa("qwerty asdf zxcv deduction", embedder, store)
        trace = " ".join(result["trace"])
        # Nonsense terms with one tax word: retrieval is weak, so the graph
        # must attempt correction rather than answering from noise.
        assert "grade:" in trace

    def test_web_fallback_supplies_documents(self, index):
        embedder, store = index

        def fake_search(query):
            return [
                {
                    "url": "https://example.gov/circular-1",
                    "title": "Circular 1",
                    "snippet": "Recent amendment text not present in the corpus.",
                }
            ]

        from app.rag.graph import make_web_search_node

        node = make_web_search_node(fake_search)
        out = node({"query": "anything", "documents": []})
        assert out["used_web"] is True
        assert out["documents"][0].chunk.metadata["source"].startswith("https://")

    def test_web_search_absent_degrades_gracefully(self):
        from app.rag.graph import make_web_search_node

        node = make_web_search_node(None)
        out = node({"query": "anything", "documents": []})
        assert out["used_web"] is False


# --------------------------------------------------------------------------
# groundedness verification
# --------------------------------------------------------------------------

class TestVerification:
    def test_answer_with_citation_is_grounded(self):
        out = node_verify({"answer": "The limit is 1,50,000 [80C].", "citations": ["80C"]})
        assert out["grounded"] is True

    def test_answer_without_citation_is_ungrounded(self):
        out = node_verify(
            {"answer": "The limit is definitely 1,50,000.", "citations": ["80C"]}
        )
        assert out["grounded"] is False

    def test_honest_refusal_counts_as_grounded(self):
        """Declining to answer is correct behaviour, not a failure to cite."""
        out = node_verify(
            {"answer": "The excerpts do not answer that.", "citations": ["80C"]}
        )
        assert out["grounded"] is True

    def test_empty_answer_is_ungrounded(self):
        assert node_verify({"answer": "", "citations": []})["grounded"] is False

    def test_regeneration_happens_at_most_once(self):
        assert route_from_verify({"grounded": False, "regenerated": True}) == "done"
        assert route_from_verify({"grounded": False, "regenerated": False}) == "regenerate"


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------

class TestQAEndToEnd:
    def test_retrieves_the_correct_section(self, index):
        embedder, store = index
        result = run_qa("80C investment limit", embedder, store)
        assert result["documents"][0].chunk.metadata["section"] == "80C"

    def test_finds_rebate_provision(self, index):
        embedder, store = index
        result = run_qa("marginal relief rebate 12 lakh", embedder, store)
        titles = [d.chunk.metadata["title"] for d in result["documents"]]
        assert any("87A" in t for t in titles)

    def test_out_of_scope_short_circuits(self, index):
        embedder, store = index
        result = run_qa("What is the capital of France?", embedder, store)
        assert result["route"] == "out_of_scope"
        assert result["documents"] == []
        assert "income tax" in result["answer"].lower()

    def test_llm_answer_is_used_when_available(self, index):
        embedder, store = index
        llm = ScriptedClient(["The ceiling is Rs 1,50,000 per year [80C]."])
        result = run_qa("80C investment limit", embedder, store, llm=llm)
        assert "1,50,000" in result["answer"]
        assert result["grounded"] is True

    def test_degrades_without_an_llm(self, index):
        """No API key must not mean no answer — the excerpt is still useful."""
        embedder, store = index
        result = run_qa("80C investment limit", embedder, store, llm=None)
        assert result["answer"]
        assert result["citations"]

    def test_never_crashes_on_empty_retrieval(self):
        """An empty index must degrade, not raise."""
        embedder = LexicalEmbedder().fit(["placeholder"])
        result = run_qa("80C deduction limit", embedder, InMemoryStore())
        assert result["answer"]
