"""Domain model.

Every monetary value is a Decimal. Never float: binary floating point cannot
represent decimal fractions exactly, which produces off-by-a-paisa errors that
compound across operations and break exact-match tests.

All inputs are frozen so no computation can mutate them and silently affect a
later one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class AgeCategory(str, Enum):
    DEFAULT = "default"            # below 60
    SENIOR = "senior"              # 60 to 79
    SUPER_SENIOR = "super_senior"  # 80 and above


class Regime(str, Enum):
    OLD = "old"
    NEW = "new"


@dataclass(frozen=True)
class SalaryInput:
    gross_salary: Decimal
    basic: Decimal = Decimal("0")
    hra_received: Decimal = Decimal("0")
    rent_paid: Decimal = Decimal("0")
    is_metro: bool = False


@dataclass(frozen=True)
class Deductions:
    sec_80c: Decimal = Decimal("0")
    sec_80d_self: Decimal = Decimal("0")
    sec_80d_parents: Decimal = Decimal("0")
    self_is_senior: bool = False
    parents_are_senior: bool = False
    home_loan_interest: Decimal = Decimal("0")     # 24(b)
    nps_self_80ccd1b: Decimal = Decimal("0")
    nps_employer_80ccd2: Decimal = Decimal("0")
    savings_interest_80tta: Decimal = Decimal("0")


@dataclass(frozen=True)
class OtherIncome:
    savings_interest: Decimal = Decimal("0")
    fd_interest: Decimal = Decimal("0")
    other: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.savings_interest + self.fd_interest + self.other


@dataclass(frozen=True)
class TaxpayerProfile:
    salary: SalaryInput
    deductions: Deductions = field(default_factory=Deductions)
    other_income: OtherIncome = field(default_factory=OtherIncome)
    age_category: AgeCategory = AgeCategory.DEFAULT
    is_resident: bool = True


@dataclass(frozen=True)
class TaxLine:
    """One row of the computation trail.

    The trail is assembled by construction, not reconstructed for display.
    Every rupee in the final number is traceable to a line here.
    """
    label: str
    amount: Decimal
    section: str | None = None
    is_deduction: bool = False


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    lines: tuple[TaxLine, ...]
    gross_total_income: Decimal
    total_deductions: Decimal
    taxable_income: Decimal
    tax_before_rebate: Decimal
    rebate: Decimal
    tax_after_rebate: Decimal
    surcharge: Decimal
    cess: Decimal
    total_tax: Decimal


@dataclass(frozen=True)
class ComparisonResult:
    assessment_year: str
    old: RegimeResult
    new: RegimeResult
    recommended: Regime
    saving: Decimal
    breakeven_deductions: Decimal
    current_deductions: Decimal
