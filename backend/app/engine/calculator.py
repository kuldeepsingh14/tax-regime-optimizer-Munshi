"""Deterministic tax computation engine.

No AI. No heuristics. No randomness. Every rupee is traceable to a TaxLine and
to a clause in the rules config.

A single engine runs both regimes. There is no `if regime == "new"` anywhere in
the calculation logic: regime differences are expressed entirely through the
config (allowed_deductions, slabs, standard_deduction, rebate_87a). Adding a
third regime would require no code change.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.domain.models import (
    AgeCategory,
    ComparisonResult,
    Regime,
    RegimeResult,
    TaxLine,
    TaxpayerProfile,
)
from app.engine.rules import RegimeRules, Slab, TaxRules, load_rules

ZERO = Decimal("0")
TEN = Decimal("10")


# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------

def round_rupee(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def round_to_ten(amount: Decimal) -> Decimal:
    """Section 288B: tax payable is rounded off to the nearest ten rupees."""
    return (amount / TEN).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * TEN


# --------------------------------------------------------------------------
# slab application
# --------------------------------------------------------------------------

def apply_slabs(taxable_income: Decimal, slabs: tuple[Slab, ...]) -> Decimal:
    """Progressive slab tax. Each slab taxes only the income within its band."""
    if taxable_income <= ZERO:
        return ZERO

    tax = ZERO
    lower = ZERO

    for slab in slabs:
        upper = slab.upto if slab.upto is not None else taxable_income
        if taxable_income <= lower:
            break
        band = min(taxable_income, upper) - lower
        if band > ZERO:
            tax += band * slab.rate
        lower = upper
        if slab.upto is None:
            break

    return tax


# --------------------------------------------------------------------------
# exemptions and deductions
# --------------------------------------------------------------------------

def hra_exemption(profile: TaxpayerProfile, rules: TaxRules) -> Decimal:
    """Least of three statutory limbs (Rule 2A)."""
    salary = profile.salary
    if salary.hra_received <= ZERO or salary.rent_paid <= ZERO:
        return ZERO

    pct = rules.hra.metro_percent if salary.is_metro else rules.hra.non_metro_percent

    limb_1 = salary.hra_received
    limb_2 = salary.basic * pct
    limb_3 = salary.rent_paid - (salary.basic * rules.hra.rent_minus_basic_percent)

    return max(ZERO, min(limb_1, limb_2, limb_3))


def _capped(amount: Decimal, cap: Decimal | None) -> Decimal:
    if amount <= ZERO:
        return ZERO
    return min(amount, cap) if cap is not None else amount


def sec_80d_allowed(profile: TaxpayerProfile, regime: RegimeRules) -> Decimal:
    d = profile.deductions
    self_cap = regime.cap("80d_self_senior" if d.self_is_senior else "80d_self")
    parents_cap = regime.cap(
        "80d_parents_senior" if d.parents_are_senior else "80d_parents"
    )
    return _capped(d.sec_80d_self, self_cap) + _capped(d.sec_80d_parents, parents_cap)


def compute_deductions(
    profile: TaxpayerProfile, regime: RegimeRules, rules: TaxRules
) -> list[TaxLine]:
    """Build the deduction trail, filtered by what this regime permits."""
    d = profile.deductions
    lines: list[TaxLine] = []

    def add(key: str, label: str, amount: Decimal, section: str) -> None:
        if not regime.allows(key) or amount <= ZERO:
            return
        lines.append(
            TaxLine(label=label, amount=amount, section=section, is_deduction=True)
        )

    add("hra", "HRA exemption", hra_exemption(profile, rules), "10(13A)")
    add("80c", "Investments", _capped(d.sec_80c, regime.cap("80c")), "80C")
    add("80d", "Health insurance", sec_80d_allowed(profile, regime), "80D")
    add(
        "24b",
        "Home loan interest",
        _capped(d.home_loan_interest, regime.cap("24b")),
        "24(b)",
    )
    add(
        "80ccd1b",
        "NPS (self)",
        _capped(d.nps_self_80ccd1b, regime.cap("80ccd1b")),
        "80CCD(1B)",
    )
    add(
        "80tta",
        "Savings interest",
        _capped(d.savings_interest_80tta, regime.cap("80tta")),
        "80TTA",
    )
    # 80CCD(2) — employer NPS — survives into the new regime. One of the very
    # few deductions that does, which makes it disproportionately valuable.
    add("80ccd2", "NPS (employer)", d.nps_employer_80ccd2, "80CCD(2)")

    return lines


# --------------------------------------------------------------------------
# rebate, surcharge, cess
# --------------------------------------------------------------------------

def compute_rebate(
    taxable_income: Decimal,
    tax: Decimal,
    profile: TaxpayerProfile,
    regime: RegimeRules,
) -> Decimal:
    """Section 87A rebate, including marginal relief where the regime provides it.

    Available to resident individuals only.
    """
    if not profile.is_resident:
        return ZERO

    r = regime.rebate_87a

    if taxable_income <= r.income_limit:
        return min(tax, r.max_rebate)

    if not r.marginal_relief:
        return ZERO

    # Marginal relief: tax payable must not exceed the amount by which income
    # exceeds the threshold. Without this, earning one rupee over the limit
    # would cost tens of thousands.
    excess = taxable_income - r.income_limit
    return max(ZERO, tax - excess) if tax > excess else ZERO


def compute_surcharge(
    taxable_income: Decimal,
    tax: Decimal,
    regime: RegimeRules,
    age_category: str,
) -> Decimal:
    """Surcharge with marginal relief at each threshold."""
    band = None
    for candidate in regime.surcharge:
        if taxable_income > candidate.above:
            band = candidate
    if band is None:
        return ZERO

    surcharge = tax * band.rate

    # Marginal relief: (tax + surcharge) must not exceed the tax at the
    # threshold plus the income above it.
    tax_at_threshold = apply_slabs(band.above, regime.slabs_for(age_category))
    ceiling = tax_at_threshold + (taxable_income - band.above)
    if tax + surcharge > ceiling:
        surcharge = max(ZERO, ceiling - tax)

    return surcharge


# --------------------------------------------------------------------------
# single-regime computation
# --------------------------------------------------------------------------

def compute_regime(
    profile: TaxpayerProfile, regime_key: str, rules: TaxRules
) -> RegimeResult:
    regime = rules.regime(regime_key)
    age = profile.age_category.value
    lines: list[TaxLine] = []

    # 1. Gross total income
    gross = profile.salary.gross_salary + profile.other_income.total
    lines.append(TaxLine("Gross salary", profile.salary.gross_salary))
    if profile.other_income.total > ZERO:
        lines.append(TaxLine("Other income", profile.other_income.total))

    # 2. Standard deduction
    std = min(regime.standard_deduction, profile.salary.gross_salary)
    if std > ZERO:
        lines.append(
            TaxLine("Standard deduction", std, section="16(ia)", is_deduction=True)
        )

    # 3. Chapter VI-A and exemptions, filtered by regime
    deduction_lines = compute_deductions(profile, regime, rules)
    lines.extend(deduction_lines)

    total_deductions = std + sum(l.amount for l in deduction_lines)

    # 4. Taxable income (rounded to nearest ten per s.288A)
    taxable = max(ZERO, gross - total_deductions)
    taxable = round_to_ten(taxable)
    lines.append(TaxLine("Taxable income", taxable))

    # 5. Slab tax
    tax_before_rebate = apply_slabs(taxable, regime.slabs_for(age))
    lines.append(TaxLine("Tax on taxable income", round_rupee(tax_before_rebate)))

    # 6. Rebate
    rebate = compute_rebate(taxable, tax_before_rebate, profile, regime)
    if rebate > ZERO:
        lines.append(
            TaxLine("Rebate", round_rupee(rebate), section="87A", is_deduction=True)
        )
    tax_after_rebate = max(ZERO, tax_before_rebate - rebate)

    # 7. Surcharge
    surcharge = compute_surcharge(taxable, tax_after_rebate, regime, age)
    if surcharge > ZERO:
        lines.append(TaxLine("Surcharge", round_rupee(surcharge)))

    # 8. Cess on (tax + surcharge)
    cess = (tax_after_rebate + surcharge) * rules.cess_rate
    if cess > ZERO:
        lines.append(TaxLine("Health & Education Cess", round_rupee(cess)))

    total_tax = round_to_ten(tax_after_rebate + surcharge + cess)
    lines.append(TaxLine("Total tax payable", total_tax))

    return RegimeResult(
        regime=Regime(regime_key),
        lines=tuple(lines),
        gross_total_income=gross,
        total_deductions=total_deductions,
        taxable_income=taxable,
        tax_before_rebate=round_rupee(tax_before_rebate),
        rebate=round_rupee(rebate),
        tax_after_rebate=round_rupee(tax_after_rebate),
        surcharge=round_rupee(surcharge),
        cess=round_rupee(cess),
        total_tax=total_tax,
    )


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------

def compare(
    profile: TaxpayerProfile, assessment_year: str = "2026-27"
) -> ComparisonResult:
    from app.engine.breakeven import find_breakeven  # local import avoids cycle

    rules = load_rules(assessment_year)
    old = compute_regime(profile, "old", rules)
    new = compute_regime(profile, "new", rules)

    recommended = Regime.OLD if old.total_tax < new.total_tax else Regime.NEW
    saving = abs(old.total_tax - new.total_tax)

    # Deductions the old regime actually granted, excluding standard deduction
    # (which both regimes give, so it isn't part of the breakeven question).
    current = old.total_deductions - min(
        rules.old.standard_deduction, profile.salary.gross_salary
    )

    return ComparisonResult(
        assessment_year=rules.assessment_year,
        old=old,
        new=new,
        recommended=recommended,
        saving=saving,
        breakeven_deductions=find_breakeven(profile, assessment_year),
        current_deductions=current,
    )
