import { Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ComputeRequest, EMPTY_REQUEST } from '../core/models';

@Component({
  selector: 'app-tax-form',
  standalone: true,
  imports: [FormsModule],
  template: `
    @if (prefilled()) {
      <p class="prefill-note">
        <span class="prefill-note__badge">Filled in</span>
        <span>
          {{ prefilled() }} figures came from your Form 16. You can compare
          now, or add what Form 16 doesn't show &mdash; rent, home loan interest,
          NPS &mdash; if any of it applies to you.
        </span>
      </p>
    }

    <form (ngSubmit)="submit()" #f="ngForm">
      <fieldset class="group">
        <legend class="group__title">Salary</legend>

        <label class="field field--wide">
          <span class="field__label">Gross salary</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="gross"
              required
              placeholder="14,00,000"
              [ngModel]="model().salary.gross_salary"
              (ngModelChange)="setSalary('gross_salary', $event)"
            />
          </span>
          <span class="field__hint">Total before any deduction, from Part B of Form 16.</span>
        </label>

        <label class="field">
          <span class="field__label">Basic salary</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="basic"
              [ngModel]="model().salary.basic"
              (ngModelChange)="setSalary('basic', $event)"
            />
          </span>
          <span class="field__hint">Needed for the HRA calculation.</span>
        </label>

        <label class="field">
          <span class="field__label">HRA received</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="hra"
              [ngModel]="model().salary.hra_received"
              (ngModelChange)="setSalary('hra_received', $event)"
            />
          </span>
          <span class="field__hint">The allowance itself, not the exempt part.</span>
        </label>

        <label class="field">
          <span class="field__label">Rent paid</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="rent"
              [ngModel]="model().salary.rent_paid"
              (ngModelChange)="setSalary('rent_paid', $event)"
            />
          </span>
          <span class="field__hint">For the year. No rent means no HRA exemption.</span>
        </label>

        @if (hraWithoutRent()) {
          <p class="field-warn">
            <strong>Worth checking.</strong>
            Your Form 16 shows HRA of {{ money(model().salary.hra_received) }},
            but no rent is entered. Without rent there's no HRA exemption, which
            can push the result towards the new regime incorrectly. Leave it at
            zero only if you genuinely pay no rent.
          </p>
        }

        <label class="check check--wide">
          <input
            type="checkbox"
            name="metro"
            [ngModel]="model().salary.is_metro"
            (ngModelChange)="setSalary('is_metro', $event)"
          />
          <span>I rent in Delhi, Mumbai, Kolkata or Chennai</span>
        </label>
      </fieldset>

      <fieldset class="group">
        <legend class="group__title">Deductions</legend>
        <p class="group__note">
          These only count under the old regime, with one exception noted below.
        </p>

        <label class="field">
          <span class="field__label">80C investments</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="c80"
              [ngModel]="model().deductions.sec_80c"
              (ngModelChange)="setDeduction('sec_80c', $event)"
            />
          </span>
          <span class="field__hint">PF, PPF, ELSS, insurance, tuition. Capped at &#8377;1,50,000.</span>
        </label>

        <label class="field">
          <span class="field__label">Health insurance &mdash; you and family</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="d80s"
              [ngModel]="model().deductions.sec_80d_self"
              (ngModelChange)="setDeduction('sec_80d_self', $event)"
            />
          </span>
          <span class="field__hint">Section 80D, up to &#8377;25,000.</span>
        </label>

        <label class="field">
          <span class="field__label">Health insurance &mdash; parents</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="d80p"
              [ngModel]="model().deductions.sec_80d_parents"
              (ngModelChange)="setDeduction('sec_80d_parents', $event)"
            />
          </span>
          <span class="field__hint">Counted separately from your own cover.</span>
        </label>

        <label class="check">
          <input
            type="checkbox"
            name="psenior"
            [ngModel]="model().deductions.parents_are_senior"
            (ngModelChange)="setDeduction('parents_are_senior', $event)"
          />
          <span>A parent is 60 or older &mdash; raises the cap to &#8377;50,000</span>
        </label>

        <label class="field">
          <span class="field__label">Home loan interest</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="hli"
              [ngModel]="model().deductions.home_loan_interest"
              (ngModelChange)="setDeduction('home_loan_interest', $event)"
            />
          </span>
          <span class="field__hint">Self-occupied property is capped at &#8377;2,00,000.</span>
        </label>

        <label class="field">
          <span class="field__label">NPS &mdash; your own contribution</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="nps1"
              [ngModel]="model().deductions.nps_self_80ccd1b"
              (ngModelChange)="setDeduction('nps_self_80ccd1b', $event)"
            />
          </span>
          <span class="field__hint">Section 80CCD(1B), up to &#8377;50,000.</span>
        </label>

        <label class="field field--keep">
          <span class="field__label">
            NPS &mdash; employer contribution
            <span class="tag tag--gain">Kept in new</span>
          </span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="nps2"
              [ngModel]="model().deductions.nps_employer_80ccd2"
              (ngModelChange)="setDeduction('nps_employer_80ccd2', $event)"
            />
          </span>
          <span class="field__hint field__hint--keep">
            The one deduction you keep in the new regime.
          </span>
        </label>
      </fieldset>

      <fieldset class="group">
        <legend class="group__title">Other income</legend>

        <label class="field">
          <span class="field__label">Savings account interest</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="sav"
              [ngModel]="model().other_income.savings_interest"
              (ngModelChange)="setOther('savings_interest', $event)"
            />
          </span>
          <span class="field__hint">Bank passbook total for the year.</span>
        </label>

        <label class="field">
          <span class="field__label">Fixed deposit interest</span>
          <span class="field__control">
            <span class="field__prefix">&#8377;</span>
            <input
              class="field__input field__input--money"
              type="text"
              inputmode="numeric"
              name="fd"
              [ngModel]="model().other_income.fd_interest"
              (ngModelChange)="setOther('fd_interest', $event)"
            />
          </span>
          <span class="field__hint">Taxable in full under both regimes.</span>
        </label>

        <label class="field">
          <span class="field__label">Age</span>
          <select
            class="field__input"
            name="age"
            [ngModel]="model().age_category"
            (ngModelChange)="setAge($event)"
          >
            <option value="default">Under 60</option>
            <option value="senior">60 to 79</option>
            <option value="super_senior">80 or older</option>
          </select>
          <span class="field__hint">Changes the old regime's exempt threshold only.</span>
        </label>
      </fieldset>

      <div class="actions">
        <button class="btn btn--primary btn--go" type="submit" [disabled]="busy() || !hasSalary()">
          {{ busy() ? 'Computing…' : 'Compare both regimes' }}
        </button>
        <button class="btn btn--quiet" type="button" (click)="reset()">Clear</button>

        @if (!hasSalary()) {
          <span class="actions__hint">
            Enter your gross salary above &mdash; it's the only figure required.
          </span>
        }
      </div>
    </form>
  `,
  styles: [
    `
      :host { display: block; }

      .prefill-note {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: 0.6rem;
        border: 1px solid var(--gain-bright);
        border-left: 4px solid var(--gain);
        background: var(--gain-soft);
        padding: 0.8rem 1rem;
        margin: 0 0 1.5rem;
        border-radius: var(--r-sm);
        font-size: 0.88rem;
        line-height: 1.55;
        color: var(--ink);
      }
      .prefill-note span:last-child { flex: 1; min-width: 16rem; }
      .prefill-note__badge {
        font-family: var(--mono);
        font-size: 0.64rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #fff;
        background: var(--gain);
        padding: 0.2rem 0.5rem;
        border-radius: 999px;
        flex: none;
      }

      .group {
        border: 1px solid var(--rule);
        border-top: 3px solid var(--stamp);
        background: var(--surface);
        border-radius: var(--r-md);
        box-shadow: var(--shadow-sm);
        padding: 1.5rem 1.35rem 1.4rem;
        margin: 0 0 1.25rem;
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
        gap: 1.15rem 1.5rem;
        align-items: start;
      }
      .group__title {
        grid-column: 1 / -1;
        font-family: var(--mono);
        font-size: 0.7rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--stamp);
        font-weight: 600;
        padding: 0;
        margin-bottom: 0.5rem;
      }
      .group__note {
        grid-column: 1 / -1;
        margin: -0.35rem 0 0;
        font-size: 0.85rem;
        color: var(--muted);
        line-height: 1.5;
      }

      .field--wide { grid-column: 1 / -1; max-width: 22rem; }
      .field__label { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

      .field--keep .field__input { border-color: var(--gain-bright); background: #FCFEFD; }
      .field--keep .field__input:focus {
        border-color: var(--gain);
        box-shadow: 0 0 0 3px var(--gain-soft);
      }
      .field__hint--keep { color: var(--gain); font-weight: 500; }

      .check--wide { grid-column: 1 / -1; max-width: 32rem; }

      .field-warn {
        grid-column: 1 / -1;
        border: 1px solid var(--brass-bright);
        border-left: 4px solid var(--brass);
        background: var(--brass-soft);
        padding: 0.75rem 0.95rem;
        margin: 0;
        border-radius: var(--r-sm);
        font-size: 0.84rem;
        line-height: 1.55;
        color: var(--ink);
      }
      .field-warn strong { color: var(--brass); }

      .actions {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        align-items: center;
        border-top: 1px solid var(--rule);
        padding-top: 1.35rem;
        margin-top: 0.25rem;
      }
      .btn--go { font-size: 0.95rem; padding: 0.7rem 1.5rem; }
      .actions__hint {
        font-size: 0.8rem;
        color: var(--muted);
        line-height: 1.4;
      }
    `,
  ],
})
export class TaxFormComponent {
  readonly prefill = input<Record<string, string> | null>(null);
  readonly busy = input(false);
  readonly compute = output<ComputeRequest>();

  readonly model = signal<ComputeRequest>(structuredClone(EMPTY_REQUEST));
  readonly prefilled = signal(0);

  constructor() {
    // Carry extracted figures into the form without overwriting anything the
    // person has already typed themselves.
    effect(() => {
      const fields = this.prefill();
      if (!fields) return;

      this.model.update((current) => {
        const next = structuredClone(current);
        const take = (key: string) => fields[key] ?? '';

        if (!next.salary.gross_salary) next.salary.gross_salary = take('gross_salary');
        if (!next.salary.basic) next.salary.basic = take('basic');
        if (!next.salary.hra_received) next.salary.hra_received = take('hra_received');
        if (!next.deductions.sec_80c) next.deductions.sec_80c = take('sec_80c');
        if (!next.deductions.sec_80d_self) next.deductions.sec_80d_self = take('sec_80d');
        return next;
      });

      this.prefilled.set(Object.keys(fields).length);
    // Angular blocks signal writes inside effects by default (NG0600), so
    // without this the whole prefill throws silently and the form stays empty.
    }, { allowSignalWrites: true });
  }

  hraWithoutRent(): boolean {
    const s = this.model().salary;
    return Number(s.hra_received) > 0 && Number(s.rent_paid) <= 0;
  }

  money(value: string): string {
    const amount = Number(value);
    return Number.isFinite(amount) && amount > 0
      ? '₹' + amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })
      : '₹0';
  }

  hasSalary(): boolean {
    return Number(this.model().salary.gross_salary) > 0;
  }

  setSalary(key: string, value: unknown): void {
    this.model.update((m) => ({ ...m, salary: { ...m.salary, [key]: value } as any }));
  }

  setDeduction(key: string, value: unknown): void {
    this.model.update((m) => ({
      ...m,
      deductions: { ...m.deductions, [key]: value } as any,
    }));
  }

  setOther(key: string, value: unknown): void {
    this.model.update((m) => ({
      ...m,
      other_income: { ...m.other_income, [key]: value } as any,
    }));
  }

  setAge(value: any): void {
    this.model.update((m) => ({ ...m, age_category: value }));
  }

  reset(): void {
    this.model.set(structuredClone(EMPTY_REQUEST));
    this.prefilled.set(0);
  }

  submit(): void {
    if (this.hasSalary()) this.compute.emit(this.model());
  }
}
