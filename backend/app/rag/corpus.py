"""Seed corpus.

A small curated set of the provisions users actually ask about. Paraphrased
summaries with section references, not verbatim statutory text — enough to
ground answers and cite correctly, and replaceable with the full Act text
without any code change.

To load the real corpus: drop text files into corpus/, and point
`load_corpus()` at them. The chunker handles section splitting.
"""

from __future__ import annotations

from app.rag.ingest import Document

SEED_DOCUMENTS: list[Document] = [
    Document(
        title="Section 4 — What income tax is and how it is charged",
        source="act/4",
        text="""4. Charge of income-tax.

Income-tax is a direct tax levied by the Central Government on the income a person earns during a year, charged for every assessment year at the rates the relevant Finance Act prescribes, on the total income of the previous year of every person.

The "previous year" is the financial year in which income is earned; the "assessment year" is the year immediately following it, in which that income is assessed and the tax reconciled. Income earned in financial year 2025-26, for instance, is assessed in assessment year 2026-27.

For an individual, total income is computed under five heads: Salaries, Income from house property, Profits and gains of business or profession, Capital gains, and Income from other sources. Income under each head is aggregated, reduced by whatever deductions the chosen regime allows, and taxed at slab rates that rise with income.

An individual chooses between two parallel sets of rules for this computation: the regime under section 115BAC(1A), now the default, which offers lower slab rates in exchange for giving up most exemptions and deductions; and the older regime, which keeps those deductions but taxes income at comparatively higher slab rates. Health and education cess is added to the tax computed under either regime, and a rebate under section 87A may reduce or eliminate liability for taxpayers below the prescribed income threshold.""",
    ),
    Document(
        title="Section 80C — Deduction for specified investments",
        source="act/80C",
        text="""80C. Deduction in respect of life insurance premia, provident fund contributions and other specified investments.

A deduction of up to Rs 1,50,000 is available to an individual or Hindu Undivided Family in respect of sums paid or deposited in specified instruments during the previous year. Qualifying investments include employee provident fund contributions, public provident fund deposits, life insurance premia, equity linked savings schemes, five-year tax-saving fixed deposits, National Savings Certificates, tuition fees paid for up to two children, and repayment of the principal component of a housing loan.

The aggregate limit of Rs 1,50,000 applies across sections 80C, 80CCC and 80CCD(1) taken together.

This deduction is available only under the old regime. A taxpayer who opts for the regime under section 115BAC(1A) forgoes it entirely.""",
    ),
    Document(
        title="Section 80CCD — National Pension System",
        source="act/80CCD",
        text="""80CCD. Deduction in respect of contribution to pension scheme of Central Government.

Sub-section (1) covers the employee's own mandatory contribution, which falls within the aggregate Rs 1,50,000 ceiling shared with section 80C.

Sub-section (1B) provides an additional deduction of up to Rs 50,000 for the taxpayer's own contribution to the National Pension System. This is over and above the Rs 1,50,000 ceiling. It is available only under the old regime.

Sub-section (2) covers the employer's contribution to the employee's NPS account. This deduction survives into the regime under section 115BAC(1A), making it one of the very few deductions available in the new regime and therefore disproportionately valuable to taxpayers who have opted into it.""",
    ),
    Document(
        title="Section 80D — Health insurance premia",
        source="act/80D",
        text="""80D. Deduction in respect of health insurance premia.

A deduction is allowed for premia paid on health insurance policies covering the taxpayer, spouse and dependent children, subject to a limit of Rs 25,000. Where the taxpayer or spouse is a senior citizen, that limit rises to Rs 50,000.

A separate and additional deduction is available for premia paid in respect of parents, again limited to Rs 25,000, or Rs 50,000 where either parent is a senior citizen. The parents need not be dependent on the taxpayer.

Preventive health check-up expenditure of up to Rs 5,000 is included within the above limits.

The deduction is available only under the old regime.""",
    ),
    Document(
        title="Section 10(13A) and Rule 2A — House Rent Allowance",
        source="act/10-13A",
        text="""10(13A). Exemption for House Rent Allowance.

Where a salaried taxpayer receives House Rent Allowance and actually pays rent for residential accommodation, an exemption is available equal to the least of three amounts.

First, the actual House Rent Allowance received during the year. Second, fifty per cent of salary where the accommodation is in Delhi, Mumbai, Kolkata or Chennai, and forty per cent of salary elsewhere. Third, the rent actually paid reduced by ten per cent of salary.

Salary for this purpose means basic salary together with dearness allowance forming part of retirement benefits and any commission on turnover.

No exemption arises where no rent is actually paid, or where rent paid does not exceed ten per cent of salary. The exemption is not available under the regime in section 115BAC(1A).""",
    ),
    Document(
        title="Section 24(b) — Interest on borrowed capital",
        source="act/24b",
        text="""24(b). Deduction for interest on borrowed capital for house property.

Interest payable on capital borrowed for acquiring, constructing, repairing or reconstructing house property is deductible in computing income from house property.

For a self-occupied property the deduction is capped at Rs 2,00,000 per year, provided the acquisition or construction is completed within five years of the end of the financial year in which the capital was borrowed. Where that condition is not met the cap falls to Rs 30,000.

For a let-out property the interest is deductible without limit, though the resulting loss under the head house property that may be set off against other heads is restricted to Rs 2,00,000 per year, with the balance carried forward.

Interest paid during the pre-construction period is deductible in five equal annual instalments beginning in the year of completion.

A taxpayer may claim both the HRA exemption under 10(13A) and the interest deduction under 24(b) in the same year where the facts genuinely support both — for example where the taxpayer rents accommodation in the city of employment while owning a house elsewhere that is let out or cannot reasonably be occupied.""",
    ),
    Document(
        title="Section 115BAC(1A) — The new tax regime",
        source="act/115BAC",
        text="""115BAC(1A). Alternative tax regime for individuals and Hindu Undivided Families.

This section provides concessional slab rates in exchange for forgoing most exemptions and deductions. It is the default regime; a taxpayer must opt out affirmatively to be taxed under the old regime.

Deductions and exemptions forgone include those under sections 80C, 80D, 80CCD(1B), 24(b) for self-occupied property, and the House Rent Allowance exemption under 10(13A), among others.

Deductions that survive include the standard deduction under section 16(ia) and the employer's contribution to the National Pension System under section 80CCD(2).

A salaried taxpayer without business income may switch between regimes in any assessment year. A taxpayer with income from business or profession may exercise the option to leave the new regime only once, and having left it cannot return. This asymmetry makes the choice materially more consequential for freelancers and business owners than for salaried employees.""",
    ),
    Document(
        title="Section 87A — Rebate for resident individuals",
        source="act/87A",
        text="""87A. Rebate of income-tax in case of certain individuals.

A resident individual whose total income does not exceed the prescribed threshold is entitled to a rebate against income-tax computed before the addition of health and education cess.

Under the old regime the threshold is total income of Rs 5,00,000 and the maximum rebate is Rs 12,500. No marginal relief is provided, so a taxpayer whose income exceeds the threshold even slightly loses the entire rebate.

Under the regime in section 115BAC(1A), for assessment year 2026-27 the threshold is total income of Rs 12,00,000 and the maximum rebate is Rs 60,000. The total rebate cannot exceed the income-tax otherwise payable.

Marginal relief is available under the new regime. Where total income exceeds Rs 12,00,000 and the tax payable exceeds the amount by which income exceeds that threshold, the taxpayer may claim relief to the extent of the difference. The practical effect is that tax payable never exceeds the amount of income earned above the threshold.

The rebate is available only to residents. A non-resident cannot claim it under either regime.""",
    ),
    Document(
        title="Section 16(ia) — Standard deduction from salary",
        source="act/16ia",
        text="""16(ia). Standard deduction.

A flat deduction is allowed from income chargeable under the head Salaries, without any requirement to substantiate expenditure.

The deduction is available under both the old regime and the regime in section 115BAC(1A), though the amounts differ, with the new regime providing the higher figure. It is one of only two significant reliefs that survive into the new regime, the other being the employer's NPS contribution under section 80CCD(2).

The deduction cannot exceed the amount of salary income itself.""",
    ),
    Document(
        title="Surcharge and health and education cess",
        source="act/surcharge",
        text="""Surcharge on income-tax.

Surcharge is levied on the amount of income-tax where total income exceeds specified thresholds, at rates rising in bands from Rs 50 lakh upwards.

Marginal relief is available at every threshold. Where income exceeds a threshold, the aggregate of income-tax and surcharge shall not exceed the income-tax payable on income at the threshold plus the amount by which income exceeds it. Without this relief, crossing a surcharge threshold by a single rupee would increase liability by a substantial sum.

Health and education cess is levied at four per cent on the aggregate of income-tax and surcharge. It applies under both regimes and no marginal relief attaches to it. The cess is computed after the section 87A rebate has been applied.""",
    ),
    Document(
        title="Section 80TTA and 80TTB — Interest income deductions",
        source="act/80TTA",
        text="""80TTA. Deduction in respect of interest on deposits in savings accounts.

A deduction of up to Rs 10,000 is allowed to an individual or Hindu Undivided Family in respect of interest on deposits in a savings account with a bank, co-operative society or post office. Interest on fixed deposits and recurring deposits does not qualify.

80TTB. Deduction in respect of interest on deposits in case of senior citizens.

A resident senior citizen may instead claim a deduction of up to Rs 50,000 in respect of interest on deposits, and this wider provision covers fixed and recurring deposits as well as savings accounts. A senior citizen claiming 80TTB cannot also claim 80TTA.

Neither deduction is available under the regime in section 115BAC(1A).""",
    ),
]


def load_corpus() -> list[Document]:
    return list(SEED_DOCUMENTS)
