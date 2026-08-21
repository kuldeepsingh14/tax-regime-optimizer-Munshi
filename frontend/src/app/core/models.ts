/**
 * Contracts mirroring the FastAPI schemas.
 *
 * Every money value is a string, not a number. The backend uses Python's
 * Decimal and serialises to string precisely so JavaScript's float doesn't
 * reintroduce the rounding errors the backend went to trouble to avoid.
 * Parse for display only, never for arithmetic.
 */

export type RegimeKey = 'old' | 'new';

export interface TaxLine {
  label: string;
  amount: string;
  section: string | null;
  is_deduction: boolean;
}

export interface RegimeResult {
  regime: RegimeKey;
  name: string;
  lines: TaxLine[];
  taxable_income: string;
  tax_before_rebate: string;
  rebate: string;
  surcharge: string;
  cess: string;
  total_tax: string;
}

export interface Comparison {
  assessment_year: string;
  old: RegimeResult;
  new: RegimeResult;
  recommended: RegimeKey;
  saving: string;
  breakeven_deductions: string;
  current_deductions: string;
}

export interface SalaryInput {
  gross_salary: string;
  basic: string;
  hra_received: string;
  rent_paid: string;
  is_metro: boolean;
}

export interface DeductionsInput {
  sec_80c: string;
  sec_80d_self: string;
  sec_80d_parents: string;
  self_is_senior: boolean;
  parents_are_senior: boolean;
  home_loan_interest: string;
  nps_self_80ccd1b: string;
  nps_employer_80ccd2: string;
  savings_interest_80tta: string;
}

export interface OtherIncomeInput {
  savings_interest: string;
  fd_interest: string;
  other: string;
}

export type AgeCategory = 'default' | 'senior' | 'super_senior';

export interface ComputeRequest {
  assessment_year: string;
  salary: SalaryInput;
  deductions: DeductionsInput;
  other_income: OtherIncomeInput;
  age_category: AgeCategory;
  is_resident: boolean;
}

export interface ExtractedDocument {
  filename: string;
  doc_type: string;
  strategy_used: string;
  attempts: number;
  needs_human_review: boolean;
  validation_errors: string[];
  fields: Record<string, string>;
  trace: string[];
}

export interface Conflict {
  field: string;
  values: Record<string, string>;
  resolution: 'rounding' | 'precedence' | 'user';
  chosen: string | null;
  chosen_source: string | null;
  note: string;
}

export interface Reconciliation {
  merged: Record<string, string>;
  conflicts: Conflict[];
  needs_user_confirmation: string[];
  trace: string[];
}

export interface ExtractResponse {
  documents: ExtractedDocument[];
  reconciliation: Reconciliation | null;
  llm_available: boolean;
  note: string;
}

export interface AnswerSource {
  section: string | null;
  title: string | null;
  score: number;
}

export interface AnswerMeta {
  route: 'law' | 'computation' | 'out_of_scope';
  rewrites: number;
  used_web: boolean;
  grounded: boolean;
}

export const EMPTY_REQUEST: ComputeRequest = {
  assessment_year: '2026-27',
  salary: {
    gross_salary: '',
    basic: '',
    hra_received: '',
    rent_paid: '',
    is_metro: false,
  },
  deductions: {
    sec_80c: '',
    sec_80d_self: '',
    sec_80d_parents: '',
    self_is_senior: false,
    parents_are_senior: false,
    home_loan_interest: '',
    nps_self_80ccd1b: '',
    nps_employer_80ccd2: '',
    savings_interest_80tta: '',
  },
  other_income: { savings_interest: '', fd_interest: '', other: '' },
  age_category: 'default',
  is_resident: true,
};
