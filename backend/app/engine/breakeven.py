"""Breakeven solver.

The most useful single output in the product:

    "Old regime only wins if your deductions exceed X. You're at Y."

Tax under both regimes is monotonic in total deductions, so binary search
finds the crossover in ~25 iterations. Deterministic, and cross-checkable
against a brute-force scan in tests.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.domain.models import Deductions, TaxpayerProfile
from app.engine.rules import load_rules

ZERO = Decimal("0")
PRECISION = Decimal("100")   # resolve to the nearest 100 rupees


def _tax_gap_at(profile: TaxpayerProfile, deduction_total: Decimal, ay: str) -> Decimal:
    """old_tax - new_tax when the taxpayer claims `deduction_total` in the old regime.

    Negative means old regime wins. We model the deduction total as an
    uncapped old-regime-only allowance so the solver measures the pure
    threshold rather than the interaction of individual section caps.
    """
    from app.engine.calculator import compute_regime

    rules = load_rules(ay)

    # 24(b) is uncapped in our probe because we raise its cap to the probe
    # amount; simpler is to bypass caps by using a synthetic profile whose
    # deductions are expressed through a single uncapped head.
    probe = replace(
        profile,
        deductions=Deductions(
            sec_80c=ZERO,
            sec_80d_self=ZERO,
            sec_80d_parents=ZERO,
            home_loan_interest=ZERO,
            nps_self_80ccd1b=ZERO,
            nps_employer_80ccd2=profile.deductions.nps_employer_80ccd2,
            savings_interest_80tta=ZERO,
        ),
    )

    old = compute_regime(probe, "old", rules)
    new = compute_regime(probe, "new", rules)

    # Recompute the old regime with the probe deduction applied directly to
    # taxable income, which is what "total deductions" means for breakeven.
    from app.engine.calculator import (
        apply_slabs,
        compute_rebate,
        compute_surcharge,
        round_to_ten,
    )

    regime = rules.old
    age = profile.age_category.value
    taxable = round_to_ten(max(ZERO, old.taxable_income - deduction_total))
    tax = apply_slabs(taxable, regime.slabs_for(age))
    rebate = compute_rebate(taxable, tax, profile, regime)
    tax_after = max(ZERO, tax - rebate)
    surcharge = compute_surcharge(taxable, tax_after, regime, age)
    cess = (tax_after + surcharge) * rules.cess_rate
    old_total = round_to_ten(tax_after + surcharge + cess)

    return old_total - new.total_tax


def find_breakeven(profile: TaxpayerProfile, ay: str = "2026-27") -> Decimal:
    """Smallest deduction total at which the old regime becomes at least as cheap.

    Returns 0 if the old regime already wins with no deductions.
    Returns the taxable income ceiling if the old regime can never win.
    """
    lo = ZERO
    hi = profile.salary.gross_salary + profile.other_income.total

    if _tax_gap_at(profile, lo, ay) <= ZERO:
        return ZERO
    if _tax_gap_at(profile, hi, ay) > ZERO:
        return hi

    while hi - lo > PRECISION:
        mid = (lo + hi) / 2
        if _tax_gap_at(profile, mid, ay) > ZERO:
            lo = mid
        else:
            hi = mid

    return (hi / PRECISION).quantize(Decimal("1")) * PRECISION
