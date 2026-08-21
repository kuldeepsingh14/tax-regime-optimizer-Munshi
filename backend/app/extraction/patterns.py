"""Deterministic extraction: PDF -> text -> fields via regex.

This is tried FIRST, before any LLM. Form 16 Part B has a semi-standard layout
mandated by Rule 31, so most employer templates yield to patterns. Regex is
cheaper, faster, and more reliable than an LLM when it works — the model is the
fallback for non-standard templates, not the default path.
"""

from __future__ import annotations

import io
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CANONICAL_FIELDS = (
    "pan",
    "employer_tan",
    "assessment_year",
    "gross_salary",
    "basic",
    "hra_received",
    "standard_deduction",
    "sec_80c",
    "sec_80d",
    "tds_deducted",
)


def pdf_to_text(data: bytes) -> str:
    """Extract text from a PDF. Returns empty string for scanned/image PDFs."""
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def parse_amount(raw: str) -> Decimal | None:
    """Parse Indian-format currency: '14,00,000.00' or 'Rs. 1,50,000'.

    Matches the numeric token rather than stripping non-digits, because
    stripping leaves the period from a 'Rs.' prefix behind and turns
    '150000' into '0.15'.
    """
    if not raw:
        return None

    match = re.search(r"\d+(?:\.\d+)?", raw.replace(",", ""))
    if not match:
        return None

    try:
        return Decimal(match.group(0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


# --------------------------------------------------------------------------
# document classification
# --------------------------------------------------------------------------

_DOC_SIGNATURES = {
    "form16": (r"FORM\s*NO\.?\s*16", r"Certificate under [Ss]ection 203", r"Part\s*B"),
    "ais": (r"Annual Information Statement", r"\bAIS\b"),
    "26as": (r"FORM\s*NO\.?\s*26AS", r"Annual Tax Statement"),
}


def classify_document(text: str) -> str:
    scores = {
        doc_type: sum(1 for p in patterns if re.search(p, text, re.I))
        for doc_type, patterns in _DOC_SIGNATURES.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


# --------------------------------------------------------------------------
# field patterns
# --------------------------------------------------------------------------

_AMOUNT = r"([\d,]+(?:\.\d{1,2})?)"

_FORM16_PATTERNS: dict[str, tuple[str, ...]] = {
    "pan": (r"PAN\s*(?:of|:)?\s*(?:the\s*)?(?:[Ee]mployee|[Dd]eductee)?\s*:?\s*([A-Z]{5}\d{4}[A-Z])",),
    "employer_tan": (r"TAN\s*(?:of\s*(?:the\s*)?[Dd]eductor)?\s*:?\s*([A-Z]{4}\d{5}[A-Z])",),
    "assessment_year": (r"Assessment\s*Year\s*:?\s*(\d{4}\s*-\s*\d{2,4})",),
    "gross_salary": (
        rf"Gross\s+[Ss]alary[^\d\n]*{_AMOUNT}",
        rf"Total\s+amount\s+of\s+salary[^\d\n]*{_AMOUNT}",
    ),
    "basic": (rf"Basic\s*(?:Salary|Pay)?[^\d\n]*{_AMOUNT}",),
    "hra_received": (
        rf"House\s+Rent\s+Allowance[^\d\n]*{_AMOUNT}",
        rf"\bHRA\b[^\d\n]*{_AMOUNT}",
    ),
    "standard_deduction": (rf"Standard\s+[Dd]eduction[^\d\n]*{_AMOUNT}",),
    "sec_80c": (
        rf"(?:[Ss]ection|u/s)\s*80\s*C\b[^\d\n]*{_AMOUNT}",
        rf"Deduction\s+in\s+respect\s+of\s+life\s+insurance[^\d\n]*{_AMOUNT}",
    ),
    "sec_80d": (rf"(?:[Ss]ection|u/s)\s*80\s*D\b[^\d\n]*{_AMOUNT}",),
    "tds_deducted": (
        rf"(?:Total\s+)?[Tt]ax\s+[Dd]educted(?:\s+at\s+[Ss]ource)?[^\d\n]*{_AMOUNT}",
        rf"\bTDS\b[^\d\n]*{_AMOUNT}",
    ),
}

_MONEY_FIELDS = frozenset(
    {
        "gross_salary",
        "basic",
        "hra_received",
        "standard_deduction",
        "sec_80c",
        "sec_80d",
        "tds_deducted",
    }
)


def extract_with_regex(text: str, doc_type: str = "form16") -> dict:
    """Best-effort deterministic extraction. Missing fields are simply absent."""
    if doc_type != "form16":
        return {}

    out: dict = {}
    for field, patterns in _FORM16_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            raw = match.group(1)
            value = parse_amount(raw) if field in _MONEY_FIELDS else raw.strip()
            if value is not None:
                out[field] = value
                break
    return out


def coverage(extracted: dict) -> float:
    """Fraction of canonical fields found. Drives the retry decision."""
    if not extracted:
        return 0.0
    return len([f for f in CANONICAL_FIELDS if f in extracted]) / len(CANONICAL_FIELDS)
