"""API schemas.

Decimal is used end to end. Pydantic serialises Decimal to a JSON number by
default, which reintroduces float precision at the boundary — so we serialise
money as strings and let the frontend format for display.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    AgeCategory,
    ComparisonResult,
    Deductions,
    OtherIncome,
    SalaryInput,
    TaxpayerProfile,
)


class SalaryIn(BaseModel):
    gross_salary: Decimal = Field(ge=0)
    basic: Decimal = Field(default=Decimal("0"), ge=0)
    hra_received: Decimal = Field(default=Decimal("0"), ge=0)
    rent_paid: Decimal = Field(default=Decimal("0"), ge=0)
    is_metro: bool = False


class DeductionsIn(BaseModel):
    sec_80c: Decimal = Field(default=Decimal("0"), ge=0)
    sec_80d_self: Decimal = Field(default=Decimal("0"), ge=0)
    sec_80d_parents: Decimal = Field(default=Decimal("0"), ge=0)
    self_is_senior: bool = False
    parents_are_senior: bool = False
    home_loan_interest: Decimal = Field(default=Decimal("0"), ge=0)
    nps_self_80ccd1b: Decimal = Field(default=Decimal("0"), ge=0)
    nps_employer_80ccd2: Decimal = Field(default=Decimal("0"), ge=0)
    savings_interest_80tta: Decimal = Field(default=Decimal("0"), ge=0)


class OtherIncomeIn(BaseModel):
    savings_interest: Decimal = Field(default=Decimal("0"), ge=0)
    fd_interest: Decimal = Field(default=Decimal("0"), ge=0)
    other: Decimal = Field(default=Decimal("0"), ge=0)


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_year: str = "2026-27"
    salary: SalaryIn
    deductions: DeductionsIn = DeductionsIn()
    other_income: OtherIncomeIn = OtherIncomeIn()
    age_category: AgeCategory = AgeCategory.DEFAULT
    is_resident: bool = True

    def to_domain(self) -> TaxpayerProfile:
        return TaxpayerProfile(
            salary=SalaryInput(**self.salary.model_dump()),
            deductions=Deductions(**self.deductions.model_dump()),
            other_income=OtherIncome(**self.other_income.model_dump()),
            age_category=self.age_category,
            is_resident=self.is_resident,
        )


class TaxLineOut(BaseModel):
    label: str
    amount: str
    section: str | None = None
    is_deduction: bool = False


class RegimeResultOut(BaseModel):
    regime: str
    name: str
    lines: list[TaxLineOut]
    taxable_income: str
    tax_before_rebate: str
    rebate: str
    surcharge: str
    cess: str
    total_tax: str


class ComparisonOut(BaseModel):
    assessment_year: str
    old: RegimeResultOut
    new: RegimeResultOut
    recommended: str
    saving: str
    breakeven_deductions: str
    current_deductions: str

    @classmethod
    def from_domain(cls, r: ComparisonResult) -> "ComparisonOut":
        def regime_out(res, name: str) -> RegimeResultOut:
            return RegimeResultOut(
                regime=res.regime.value,
                name=name,
                lines=[
                    TaxLineOut(
                        label=l.label,
                        amount=str(l.amount),
                        section=l.section,
                        is_deduction=l.is_deduction,
                    )
                    for l in res.lines
                ],
                taxable_income=str(res.taxable_income),
                tax_before_rebate=str(res.tax_before_rebate),
                rebate=str(res.rebate),
                surcharge=str(res.surcharge),
                cess=str(res.cess),
                total_tax=str(res.total_tax),
            )

        return cls(
            assessment_year=r.assessment_year,
            old=regime_out(r.old, "Old Regime"),
            new=regime_out(r.new, "New Regime"),
            recommended=r.recommended.value,
            saving=str(r.saving),
            breakeven_deductions=str(r.breakeven_deductions),
            current_deductions=str(r.current_deductions),
        )
