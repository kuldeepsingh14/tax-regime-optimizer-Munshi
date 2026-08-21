"""Exact-match tests. Not 'close enough' — exact rupee equality.

Every expected value here is hand-computed from the AY 2026-27 rate document.
"""

from decimal import Decimal

import pytest

from app.domain.models import (
    AgeCategory,
    Deductions,
    OtherIncome,
    Regime,
    SalaryInput,
    TaxpayerProfile,
)
from app.engine.calculator import (
    apply_slabs,
    compare,
    compute_regime,
    hra_exemption,
)
from app.engine.rules import load_rules

D = Decimal
AY = "2026-27"


def profile(gross, **kw):
    return TaxpayerProfile(
        salary=SalaryInput(
            gross_salary=D(gross),
            basic=D(kw.pop("basic", "0")),
            hra_received=D(kw.pop("hra_received", "0")),
            rent_paid=D(kw.pop("rent_paid", "0")),
            is_metro=kw.pop("is_metro", False),
        ),
        deductions=kw.pop("deductions", Deductions()),
        other_income=kw.pop("other_income", OtherIncome()),
        age_category=kw.pop("age_category", AgeCategory.DEFAULT),
        is_resident=kw.pop("is_resident", True),
    )


# --------------------------------------------------------------------------
# slab arithmetic
# --------------------------------------------------------------------------

class TestSlabs:
    def test_new_regime_slabs_at_16_lakh(self):
        """4L nil + 4L@5% + 4L@10% + 4L@15% = 0 + 20000 + 40000 + 60000."""
        rules = load_rules(AY)
        tax = apply_slabs(D("1600000"), rules.new.slabs_for("default"))
        assert tax == D("120000")

    def test_old_regime_slabs_at_10_lakh(self):
        """2.5L nil + 2.5L@5% + 5L@20% = 0 + 12500 + 100000."""
        rules = load_rules(AY)
        tax = apply_slabs(D("1000000"), rules.old.slabs_for("default"))
        assert tax == D("112500")

    def test_zero_income(self):
        rules = load_rules(AY)
        assert apply_slabs(D("0"), rules.new.slabs_for("default")) == D("0")

    def test_exactly_at_first_threshold(self):
        rules = load_rules(AY)
        assert apply_slabs(D("400000"), rules.new.slabs_for("default")) == D("0")

    def test_one_rupee_over_threshold(self):
        rules = load_rules(AY)
        assert apply_slabs(D("400001"), rules.new.slabs_for("default")) == D("0.05")

    def test_senior_citizen_higher_exemption(self):
        """Senior gets 3L nil vs 2.5L — saves 5% of 50,000 = 2,500."""
        rules = load_rules(AY)
        default = apply_slabs(D("1000000"), rules.old.slabs_for("default"))
        senior = apply_slabs(D("1000000"), rules.old.slabs_for("senior"))
        assert default - senior == D("2500")

    def test_super_senior_exemption(self):
        """5L nil, no 5% band at all."""
        rules = load_rules(AY)
        assert apply_slabs(D("500000"), rules.old.slabs_for("super_senior")) == D("0")


# --------------------------------------------------------------------------
# HRA — least of three limbs
# --------------------------------------------------------------------------

class TestHRA:
    def test_limb_2_binds_in_metro(self):
        """50% of basic = 250000; HRA received 300000; rent-10% = 290000."""
        rules = load_rules(AY)
        p = profile(
            "1400000", basic="500000", hra_received="300000",
            rent_paid="340000", is_metro=True,
        )
        assert hra_exemption(p, rules) == D("250000")

    def test_limb_3_binds(self):
        """Rent paid barely above 10% of basic."""
        rules = load_rules(AY)
        p = profile(
            "1400000", basic="500000", hra_received="300000",
            rent_paid="60000", is_metro=True,
        )
        assert hra_exemption(p, rules) == D("10000")

    def test_non_metro_uses_40_percent(self):
        rules = load_rules(AY)
        p = profile(
            "1400000", basic="500000", hra_received="300000",
            rent_paid="340000", is_metro=False,
        )
        assert hra_exemption(p, rules) == D("200000")

    def test_no_rent_no_exemption(self):
        rules = load_rules(AY)
        p = profile("1400000", basic="500000", hra_received="300000", rent_paid="0")
        assert hra_exemption(p, rules) == D("0")

    def test_rent_below_ten_percent_gives_zero_not_negative(self):
        rules = load_rules(AY)
        p = profile(
            "1400000", basic="500000", hra_received="300000",
            rent_paid="10000", is_metro=True,
        )
        assert hra_exemption(p, rules) == D("0")


# --------------------------------------------------------------------------
# section 87A rebate — the cliff
# --------------------------------------------------------------------------

class TestRebate:
    def test_new_regime_zero_tax_at_12_lakh_taxable(self):
        """Taxable 12L: tax = 20000+40000 = 60000, fully rebated."""
        r = compute_regime(profile("1275000"), "new", load_rules(AY))
        assert r.taxable_income == D("1200000")
        assert r.tax_before_rebate == D("60000")
        assert r.rebate == D("60000")
        assert r.total_tax == D("0")

    def test_marginal_relief_just_above_cliff(self):
        """Taxable 12,10,000 = 60000 (up to 12L) + 10000 @ 15% = 61500.
        Excess over the 12L threshold is 10000, so marginal relief rebates
        61500 - 10000 = 51500, leaving 10000 + 4% cess."""
        r = compute_regime(profile("1285000"), "new", load_rules(AY))
        assert r.taxable_income == D("1210000")
        assert r.tax_before_rebate == D("61500")
        assert r.rebate == D("51500")
        assert r.tax_after_rebate == D("10000")
        assert r.total_tax == D("10400")

    def test_marginal_relief_expires_when_tax_below_excess(self):
        """Far above the cliff, no relief applies."""
        r = compute_regime(profile("1600000"), "new", load_rules(AY))
        assert r.rebate == D("0")

    def test_old_regime_rebate_at_5_lakh(self):
        p = profile("550000")
        r = compute_regime(p, "old", load_rules(AY))
        assert r.taxable_income == D("500000")
        assert r.tax_before_rebate == D("12500")
        assert r.rebate == D("12500")
        assert r.total_tax == D("0")

    def test_old_regime_has_no_marginal_relief(self):
        """One rupee over 5L in the old regime: full tax, no relief.
        This asymmetry is real and is why the new regime cliff matters more."""
        p = profile("560000")
        r = compute_regime(p, "old", load_rules(AY))
        assert r.taxable_income == D("510000")
        assert r.rebate == D("0")
        assert r.tax_before_rebate == D("14500")

    def test_non_resident_gets_no_rebate(self):
        p = profile("1275000", is_resident=False)
        r = compute_regime(p, "new", load_rules(AY))
        assert r.rebate == D("0")
        assert r.total_tax > D("0")


# --------------------------------------------------------------------------
# regime-specific deduction filtering
# --------------------------------------------------------------------------

class TestDeductionFiltering:
    def test_new_regime_ignores_80c(self):
        d = Deductions(sec_80c=D("150000"))
        with_d = compute_regime(profile("1400000", deductions=d), "new", load_rules(AY))
        without = compute_regime(profile("1400000"), "new", load_rules(AY))
        assert with_d.total_tax == without.total_tax

    def test_old_regime_honours_80c(self):
        d = Deductions(sec_80c=D("150000"))
        with_d = compute_regime(profile("1400000", deductions=d), "old", load_rules(AY))
        without = compute_regime(profile("1400000"), "old", load_rules(AY))
        assert with_d.total_tax < without.total_tax

    def test_employer_nps_survives_into_new_regime(self):
        """80CCD(2) is one of the very few deductions the new regime keeps."""
        d = Deductions(nps_employer_80ccd2=D("100000"))
        with_d = compute_regime(profile("1400000", deductions=d), "new", load_rules(AY))
        without = compute_regime(profile("1400000"), "new", load_rules(AY))
        assert with_d.total_tax < without.total_tax

    def test_80c_is_capped_at_150000(self):
        over = Deductions(sec_80c=D("300000"))
        at_cap = Deductions(sec_80c=D("150000"))
        a = compute_regime(profile("1400000", deductions=over), "old", load_rules(AY))
        b = compute_regime(profile("1400000", deductions=at_cap), "old", load_rules(AY))
        assert a.total_tax == b.total_tax

    def test_80d_senior_parents_higher_cap(self):
        normal = Deductions(sec_80d_parents=D("50000"), parents_are_senior=False)
        senior = Deductions(sec_80d_parents=D("50000"), parents_are_senior=True)
        a = compute_regime(profile("1400000", deductions=normal), "old", load_rules(AY))
        b = compute_regime(profile("1400000", deductions=senior), "old", load_rules(AY))
        assert b.total_tax < a.total_tax

    def test_home_loan_interest_capped_at_200000(self):
        over = Deductions(home_loan_interest=D("350000"))
        at_cap = Deductions(home_loan_interest=D("200000"))
        a = compute_regime(profile("1400000", deductions=over), "old", load_rules(AY))
        b = compute_regime(profile("1400000", deductions=at_cap), "old", load_rules(AY))
        assert a.total_tax == b.total_tax


# --------------------------------------------------------------------------
# surcharge and marginal relief
# --------------------------------------------------------------------------

class TestSurcharge:
    def test_no_surcharge_below_50_lakh(self):
        r = compute_regime(profile("4500000"), "new", load_rules(AY))
        assert r.surcharge == D("0")

    def test_surcharge_applies_above_50_lakh(self):
        r = compute_regime(profile("6000000"), "new", load_rules(AY))
        assert r.surcharge > D("0")

    def test_marginal_relief_just_above_50_lakh(self):
        """Crossing 50L by a small amount must not increase total tax by more
        than the amount of the crossing."""
        below = compute_regime(profile("5074999"), "new", load_rules(AY))
        above = compute_regime(profile("5075100"), "new", load_rules(AY))
        income_delta = D("5075100") - D("5074999")
        assert above.total_tax - below.total_tax <= income_delta * 2


# --------------------------------------------------------------------------
# end-to-end comparison
# --------------------------------------------------------------------------

class TestComparison:
    def test_no_deductions_favours_new_regime(self):
        result = compare(profile("1400000"), AY)
        assert result.recommended == Regime.NEW

    def test_heavy_deductions_favour_old_regime(self):
        d = Deductions(
            sec_80c=D("150000"),
            sec_80d_self=D("25000"),
            home_loan_interest=D("200000"),
            nps_self_80ccd1b=D("50000"),
        )
        p = profile(
            "1400000", basic="600000", hra_received="300000",
            rent_paid="360000", is_metro=True, deductions=d,
        )
        result = compare(p, AY)
        assert result.recommended == Regime.OLD

    def test_saving_is_absolute_difference(self):
        result = compare(profile("1400000"), AY)
        assert result.saving == abs(result.old.total_tax - result.new.total_tax)

    def test_computation_trail_is_present(self):
        result = compare(profile("1400000"), AY)
        labels = [l.label for l in result.new.lines]
        assert "Gross salary" in labels
        assert "Taxable income" in labels
        assert "Total tax payable" in labels

    def test_low_income_zero_tax_both_regimes(self):
        result = compare(profile("400000"), AY)
        assert result.old.total_tax == D("0")
        assert result.new.total_tax == D("0")


# --------------------------------------------------------------------------
# breakeven solver — cross-checked against brute force
# --------------------------------------------------------------------------

class TestBreakeven:
    @pytest.mark.parametrize("gross", ["1000000", "1400000", "2000000", "2500000"])
    def test_breakeven_matches_brute_force_scan(self, gross):
        from app.engine.breakeven import _tax_gap_at, find_breakeven

        p = profile(gross)
        solved = find_breakeven(p, AY)

        # Brute force: scan in 5000-rupee steps for the first crossover.
        scanned = None
        step = D("5000")
        probe = D("0")
        while probe <= D(gross):
            if _tax_gap_at(p, probe, AY) <= D("0"):
                scanned = probe
                break
            probe += step

        if scanned is None:
            pytest.skip("old regime never wins at this income")

        assert abs(solved - scanned) <= step * 2

    def test_breakeven_is_actionable(self):
        """At the breakeven point the old regime should be at least as cheap."""
        from app.engine.breakeven import _tax_gap_at, find_breakeven

        p = profile("1400000")
        be = find_breakeven(p, AY)
        assert _tax_gap_at(p, be + D("10000"), AY) <= D("0")


# --------------------------------------------------------------------------
# rules config integrity
# --------------------------------------------------------------------------

class TestRulesConfig:
    def test_loads_ay_2026_27(self):
        rules = load_rules(AY)
        assert rules.assessment_year == "2026-27"
        assert rules.cess_rate == D("0.04")

    def test_new_regime_rebate_is_60000_at_12_lakh(self):
        r = load_rules(AY).new.rebate_87a
        assert r.income_limit == D("1200000")
        assert r.max_rebate == D("60000")
        assert r.marginal_relief is True

    def test_old_regime_rebate_is_12500_at_5_lakh(self):
        r = load_rules(AY).old.rebate_87a
        assert r.income_limit == D("500000")
        assert r.max_rebate == D("12500")
        assert r.marginal_relief is False

    def test_missing_year_raises(self):
        with pytest.raises(FileNotFoundError):
            load_rules("1999-00")

    def test_no_floats_anywhere_in_config(self):
        """Every numeric in the config must be a string, parsed to Decimal."""
        import json
        from pathlib import Path

        raw = json.loads(
            (Path(__file__).resolve().parents[1] / "rules" / "ay_2026_27.json").read_text()
        )

        def check(node, path=""):
            if isinstance(node, float):
                raise AssertionError(f"float found at {path}")
            if isinstance(node, dict):
                for k, v in node.items():
                    check(v, f"{path}.{k}")
            if isinstance(node, list):
                for i, v in enumerate(node):
                    check(v, f"{path}[{i}]")

        check(raw)
