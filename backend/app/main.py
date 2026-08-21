"""FastAPI application.

Stateless by design. No database, no session, no persistence. Form 16 contains
PAN and full salary detail; not storing it removes an entire class of risk.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.extract_routes import router as extract_router
from app.api.qa_routes import router as qa_router
from app.api.schemas import ComparisonOut, ComputeRequest
from app.engine.calculator import compare
from app.engine.rules import RULES_DIR, load_rules

def _load_dotenv() -> None:
    """Nothing else reads .env — not uvicorn, not os.getenv. Without this a
    GROQ_API_KEY in .env is invisible and the app silently runs degraded.
    Real env vars (what Render sets) always win over the file."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("taxopt")

app = FastAPI(
    title="Tax Regime Optimizer",
    version="0.1.0",
    description="Deterministic old vs new regime comparison for Indian income tax.",
)

def _cors_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:4200")
    return [o.strip() for o in raw.split(",") if o.strip()]


# Vercel gives every preview deployment its own hostname
# (project-git-branch-user.vercel.app), so a static allowlist would only ever
# cover production. The regex covers previews; ALLOWED_ORIGINS covers the
# production domain. Both are needed.
_PREVIEW_ORIGIN_RE = os.getenv(
    "ALLOWED_ORIGIN_REGEX", r"https://.*\.vercel\.app"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_PREVIEW_ORIGIN_RE,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(extract_router)
app.include_router(qa_router)


@app.get("/health")
def health() -> dict:
    """Also serves as the Render keep-warm probe."""
    return {"status": "ok"}


@app.get("/api/v1/rules")
def list_rules() -> dict:
    years = sorted(
        p.stem.replace("ay_", "").replace("_", "-") for p in RULES_DIR.glob("ay_*.json")
    )
    return {"assessment_years": years}


@app.get("/api/v1/rules/{assessment_year}")
def get_rules(assessment_year: str) -> dict:
    """Expose the rules config. Transparency: the user can see exactly which
    slabs and limits produced their number."""
    try:
        r = load_rules(assessment_year)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "assessment_year": r.assessment_year,
        "financial_year": r.financial_year,
        "cess_rate": str(r.cess_rate),
        "regimes": {
            key: {
                "name": reg.name,
                "section": reg.section,
                "standard_deduction": str(reg.standard_deduction),
                "allowed_deductions": sorted(reg.allowed_deductions),
                "rebate_87a": {
                    "income_limit": str(reg.rebate_87a.income_limit),
                    "max_rebate": str(reg.rebate_87a.max_rebate),
                    "marginal_relief": reg.rebate_87a.marginal_relief,
                },
            }
            for key, reg in (("old", r.old), ("new", r.new))
        },
    }


@app.post("/api/v1/compute", response_model=ComparisonOut)
def compute(req: ComputeRequest) -> ComparisonOut:
    """Compute both regimes. Deterministic — no LLM in this path."""
    try:
        result = compare(req.to_domain(), req.assessment_year)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info(
        "computed ay=%s recommended=%s", req.assessment_year, result.recommended.value
    )
    return ComparisonOut.from_domain(result)
