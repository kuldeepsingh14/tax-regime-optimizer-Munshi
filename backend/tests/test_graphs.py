"""Graph tests.

No network, no API key, no nondeterminism. The LLM is scripted, so every
branch of the state machine is exercised deterministically — including the
retry cycle and the human-in-the-loop terminal.
"""

from decimal import Decimal

import pytest

from app.extraction.graph import (
    STRATEGY_LADDER,
    route_after_validate,
    run_extraction,
    validate_extraction,
)
from app.extraction.llm import ScriptedClient, parse_llm_json
from app.extraction.patterns import (
    classify_document,
    coverage,
    extract_with_regex,
    parse_amount,
)
from app.reconciliation.graph import run_reconciliation

D = Decimal

STANDARD_FORM16 = """
FORM NO. 16
Certificate under Section 203 of the Income-tax Act, 1961
Part B
TAN of Deductor: MUMA12345B
PAN of the Employee: ABCDE1234F
Assessment Year: 2026-27
1. Gross Salary  14,00,000.00
   Basic Salary   6,00,000.00
   House Rent Allowance  3,00,000.00
2. Standard Deduction  75,000.00
   Section 80C  1,50,000.00
   Section 80D  25,000.00
Total Tax Deducted at Source  57,200.00
"""

NONSTANDARD_FORM16 = """
FORM NO. 16  Part B
Remuneration Particulars for FY 2025-26
Total emoluments paid during the year ...... 22,50,000
Tax remitted to Central Government ......... 3,10,000
"""

GOOD_LLM_JSON = (
    '{"gross_salary": "2250000", "pan": "XYZAB9999C", "tds_deducted": "310000", '
    '"assessment_year": "2026-27", "employer_tan": "MUMA99999Z", "basic": null}'
)


# --------------------------------------------------------------------------
# amount parsing
# --------------------------------------------------------------------------

class TestParseAmount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("14,00,000.00", "1400000"),
            ("Rs. 1,50,000", "150000"),
            ("57200", "57200"),
            ("1,00,000.50", "100001"),  # half-up to whole rupees
        ],
    )
    def test_indian_number_formats(self, raw, expected):
        assert parse_amount(raw) == D(expected)

    @pytest.mark.parametrize("raw", ["", "   ", "N/A", "-"])
    def test_unparseable_returns_none(self, raw):
        assert parse_amount(raw) is None


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

class TestClassification:
    def test_identifies_form16(self):
        assert classify_document(STANDARD_FORM16) == "form16"

    def test_identifies_26as(self):
        assert classify_document("FORM NO. 26AS Annual Tax Statement") == "26as"

    def test_identifies_ais(self):
        assert classify_document("Annual Information Statement for AY 2026-27") == "ais"

    def test_unknown_document(self):
        assert classify_document("Grocery receipt, milk 60 rupees") == "unknown"


# --------------------------------------------------------------------------
# regex extraction
# --------------------------------------------------------------------------

class TestRegexExtraction:
    def test_full_coverage_on_standard_template(self):
        extracted = extract_with_regex(STANDARD_FORM16)
        assert coverage(extracted) == 1.0
        assert extracted["gross_salary"] == D("1400000")
        assert extracted["pan"] == "ABCDE1234F"
        assert extracted["employer_tan"] == "MUMA12345B"

    def test_low_coverage_on_nonstandard_template(self):
        assert coverage(extract_with_regex(NONSTANDARD_FORM16)) < 0.4

    def test_non_form16_yields_nothing(self):
        assert extract_with_regex(STANDARD_FORM16, doc_type="ais") == {}


# --------------------------------------------------------------------------
# LLM output parsing — models misbehave, the parser must not
# --------------------------------------------------------------------------

class TestLLMParsing:
    def test_strips_markdown_fences(self):
        out = parse_llm_json('```json\n{"gross_salary": "500000"}\n```')
        assert out["gross_salary"] == D("500000")

    def test_ignores_prose_around_json(self):
        out = parse_llm_json('Sure! Here you go:\n{"gross_salary": "500000"}\nHope that helps.')
        assert out["gross_salary"] == D("500000")

    def test_malformed_json_returns_empty_not_raises(self):
        assert parse_llm_json("{gross_salary: 500000,,}") == {}

    def test_nulls_are_dropped(self):
        out = parse_llm_json('{"gross_salary": "500000", "basic": null}')
        assert "basic" not in out

    def test_unknown_fields_are_dropped(self):
        out = parse_llm_json('{"gross_salary": "500000", "favourite_colour": "blue"}')
        assert "favourite_colour" not in out

    def test_no_json_at_all(self):
        assert parse_llm_json("I could not find any fields.") == {}


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

class TestValidation:
    def test_clean_extraction_passes(self):
        assert validate_extraction(extract_with_regex(STANDARD_FORM16)) == []

    def test_empty_extraction_fails(self):
        assert validate_extraction({}) == ["no fields extracted"]

    def test_missing_gross_salary_fails(self):
        errors = validate_extraction({"pan": "ABCDE1234F"})
        assert any("gross_salary missing" in e for e in errors)

    def test_malformed_pan_flagged(self):
        errors = validate_extraction(
            {**extract_with_regex(STANDARD_FORM16), "pan": "NOTAPAN"}
        )
        assert any("PAN malformed" in e for e in errors)

    def test_component_exceeding_gross_flagged(self):
        errors = validate_extraction(
            {**extract_with_regex(STANDARD_FORM16), "basic": D("9900000")}
        )
        assert any("basic exceeds gross_salary" in e for e in errors)

    def test_implausible_gross_flagged(self):
        errors = validate_extraction({"gross_salary": D("99999999999")})
        assert any("implausibly large" in e for e in errors)

    def test_negative_gross_flagged(self):
        errors = validate_extraction({"gross_salary": D("-100")})
        assert any("must be positive" in e for e in errors)


# --------------------------------------------------------------------------
# routing logic
# --------------------------------------------------------------------------

class TestRouting:
    def test_clean_validation_ends(self):
        assert route_after_validate({"validation_errors": [], "attempts": 1}) == "done"

    def test_errors_escalate(self):
        state = {"validation_errors": ["x"], "attempts": 1, "strategy": "regex"}
        assert route_after_validate(state) == "escalate"

    def test_exhausted_ladder_goes_to_human(self):
        state = {"validation_errors": ["x"], "attempts": 1, "strategy": "llm_verbose"}
        assert route_after_validate(state) == "human_review"

    def test_max_attempts_goes_to_human(self):
        state = {"validation_errors": ["x"], "attempts": 3, "strategy": "regex"}
        assert route_after_validate(state) == "human_review"


# --------------------------------------------------------------------------
# end-to-end graph behaviour
# --------------------------------------------------------------------------

class TestExtractionGraph:
    def test_standard_template_never_calls_llm(self):
        """Cost and latency both matter. Regex-first must actually short-circuit."""
        llm = ScriptedClient([GOOD_LLM_JSON])
        result = run_extraction(text=STANDARD_FORM16, llm=llm)

        assert result["strategy"] == "regex"
        assert result["attempts"] == 1
        assert result["needs_human"] is False
        assert len(llm.calls) == 0

    def test_escalates_through_full_ladder(self):
        """Regex fails, LLM returns garbage, verbose LLM succeeds."""
        llm = ScriptedClient(["not json at all", GOOD_LLM_JSON])
        result = run_extraction(text=NONSTANDARD_FORM16, llm=llm)

        assert result["strategy"] == "llm_verbose"
        assert result["attempts"] == 3
        assert result["needs_human"] is False
        assert result["validation_errors"] == []
        assert len(llm.calls) == 2
        assert result["extracted"]["gross_salary"] == D("2250000")

    def test_verbose_flag_reaches_the_prompt(self):
        llm = ScriptedClient(["garbage", GOOD_LLM_JSON])
        run_extraction(text=NONSTANDARD_FORM16, llm=llm)
        _, verbose_prompt = llm.calls[-1]
        assert "non-standard layouts" in verbose_prompt

    def test_exhausted_ladder_escalates_to_human(self):
        llm = ScriptedClient(["garbage", "still garbage"])
        result = run_extraction(text=NONSTANDARD_FORM16, llm=llm)

        assert result["needs_human"] is True
        assert result["validation_errors"]

    def test_scanned_pdf_escalates_immediately(self):
        result = run_extraction(text="   ")
        assert result["needs_human"] is True
        assert any("scanned image" in e for e in result["validation_errors"])
        assert "classify" not in " ".join(result["trace"])

    def test_no_llm_configured_falls_back_to_human(self):
        result = run_extraction(text=NONSTANDARD_FORM16, llm=None)
        assert result["needs_human"] is True

    def test_partial_extraction_survives_to_human_review(self):
        """Even a failed run pre-fills the form. Partial data is still useful."""
        llm = ScriptedClient(["garbage", "garbage"])
        result = run_extraction(text=NONSTANDARD_FORM16, llm=llm)
        assert isinstance(result["extracted"], dict)

    def test_trace_records_every_transition(self):
        llm = ScriptedClient(["garbage", GOOD_LLM_JSON])
        result = run_extraction(text=NONSTANDARD_FORM16, llm=llm)
        trace = " ".join(result["trace"])
        assert "escalate: regex -> llm" in trace
        assert "escalate: llm -> llm_verbose" in trace

    def test_strategy_ladder_is_ordered(self):
        assert STRATEGY_LADDER == ("regex", "llm", "llm_verbose")


# --------------------------------------------------------------------------
# reconciliation
# --------------------------------------------------------------------------

class TestReconciliation:
    def test_single_document_has_no_conflicts(self):
        result = run_reconciliation({"form16": {"gross_salary": D("1400000")}})
        assert result["conflicts"] == []
        assert result["merged"]["gross_salary"] == D("1400000")

    def test_26as_wins_for_tds(self):
        """The department's own record beats the employer's certificate."""
        result = run_reconciliation(
            {
                "form16": {"tds_deducted": D("57200")},
                "26as": {"tds_deducted": D("55000")},
            }
        )
        assert result["merged"]["tds_deducted"] == D("55000")
        conflict = next(c for c in result["conflicts"] if c.field == "tds_deducted")
        assert conflict.resolution == "precedence"
        assert conflict.chosen_source == "26as"

    def test_rounding_difference_is_not_a_conflict(self):
        result = run_reconciliation(
            {
                "form16": {"gross_salary": D("1400000")},
                "ais": {"gross_salary": D("1400005")},
            }
        )
        assert result["conflicts"] == []

    def test_ais_surfaces_income_absent_from_form16(self):
        """The whole point of reconciliation: income the user must declare
        but Form 16 never mentions."""
        result = run_reconciliation(
            {
                "form16": {"gross_salary": D("1400000")},
                "ais": {"savings_interest": D("12500"), "fd_interest": D("48000")},
            }
        )
        assert result["merged"]["savings_interest"] == D("12500")
        assert result["merged"]["fd_interest"] == D("48000")

    def test_unresolvable_conflict_goes_to_user_not_guessed(self):
        result = run_reconciliation(
            {
                "form16": {"sec_80c": D("150000")},
                "ais": {"sec_80c": D("90000")},
            }
        )
        assert "sec_80c" in result["needs_user_confirmation"]
        assert "sec_80c" not in result["merged"]  # absent, never guessed

    def test_identical_values_across_docs_merge_cleanly(self):
        result = run_reconciliation(
            {
                "form16": {"pan": "ABCDE1234F"},
                "26as": {"pan": "ABCDE1234F"},
            }
        )
        assert result["conflicts"] == []
        assert result["merged"]["pan"] == "ABCDE1234F"

    def test_conflicting_pan_is_flagged_for_user(self):
        result = run_reconciliation(
            {
                "form16": {"pan": "ABCDE1234F"},
                "26as": {"pan": "ZZZZZ9999Z"},
            }
        )
        assert "pan" in result["needs_user_confirmation"]
