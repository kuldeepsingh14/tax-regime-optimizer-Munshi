# Tax Regime Optimizer — Phase 1: System Design

**Project:** Agentic tax document processing + deterministic regime comparison
**Stack:** Angular (Vercel) · FastAPI (Render) · LangChain + LangGraph · Pinecone · Groq (Llama-3) · HuggingFace embeddings

---

## 1. The Governing Principle

Everything in this architecture follows from one rule:

> **The LLM never touches the arithmetic. The rules engine never guesses.**

This split is the spine of the design and the answer to most interview questions.

| Layer | Nature | Technology | Correctness criterion |
|---|---|---|---|
| Extraction | Fuzzy | LangGraph + Groq | Field-level accuracy vs labelled PDFs |
| Reconciliation | Fuzzy | LangGraph + Groq | Conflict detection recall |
| **Computation** | **Deterministic** | **Pure Python** | **Exact match vs hand-computed** |
| Q&A | Fuzzy | LangGraph + Pinecone RAG | Retrieval relevance + groundedness |

If an interviewer asks *"why not let the LLM compute the tax?"* — the answer is that a tax figure has exactly one correct value, and a system whose correctness cannot be asserted in a test suite is not a system you can ship. Extraction is fuzzy because PDFs are fuzzy. Arithmetic is not.

---

## 2. High-Level Design

### 2.1 Component View

```
┌─────────────────────────────────────────────────────┐
│  Angular SPA (Vercel)                               │
│  Upload · Gap-fill form · Results · Q&A chat        │
└────────────────────┬────────────────────────────────┘
                     │ HTTPS / JSON + SSE
┌────────────────────▼────────────────────────────────┐
│  FastAPI (Render)                                   │
│  ┌───────────────────────────────────────────────┐  │
│  │  AGENTIC LAYER (LangGraph)                    │  │
│  │   Graph A: Extraction                         │  │
│  │   Graph B: Reconciliation                     │  │
│  │   Graph C: Tax Q&A (Agentic RAG)              │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │  DETERMINISTIC LAYER (pure Python)            │  │
│  │   Rules engine · Old/New computation          │  │
│  │   Breakeven solver                            │  │
│  └───────────────────────────────────────────────┘  │
└───────┬─────────────────────┬───────────────────────┘
        │                     │
   ┌────▼─────┐         ┌─────▼──────┐
   │  Groq    │         │  Pinecone  │
   │ Llama-3  │         │ Act corpus │
   └──────────┘         └────────────┘
```

### 2.2 Request Flow

1. User uploads Form 16 (optionally AIS / 26AS)
2. **Graph A** classifies, extracts, validates, retries, escalates
3. **Graph B** reconciles multi-document conflicts, flags disputes
4. Angular renders a gap-fill form pre-populated with extracted values
5. User confirms/corrects → submits
6. **Deterministic engine** computes both regimes + breakeven
7. Results render; **Graph C** answers follow-up questions via RAG

### 2.3 Statelessness

No database. Form 16 contains PAN and full salary detail. Documents are processed in-memory and discarded after response.

- **Privacy:** nothing to leak
- **Compliance:** no data retention obligations
- **Ops:** horizontally scalable, no migrations
- **Trade-off:** no history across sessions. Acceptable — and defensible as a deliberate choice, not an omission.

Pinecone stores only the Income Tax Act corpus. Never user data.

---

## 3. Low-Level Design — Deterministic Engine

### 3.1 Versioned Rules Configuration

**Rules live in data, not code.** One config per assessment year.

```
/rules
  ay_2026_27.json
  ay_2027_28.json
```

Shape:

```json
{
  "assessment_year": "2026-27",
  "regimes": {
    "old": {
      "slabs": [ { "upto": 250000, "rate": 0.0 }, ... ],
      "standard_deduction": 50000,
      "allowed_deductions": ["80C", "80D", "HRA", "24B", "80CCD1B", "80CCD2"],
      "caps": { "80C": 150000, "80CCD1B": 50000 }
    },
    "new": {
      "slabs": [ ... ],
      "standard_deduction": 75000,
      "allowed_deductions": ["80CCD2"],
      "rebate": { "section": "87A", "income_limit": ..., "max_rebate": ... }
    }
  },
  "surcharge": [ { "above": 5000000, "rate": 0.10 }, ... ],
  "cess": 0.04,
  "marginal_relief": true
}
```

**Why this matters in interviews:** next year's Budget becomes a data change, not a code change. You can compute a user's liability across multiple years for comparison. And the engine is testable independent of any specific year's numbers.

> ⚠️ Slab values, rebate thresholds, and standard deduction above are **placeholders**. These are verified against the current Finance Act at the start of Phase 2 — they have moved recently and encoding them from memory would poison every test case.

### 3.2 Domain Model

```python
@dataclass(frozen=True)
class SalaryInput:
    gross_salary: Decimal
    basic: Decimal
    hra_received: Decimal
    rent_paid: Decimal
    is_metro: bool

@dataclass(frozen=True)
class Deductions:
    sec_80c: Decimal
    sec_80d_self: Decimal
    sec_80d_parents: Decimal
    parents_are_senior: bool
    home_loan_interest: Decimal
    nps_self_80ccd1b: Decimal
    nps_employer_80ccd2: Decimal

@dataclass(frozen=True)
class OtherIncome:
    savings_interest: Decimal
    fd_interest: Decimal

@dataclass(frozen=True)
class TaxLine:          # one row of the computation trail
    label: str
    amount: Decimal
    section: str | None

@dataclass(frozen=True)
class RegimeResult:
    regime: str
    lines: list[TaxLine]     # full audit trail, not just a total
    taxable_income: Decimal
    tax_before_rebate: Decimal
    rebate: Decimal
    surcharge: Decimal
    cess: Decimal
    total_tax: Decimal

@dataclass(frozen=True)
class ComparisonResult:
    old: RegimeResult
    new: RegimeResult
    recommended: str
    saving: Decimal
    breakeven_deductions: Decimal
```

**`Decimal` everywhere, never `float`.** Money in binary floating point produces rounding errors that break exact-match tests. Naming this unprompted in an interview signals you've handled financial code before.

**Frozen dataclasses** — inputs are immutable, so no computation can mutate them and silently affect a later one.

### 3.3 Computation Pipeline

Each step is a pure function returning a new `TaxLine`, so the full trail is assembled by construction rather than reconstructed for display:

```
gross
  → apply standard deduction
  → apply exemptions (HRA — old only)
  → apply Chapter VI-A deductions (filtered by regime's allowed list, capped)
  → taxable income
  → apply slabs progressively
  → apply rebate (87A)
  → apply surcharge (with marginal relief)
  → apply cess
  → total
```

Regime differences are expressed entirely through config (`allowed_deductions`, `slabs`, `rebate`), so **one engine runs both regimes**. No branching on regime name inside the calculation logic. This is the single most important design decision in the deterministic layer.

### 3.4 Breakeven Solver

The most useful output: *"old regime only wins if deductions exceed ₹X; you're at ₹Y."*

Tax under both regimes is monotonic in total deductions, so binary search over deduction total finds the crossover point in ~20 iterations. Deterministic, fast, exactly testable.

### 3.5 Test Strategy

| Layer | Method | Assertion |
|---|---|---|
| Slab application | Table-driven, hand-computed | Exact rupee match |
| HRA exemption | All three statutory limbs | Minimum correctly chosen |
| Rebate boundary | Values at threshold ±1 | Cliff behaves correctly |
| Surcharge | Marginal relief cases | Relief applied |
| Breakeven | Cross-check by brute force | Solver matches scan |
| End-to-end | ~50 full profiles | Exact match |

Target: **exact match on every case.** Not "close enough." That claim is what makes this project defensible.

---

## 4. Low-Level Design — Agentic Layer

### Graph A: Document Extraction

**State:**

```python
class ExtractionState(TypedDict):
    raw_bytes: bytes
    text: str
    doc_type: Literal["form16", "ais", "26as", "unknown"]
    extracted: dict
    validation_errors: list[str]
    strategy: Literal["regex", "llm", "llm_verbose"]
    attempts: int
    needs_human: bool
```

**Nodes and edges:**

```
        ┌──────────┐
        │  ingest  │   pdfplumber → text
        └────┬─────┘
             ▼
        ┌──────────┐
        │ classify │   which document is this?
        └────┬─────┘
             ▼
     ┌───────────────┐
     │ route_extract │  ─── conditional edge on doc_type
     └───┬───┬───┬───┘
         ▼   ▼   ▼
      form16 ais 26as     strategy-specific extractors
         └───┬───┘
             ▼
        ┌──────────┐
        │ validate │   components sum to gross? PAN format? TDS ≤ tax?
        └────┬─────┘
             ▼
     ┌────────────────┐
     │ conditional:   │
     │  valid    → END│
     │  fail & attempts<2 → escalate_strategy → re-extract
     │  fail & attempts≥2 → human_in_loop → END
     └────────────────┘
```

**Why LangGraph and not a chain:** the retry edge is *conditional on validation output* and *changes strategy on retry* (regex → LLM → LLM with verbose prompt). There's a cycle, a branch on state, and a terminal escalation path. That is a state machine, not a pipeline. This is the honest justification for the framework.

**Extraction strategy — regex first, LLM second.** Form 16 Part B has a semi-standard layout. Deterministic parsing is cheaper, faster, and more reliable when it works; the LLM is the fallback for non-standard employer templates. Cost and latency both improve, and it's a better engineering answer than "LLM everything."

### Graph B: Multi-Document Reconciliation

Runs only when more than one document is supplied.

**State:**

```python
class ReconciliationState(TypedDict):
    documents: dict[str, dict]      # doc_type → extracted fields
    merged: dict
    conflicts: list[Conflict]
    resolutions: list[Resolution]
    needs_user_confirmation: list[str]
```

**Nodes:**

```
align_fields      map differing field names across doc types to canonical keys
      ▼
detect_conflicts  same canonical field, different values across sources
      ▼
classify_conflict ─┬─ tolerance (rounding) → auto-resolve
                   ├─ known precedence (26AS authoritative for TDS) → auto-resolve
                   └─ genuine disagreement → flag for user
      ▼
merge             confidence-weighted merge
      ▼
END
```

This is the layer most competing tools skip — they take Form 16 alone. Real users have income in AIS that never appears in Form 16 (savings interest, dividends), and TDS figures that disagree between employer and department records.

### Graph C: Tax Q&A — Agentic RAG

The original Agentic RAG design, now solving a real problem.

**Corpus:** Income Tax Act sections, CBDT circulars, relevant rules → chunked → HuggingFace embeddings → Pinecone.

**State:**

```python
class QAState(TypedDict):
    question: str
    query: str
    documents: list[Document]
    grade: Literal["relevant", "irrelevant"]
    rewrites: int
    used_web: bool
    answer: str
    citations: list[str]
```

**Topology:**

```
      ┌────────┐
      │ router │  tax-law question? computation question? out of scope?
      └───┬────┘
          ▼
     ┌─────────┐
     │ retrieve│  Pinecone top-k
     └────┬────┘
          ▼
     ┌─────────┐
     │  grade  │  are these documents actually relevant?
     └────┬────┘
          ▼
   ┌──────────────────┐
   │ conditional:     │
   │  relevant  → generate
   │  irrelevant & rewrites<2 → rewrite_query → retrieve
   │  irrelevant & rewrites≥2 → web_search → generate
   └──────────────────┘
          ▼
     ┌─────────┐
     │ generate│  answer grounded in retrieved sections
     └────┬────┘
          ▼
     ┌─────────┐
     │ verify  │  is every claim supported by a citation?
     └────┬────┘
          └── unsupported → regenerate (max 1) → END
```

**Router matters:** computation questions ("what's my tax on 14L?") route to the deterministic engine, *not* to RAG. The router enforces the governing principle at the entry point. Say this in interviews.

---

## 5. API Surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/extract` | Upload documents → Graph A (+ B) → structured fields + conflicts |
| `POST` | `/api/v1/compute` | Confirmed inputs → deterministic engine → `ComparisonResult` |
| `POST` | `/api/v1/ask` | Question → Graph C → SSE token stream |
| `GET` | `/api/v1/rules/{ay}` | Rules config for a year (transparency + frontend validation) |
| `GET` | `/health` | Render keep-warm probe |

Extraction and computation are **separate endpoints** — the user must confirm extracted values before anything is computed. Never compute silently on machine-extracted numbers. That's both correct product design and a good answer to "how do you handle extraction errors?"

---

## 6. Deployment Constraints (designed for now, executed in Phase 5)

| Constraint | Impact | Mitigation |
|---|---|---|
| Render free tier: 512 MB RAM | PyTorch (~800 MB) will not fit | **FastEmbed** (ONNX, ~50 MB, same MiniLM weights) |
| Render spins down after ~15 min idle | ~50 s cold start on demo | `/health` warmer + honest loading state in UI |
| Pinecone free tier | One index, limited namespaces | Single index; corpus only, no user data |
| Groq rate limits | Burst failures | Exponential backoff + regex-first extraction reduces call volume |

The FastEmbed decision is the most important one here and should be made in Phase 2, not discovered at deployment.

---

## 7. Interview Defense — Question Bank

**"Why an LLM at all if the tax logic is deterministic?"**
The LLM solves document parsing — employer Form 16 templates vary and PDF text extraction is messy. It never computes. Two separable subsystems with two different correctness criteria and two different test strategies.

**"Why LangGraph instead of a plain function chain?"**
The extraction graph has a cycle: validation failure escalates strategy and re-extracts, with a bounded attempt count and a terminal human-in-the-loop path. Conditional edges on state plus cycles plus terminal branching is a state machine. A chain can't express it without hand-rolling the same thing worse.

**"How do you know the tax numbers are right?"**
Exact-match test suite against hand-computed cases, including boundary cases at the rebate cliff and surcharge thresholds. Not statistical confidence — exact rupee equality.

**"What happens when the Budget changes the slabs?"**
Add a JSON config for the new assessment year. No code change. The engine is year-agnostic.

**"Why no database?"**
Form 16 contains PAN and full salary. Not storing it removes an entire class of risk and compliance burden. The trade-off is no cross-session history, which I accepted deliberately.

**"This already exists — ClearTax, Tax CoPilot."**
Yes. The base comparison is commodity. What I built differently is the reconciliation layer — most tools take Form 16 alone, but real users have AIS and 26AS with conflicting figures, and resolving those is genuinely non-trivial. And architecturally, I kept the LLM strictly out of the computation path, which is the decision I'd defend hardest.

**"Why `Decimal` and not `float`?"**
Binary floating point can't represent decimal fractions exactly. In money code that produces off-by-a-paisa errors that break exact-match tests and compound across operations.

**"What's the weakest part?"**
Extraction on non-standard employer templates. Mitigated by regex-first with LLM fallback and a mandatory user-confirmation step, but it's the component with the lowest ceiling on reliability — which is exactly why the architecture never lets it feed computation without human confirmation.

---

## 8. Build Order

| Phase | Deliverable | Verification checkpoint |
|---|---|---|
| **2** | FastAPI scaffold, rules config (verified slabs), deterministic engine, test suite | `pytest` green on all hand-computed cases |
| **3** | Graph A extraction, Graph B reconciliation | Upload a real Form 16 → correct fields extracted |
| **4** | Graph C Agentic RAG, Pinecone ingestion | Ask a tax question → grounded, cited answer |
| **5** | Angular UI, SSE streaming | Full flow works locally end to end |
| **6** | Render + Vercel deployment | Public URL, cold start handled |

Phase 2 starts with verifying the current Finance Act numbers by search — not from memory.
