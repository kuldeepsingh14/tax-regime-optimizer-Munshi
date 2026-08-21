# Tax Regime Optimizer — Backend (Phase 2)

Deterministic old vs new regime comparison for Indian income tax, AY 2026-27.

## Governing principle

**The LLM never touches the arithmetic.** This phase contains zero AI. The
agentic layer (Phase 3+) handles document extraction and reconciliation only.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q
```

## Layout

```
rules/ay_2026_27.json   tax law as data, one file per assessment year
app/domain/models.py    frozen dataclasses, Decimal money
app/engine/rules.py     config loader, JSON strings -> Decimal
app/engine/calculator.py  slabs, HRA, rebate, surcharge, cess
app/engine/breakeven.py   binary-search crossover solver
app/api/schemas.py      pydantic boundary, money serialised as strings
app/main.py             FastAPI
tests/test_engine.py    42 exact-match tests
```

## Design decisions

**One engine, both regimes.** There is no `if regime == "new"` in the
calculation logic. Slabs, standard deduction, allowed deductions and rebate
rules all come from config. A third regime needs no code change.

**Decimal everywhere, never float.** Binary floating point can't represent
decimal fractions exactly. In money code that produces errors that compound
and break exact-match tests.

**Rules in versioned JSON.** Next Budget is a data change. The test
`test_no_floats_anywhere_in_config` enforces that every numeric in config is
a string.

**Stateless.** No database. Form 16 contains PAN and salary; not storing it
removes a class of risk rather than mitigating it.

## AY 2026-27 rates (source: Income Tax Dept, as amended by Finance Act 2026)

Old regime: nil to 2.5L / 5% to 5L / 20% to 10L / 30% above.
Senior 3L threshold, super senior 5L. Rebate 87A: 12,500 up to 5L, no
marginal relief.

New regime 115BAC(1A): nil to 4L / 5% to 8L / 10% to 12L / 15% to 16L /
20% to 20L / 25% to 24L / 30% above. Rebate 87A: 60,000 up to 12L, **with**
marginal relief.

Surcharge both regimes: 10% / 15% / 25% / 37% at 50L / 1Cr / 2Cr / 5Cr,
with marginal relief. Cess 4%.

## Open verification items

1. **Standard deduction** (50,000 old / 75,000 new) is not stated in the
   source rate document. Encoded from s.16(ia) as understood. Verify against
   the Finance Act before claiming exact correctness.
2. **New regime surcharge** is encoded as printed in the source (37% above
   5Cr). Widely-cited guidance caps 115BAC surcharge at 25%. Flagged.

Both are isolated to `rules/ay_2026_27.json` — correcting them is a one-line
data edit, not a code change. That is the point of the design.

---

## Phase 3 — Extraction & Reconciliation (LangGraph)

**Graph A** (`app/extraction/graph.py`): ingest → classify → extract →
validate → conditional retry. Strategy escalates regex → llm → llm_verbose on
validation failure, bounded at 3 attempts, terminating in human review.

Regex-first is not a shortcut: standard Form 16 templates complete with **zero
LLM calls**. The model is the fallback for non-standard employer layouts.

**Graph B** (`app/reconciliation/graph.py`): align → detect → classify → merge.
Resolves conflicts between Form 16, AIS and 26AS. 26AS wins for TDS (it is the
department's own record). Differences under Rs 10 are rounding, not conflict.
Fields with no precedence rule are left **absent from the merged record, never
guessed** — the user decides.

## Phase 4 — Agentic RAG (LangGraph)

**Graph C** (`app/rag/graph.py`): router → retrieve → grade → generate →
verify, with two cycles: rewrite-and-retry on poor retrieval (bounded at 2),
and one regeneration on an ungrounded answer. Web search is the fallback after
rewrites are exhausted.

**The router is the point.** "What is my tax on 14 lakh?" routes to the
deterministic engine, not to retrieval. The governing principle is enforced at
the entry point.

## Dependency injection

`Embedder`, `VectorStore` and `LLMClient` are Protocols. Production uses
FastEmbed, Pinecone and Groq; tests use `LexicalEmbedder`, `InMemoryStore` and
`ScriptedClient`. This is why 132 tests run in under a second with no network,
no API key and no model download — and why every branch, including the retry
cycles, is deterministically testable.

Every layer degrades rather than fails: no Groq key falls back to regex-only
extraction; no Pinecone falls back to in-memory; no FastEmbed falls back to
lexical retrieval.

## Environment

```
GROQ_API_KEY=...        # optional — extraction degrades to regex-only
PINECONE_API_KEY=...    # optional — falls back to in-memory store
ALLOWED_ORIGINS=https://your-app.vercel.app
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/extract` | Upload Form 16 / AIS / 26AS → fields + conflicts |
| POST | `/api/v1/compute` | Confirmed inputs → both regimes + breakeven |
| POST | `/api/v1/ask` | Tax-law question → SSE token stream |
| GET | `/api/v1/rules/{ay}` | Rules config for an assessment year |
| GET | `/api/v1/index/status` | Which embedder and store are active |
| GET | `/health` | Render keep-warm probe |

---

## Phase 6 — Deployment

See [DEPLOY.md](./DEPLOY.md) for the full walkthrough. Summary:

| | |
|---|---|
| Backend | Render free tier, Singapore, 1 worker, `render.yaml` committed |
| Frontend | Vercel, output `dist/taxopt-web/browser` |
| Health | `GET /health` — also the Render health check |
| Cold start | ~50s after 15min idle; surfaced honestly in the UI |

### Measured memory (against Render's 512 MB)

| Stage | Resident |
|---|---|
| Interpreter | 12 MB |
| + FastAPI, Pydantic | 48 MB |
| + LangGraph | 82 MB |
| + pdfplumber | 91 MB |
| + index (lexical) | 143 MB |
| + index (FastEmbed) | ~300 MB |

`sentence-transformers` is deliberately absent: PyTorch is ~800 MB installed
and does not fit. FastEmbed runs comparable models via ONNX in ~50 MB.

### Configuration

| Variable | Default | Effect if unset |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:4200` | Browser requests blocked by CORS |
| `ALLOWED_ORIGIN_REGEX` | `https://.*\.vercel\.app` | Vercel previews blocked |
| `EMBEDDER` | `auto` | — |
| `GROQ_API_KEY` | — | Extraction is regex-only |
| `PINECONE_API_KEY` | — | Corpus served from memory |

`EMBEDDER=lexical` starts in ~1s. `auto` attempts FastEmbed and falls back —
but a failed model download costs ~40s of backoff, which is why the model is
cached at build time and why this is an explicit setting rather than a bare
try/except.
