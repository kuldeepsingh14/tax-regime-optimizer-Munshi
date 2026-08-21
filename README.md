# Tax Regime Optimizer

Compares India's old and new income tax regimes to the rupee for assessment
year 2026-27, reads your Form 16 to fill in the figures, and answers questions
about the law with citations.

**Stack:** Angular 18 (Vercel) · FastAPI (Render) · LangGraph · Groq ·
FastEmbed · Pinecone

**Status:** 132 tests passing. Production build 67 kB. Runs with zero API keys.

---

## The one idea worth remembering

> **The LLM never touches the arithmetic. The rules engine never guesses.**

Everything else follows from that split.

| Layer | Nature | How correctness is checked |
|---|---|---|
| Extraction | fuzzy | field accuracy against labelled PDFs |
| Reconciliation | fuzzy | conflict-detection recall |
| **Computation** | **deterministic** | **exact rupee match, hand-computed** |
| Q&A | fuzzy | retrieval relevance and groundedness |

A tax figure has exactly one correct value. A system whose correctness can't be
asserted in a test suite isn't one you can ship. PDFs are messy, so extraction
is fuzzy — arithmetic isn't, so it isn't.

---

## Quickstart

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                    # 132 passed
uvicorn app.main:app --reload                # http://localhost:8000
```

**Frontend**

```bash
cd frontend
npm install
npm start                                    # http://localhost:4200
```

No API keys needed. Every external dependency degrades rather than fails.

---

## What's in here

```
backend/
  rules/ay_2026_27.json      tax law as data, one file per assessment year
  app/domain/models.py       frozen dataclasses, Decimal money
  app/engine/               slabs, HRA, rebate, surcharge, cess, breakeven
  app/extraction/           Graph A — Form 16 extraction state machine
  app/reconciliation/       Graph B — Form 16 vs AIS vs 26AS
  app/rag/                  Graph C — agentic RAG over the Act
  app/api/                  FastAPI routes, SSE streaming
  tests/                    132 tests, 0.8s, no network
  render.yaml               Render blueprint
  DEPLOY.md                 full deployment walkthrough

frontend/
  src/app/core/             API service (fetch + SSE), typed contracts
  src/app/components/       uploader, form, ledger, chat
  vercel.json               Vercel config

docs/
  01-system-design.md       HLD, LLD, graph topologies, interview defence
  02-deployment.md          same as backend/DEPLOY.md
```

---

## The three LangGraph graphs

**Graph A — Extraction.** `ingest → classify → extract → validate →` conditional
retry. Strategy escalates `regex → llm → llm_verbose` on validation failure,
bounded at 3 attempts, terminating in human review.

Regex-first isn't a shortcut: standard Form 16 templates complete with **zero
LLM calls**. The model is the fallback for non-standard employer layouts.

**Graph B — Reconciliation.** `align → detect → classify → merge`. Resolves
disagreements between Form 16, AIS and 26AS. Form 26AS wins for TDS — it's the
department's own record. Differences under ₹10 are rounding, not conflict.
Fields with no precedence rule are left **absent from the merged record, never
guessed**.

Most competing tools take Form 16 alone and silently miss income the user is
legally required to declare.

**Graph C — Q&A.** `router → retrieve → grade → generate → verify`, with two
cycles: rewrite-and-retry on poor retrieval (bounded at 2), and one
regeneration on an ungrounded answer. Web search is the fallback after rewrites
are exhausted.

**The router is the point.** "What is my tax on 14 lakh?" goes to the
deterministic engine. "What rebate applies above 12 lakh?" goes to retrieval.
The governing principle is enforced structurally at the entry point.

---

## Why LangGraph and not a chain

The extraction graph has a cycle: validation failure escalates strategy and
re-extracts, with a bounded attempt count and a terminal human-in-the-loop
path. Conditional edges on state, plus cycles, plus terminal branching, is a
state machine. A chain can't express it without hand-rolling the same
machinery, worse.

---

## Why the tests are fast

`Embedder`, `VectorStore` and `LLMClient` are Protocols. Production uses
FastEmbed, Pinecone and Groq; tests use `LexicalEmbedder`, `InMemoryStore` and
`ScriptedClient`.

That's why 132 tests run in 0.8 seconds with no network, no API key and no
model download — and why every branch, including both retry cycles, is
deterministically testable.

---

## Design decisions worth defending

**Decimal everywhere, never float.** Binary floating point can't represent
decimal fractions exactly. In money code that produces errors that compound and
break exact-match tests. Money crosses the API as a *string* so JavaScript's
float never touches a rupee figure either.

**Rules in versioned JSON.** Next Budget is a data change, not a code change.
One engine runs both regimes — there is no `if regime == "new"` anywhere in the
calculation logic. A test enforces that every numeric in config is a string.

**Stateless, no database.** Form 16 contains PAN and full salary. Not storing
it removes a class of risk rather than mitigating it.

**Extraction and computation are separate endpoints.** The user confirms
extracted values before anything is computed. Never compute silently on
machine-extracted numbers.

**FastEmbed, not sentence-transformers.** PyTorch is ~800 MB installed and
doesn't fit Render's 512 MB. FastEmbed runs comparable models via ONNX in
~50 MB. Measured footprint: 143 MB lexical, ~300 MB with FastEmbed.

**The strike-through.** In the results ledger, a deduction the old regime
grants and the new regime refuses still gets a row — struck through. Other
calculators show what you save; this shows what you give up.

---

## Bugs the test suite caught

Worth mentioning in interviews, because they're evidence the tests do real work
rather than decorating the repo:

- A hand-computed expected value was wrong: taxable ₹12,10,000 crosses into
  the 15% band, so tax is ₹61,500 not ₹61,000. The engine was right; the test
  author wasn't.
- `"Rs. 1,50,000"` parsed to zero — the period in "Rs." survived cleanup and
  became a decimal point.
- The Q&A router classified any question containing an amount as a
  calculation, so "marginal relief rebate 12 lakh" never reached retrieval.
- Angular's production build inlines `@import`ed Google Fonts at build time,
  making the build depend on a third-party CDN being reachable.
- FastEmbed burned 40 seconds retrying a failed model download before falling
  back — on a platform that sleeps when idle, that's 40s added to every cold
  start.

---

## Open verification items

Both are isolated to `backend/rules/ay_2026_27.json`, so correcting them is a
one-line data edit. That's the versioned-config design earning its keep.

1. **Standard deduction** (₹50,000 old / ₹75,000 new) is not stated in the
   source rate document. Encoded from s.16(ia) as understood. Verify before
   claiming exact correctness — it touches every computation.
2. **New-regime surcharge** is encoded as printed in the source document (37%
   above ₹5 crore). Widely-cited guidance caps 115BAC surcharge at 25%. Flagged
   rather than silently resolved.

---

## Deployment

See [docs/02-deployment.md](./docs/02-deployment.md). Order matters: backend
first, take the Render URL, set it in `frontend/src/environments/environment.prod.ts`,
deploy the frontend, then go back and set `ALLOWED_ORIGINS` on Render.

Skipping that last step is why people spend an hour debugging a backend that
works perfectly under `curl`.

---

## Honest framing

Regime calculators are a saturated market — the Income Tax Department ships
one, as do ClearTax, Groww and others, and Form 16 auto-extraction exists as a
product too. This isn't a novel category.

What's defensible is the engineering: the deterministic/agentic split with two
separate correctness criteria, the reconciliation layer most tools skip, and a
test suite that asserts exact rupee equality rather than "seems about right."
If asked "doesn't this already exist?", say yes, name the incumbents, and talk
about the architecture instead. A candidate who claims nothing like their
project existed is usually telling you they didn't look.
