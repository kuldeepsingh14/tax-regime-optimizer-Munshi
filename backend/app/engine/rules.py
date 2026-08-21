"""Rules loader.

Tax law lives in versioned JSON, never in code. A Budget change is a data
change: drop in a new assessment-year file and the engine works unchanged.

All numeric values are stored as strings in JSON and parsed to Decimal here,
so no float ever enters the system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


@dataclass(frozen=True)
class Slab:
    upto: Decimal | None   # None means "and above"
    rate: Decimal


@dataclass(frozen=True)
class SurchargeBand:
    above: Decimal
    rate: Decimal


@dataclass(frozen=True)
class Rebate87A:
    income_limit: Decimal
    max_rebate: Decimal
    marginal_relief: bool


@dataclass(frozen=True)
class RegimeRules:
    key: str
    name: str
    section: str
    standard_deduction: Decimal
    slabs: dict[str, tuple[Slab, ...]]
    allowed_deductions: frozenset[str]
    caps: dict[str, Decimal]
    rebate_87a: Rebate87A
    surcharge: tuple[SurchargeBand, ...]

    def slabs_for(self, age_category: str) -> tuple[Slab, ...]:
        # New regime has no age-based variation; fall back to default.
        return self.slabs.get(age_category) or self.slabs["default"]

    def allows(self, deduction_key: str) -> bool:
        return deduction_key in self.allowed_deductions

    def cap(self, key: str) -> Decimal | None:
        return self.caps.get(key)


@dataclass(frozen=True)
class HraRules:
    metro_percent: Decimal
    non_metro_percent: Decimal
    rent_minus_basic_percent: Decimal


@dataclass(frozen=True)
class TaxRules:
    assessment_year: str
    financial_year: str
    cess_rate: Decimal
    old: RegimeRules
    new: RegimeRules
    hra: HraRules

    def regime(self, key: str) -> RegimeRules:
        return self.old if key == "old" else self.new


def _d(value: str) -> Decimal:
    return Decimal(value)


def _parse_slabs(raw: dict) -> dict[str, tuple[Slab, ...]]:
    return {
        category: tuple(
            Slab(
                upto=_d(s["upto"]) if s["upto"] is not None else None,
                rate=_d(s["rate"]),
            )
            for s in slab_list
        )
        for category, slab_list in raw.items()
    }


def _parse_regime(key: str, raw: dict) -> RegimeRules:
    return RegimeRules(
        key=key,
        name=raw["name"],
        section=raw["section"],
        standard_deduction=_d(raw["standard_deduction"]),
        slabs=_parse_slabs(raw["slabs"]),
        allowed_deductions=frozenset(raw["allowed_deductions"]),
        caps={k: _d(v) for k, v in raw["caps"].items()},
        rebate_87a=Rebate87A(
            income_limit=_d(raw["rebate_87a"]["income_limit"]),
            max_rebate=_d(raw["rebate_87a"]["max_rebate"]),
            marginal_relief=bool(raw["rebate_87a"]["marginal_relief"]),
        ),
        surcharge=tuple(
            SurchargeBand(above=_d(b["above"]), rate=_d(b["rate"]))
            for b in raw["surcharge"]
        ),
    )


@lru_cache(maxsize=8)
def load_rules(assessment_year: str) -> TaxRules:
    """Load and cache rules for an assessment year, e.g. '2026-27'."""
    path = RULES_DIR / f"ay_{assessment_year.replace('-', '_')}.json"
    if not path.exists():
        available = sorted(p.stem for p in RULES_DIR.glob("ay_*.json"))
        raise FileNotFoundError(
            f"No rules config for AY {assessment_year}. Available: {available}"
        )

    raw = json.loads(path.read_text())
    return TaxRules(
        assessment_year=raw["assessment_year"],
        financial_year=raw["financial_year"],
        cess_rate=_d(raw["cess_rate"]),
        old=_parse_regime("old", raw["regimes"]["old"]),
        new=_parse_regime("new", raw["regimes"]["new"]),
        hra=HraRules(
            metro_percent=_d(raw["hra"]["metro_percent"]),
            non_metro_percent=_d(raw["hra"]["non_metro_percent"]),
            rent_minus_basic_percent=_d(raw["hra"]["rent_minus_basic_percent"]),
        ),
    )
