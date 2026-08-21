import { Component, computed, input } from '@angular/core';
import { Comparison, TaxLine } from '../core/models';

interface LedgerRow {
  label: string;
  section: string | null;
  old: string | null;
  new: string | null;
  isDeduction: boolean;
  isTotal: boolean;
  /** Allowed in the old regime, forgone in the new one. */
  forgone: boolean;
}

const TOTAL_LABELS = new Set(['Taxable income', 'Total tax payable']);

@Component({
  selector: 'app-ledger',
  standalone: true,
  template: `
    <section class="verdict" [class.verdict--old]="c().recommended === 'old'">
      <p class="verdict__eyebrow kicker">Assessment year {{ c().assessment_year }}</p>
      <h2 class="verdict__headline">
        <span class="verdict__regime">{{ recommendedName() }}</span>
        saves you
        <span class="verdict__amount">{{ money(c().saving) }}</span>
      </h2>
      <p class="verdict__sub">{{ breakevenNote() }}</p>
    </section>

    <div class="ledger" role="table" aria-label="Side-by-side tax computation">
      <div class="ledger__head" role="row">
        <span role="columnheader">Particulars</span>
        <span
          role="columnheader"
          class="num"
          [class.col--won]="c().recommended === 'old'"
        >Old regime</span>
        <span
          role="columnheader"
          class="num"
          [class.col--won]="c().recommended === 'new'"
        >New regime</span>
      </div>

      @for (row of rows(); track row.label + row.section) {
        <div
          class="ledger__row"
          role="row"
          [class.row--total]="row.isTotal"
          [class.row--deduction]="row.isDeduction"
        >
          <span class="cell cell--label" role="cell">
            {{ row.label }}
            @if (row.section) {
              <em class="sec">{{ row.section }}</em>
            }
          </span>

          <span class="cell num" role="cell" [class.cell--won]="c().recommended === 'old'">
            @if (row.old !== null) {
              {{ signed(row) }}
            } @else {
              <span class="dash" aria-label="not applicable">&mdash;</span>
            }
          </span>

          <span
            class="cell num"
            role="cell"
            [class.cell--forgone]="row.forgone"
            [class.cell--won]="c().recommended === 'new'"
          >
            @if (row.new !== null) {
              {{ signedNew(row) }}
            } @else if (row.forgone) {
              <s [attr.aria-label]="'forgone: ' + money(row.old!)">{{ money(row.old!) }}</s>
            } @else {
              <span class="dash" aria-label="not applicable">&mdash;</span>
            }
          </span>
        </div>
      }
    </div>

    @if (forgoneTotal() !== '0') {
      <p class="forgone-note">
        Struck-through figures are deductions the new regime doesn't allow &mdash;
        <strong>{{ money(forgoneTotal()) }}</strong> you'd give up by switching.
      </p>
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }

      /* ---- verdict ---- */
      .verdict {
        border: 1px solid var(--rule);
        border-top: 4px solid var(--stamp);
        background: linear-gradient(165deg, var(--surface), var(--stamp-soft));
        padding: 1.85rem 1.75rem 1.75rem;
        margin-bottom: 2.25rem;
        border-radius: var(--r-md);
        box-shadow: var(--shadow-md);
      }
      .verdict--old {
        border-top-color: var(--brass);
        background: linear-gradient(165deg, var(--surface), var(--brass-soft));
      }
      .verdict__eyebrow {
        color: var(--brass);
        margin: 0 0 0.85rem;
        font-weight: 600;
      }
      .verdict--old .verdict__eyebrow {
        color: var(--stamp);
      }
      .verdict__headline {
        font-family: var(--display);
        font-weight: 700;
        font-size: clamp(1.55rem, 4.5vw, 2.5rem);
        line-height: 1.2;
        margin: 0;
        letter-spacing: -0.015em;
      }
      .verdict__regime {
        font-weight: 700;
      }
      .verdict__amount {
        font-family: var(--mono);
        font-weight: 600;
        color: var(--gain);
        font-feature-settings: 'tnum';
        white-space: nowrap;
      }
      .verdict__sub {
        margin: 0.9rem 0 0;
        color: var(--muted);
        max-width: 52ch;
        font-size: 0.94rem;
        line-height: 1.55;
      }

      /* ---- ledger ---- */
      .ledger {
        border: 1px solid var(--rule);
        border-top: 2px solid var(--ink);
        background: var(--surface);
        border-radius: var(--r-md);
        box-shadow: var(--shadow-sm);
        overflow: hidden;
      }
      .ledger__head,
      .ledger__row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 8.5rem 8.5rem;
        gap: 0.5rem;
        padding: 0 1rem;
        align-items: baseline;
      }
      /* Vertical padding lives on the cell, not the row, so the winning
         column's tint runs the full height of every row without gaps. */
      .ledger__head > span,
      .cell {
        padding-block: 0.62rem;
      }
      .ledger__head {
        border-bottom: 1px solid var(--ink);
        font-family: var(--mono);
        font-size: 0.68rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
        position: sticky;
        top: 0;
        background: var(--surface);
        z-index: 1;
      }
      .col--won {
        color: var(--stamp);
        font-weight: 600;
      }
      /* The side box-shadows bleed the tint across the grid gap so the column
         reads as one band rather than a stack of chips. */
      .cell--won {
        background: var(--stamp-soft);
        box-shadow: -0.25rem 0 0 var(--stamp-soft), 0.25rem 0 0 var(--stamp-soft);
      }
      .ledger__row + .ledger__row {
        border-top: 1px solid var(--rule);
      }
      .ledger__row {
        transition: background 0.12s;
      }
      .ledger__row:hover {
        background: var(--tint);
      }
      .row--total {
        border-top: 3px double var(--ink) !important;
        font-weight: 600;
        background: var(--tint);
      }
      .row--total:hover {
        background: var(--tint);
      }
      .cell--label {
        font-size: 0.93rem;
      }
      .row--deduction .cell--label {
        padding-left: 1rem;
        color: var(--muted);
      }
      .sec {
        font-family: var(--mono);
        font-style: normal;
        font-size: 0.68rem;
        color: var(--muted);
        margin-left: 0.45rem;
        border: 1px solid var(--rule);
        padding: 0.05rem 0.3rem;
        border-radius: 2px;
        white-space: nowrap;
      }
      .num {
        font-family: var(--mono);
        font-variant-numeric: tabular-nums;
        font-feature-settings: 'tnum';
        text-align: right;
        font-size: 0.88rem;
      }
      .dash {
        color: var(--rule-dark);
      }
      .cell--forgone s {
        color: var(--levy);
        opacity: 0.65;
        text-decoration-thickness: 1px;
      }

      .forgone-note {
        margin: 1rem 0 0;
        font-size: 0.87rem;
        color: var(--muted);
        line-height: 1.5;
        max-width: 60ch;
      }
      .forgone-note strong {
        font-family: var(--mono);
        color: var(--levy);
      }

      @media (max-width: 620px) {
        .ledger__head,
        .ledger__row {
          grid-template-columns: minmax(0, 1fr) 6.2rem 6.2rem;
          padding: 0 0.65rem;
          gap: 0.35rem;
        }
        .ledger__head > span,
        .cell {
          padding-block: 0.5rem;
        }
        .num {
          font-size: 0.78rem;
        }
        .cell--label {
          font-size: 0.85rem;
        }
      }
    `,
  ],
})
export class LedgerComponent {
  readonly c = input.required<Comparison>();

  readonly recommendedName = computed(() =>
    this.c().recommended === 'old' ? 'Old regime' : 'New regime',
  );

  /**
   * Merge both computation trails into aligned rows.
   *
   * The design thesis: a deduction the old regime granted and the new regime
   * refuses still gets a row, struck through. The absence is the information —
   * it's what you give up, and no calculator shows it.
   */
  readonly rows = computed<LedgerRow[]>(() => {
    const comparison = this.c();
    const oldLines = comparison.old.lines;
    const newLines = comparison.new.lines;

    const newByLabel = new Map<string, TaxLine>();
    newLines.forEach((line) => newByLabel.set(line.label, line));

    const seen = new Set<string>();
    const rows: LedgerRow[] = [];

    for (const line of oldLines) {
      seen.add(line.label);
      const counterpart = newByLabel.get(line.label);
      rows.push({
        label: line.label,
        section: line.section,
        old: line.amount,
        new: counterpart ? counterpart.amount : null,
        isDeduction: line.is_deduction,
        isTotal: TOTAL_LABELS.has(line.label),
        forgone: line.is_deduction && !counterpart,
      });
    }

    // Rows the new regime has and the old one doesn't (e.g. its rebate).
    for (const line of newLines) {
      if (seen.has(line.label)) continue;
      rows.push({
        label: line.label,
        section: line.section,
        old: null,
        new: line.amount,
        isDeduction: line.is_deduction,
        isTotal: TOTAL_LABELS.has(line.label),
        forgone: false,
      });
    }

    return rows;
  });

  readonly forgoneTotal = computed(() =>
    this.rows()
      .filter((r) => r.forgone)
      .reduce((sum, r) => sum + Number(r.old ?? 0), 0)
      .toString(),
  );

  readonly breakevenNote = computed(() => {
    const comparison = this.c();
    const breakeven = Number(comparison.breakeven_deductions);
    const current = Number(comparison.current_deductions);

    if (breakeven <= 0) {
      return 'The old regime wins here even with no deductions at all.';
    }
    if (current >= breakeven) {
      const margin = current - breakeven;
      return `You're claiming ${this.money(String(current))} in deductions — ${this.money(
        String(margin),
      )} past the ${this.money(String(breakeven))} the old regime needs to win.`;
    }
    const gap = breakeven - current;
    return `The old regime would need ${this.money(
      String(breakeven),
    )} in deductions to win. You're at ${this.money(String(current))} — ${this.money(
      String(gap),
    )} short.`;
  });

  signed(row: LedgerRow): string {
    const value = this.money(row.old!);
    return row.isDeduction ? `(${value})` : value;
  }

  signedNew(row: LedgerRow): string {
    const value = this.money(row.new!);
    return row.isDeduction ? `(${value})` : value;
  }

  /** Indian digit grouping: 14,00,000 not 1,400,000. */
  money(value: string): string {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return value;
    return '₹' + amount.toLocaleString('en-IN', { maximumFractionDigits: 0 });
  }
}
