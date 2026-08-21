import { Component, inject, output, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { ExtractResponse } from '../core/models';

@Component({
  selector: 'app-uploader',
  standalone: true,
  template: `
    <div
      class="drop"
      [class.drop--over]="dragging()"
      [class.drop--busy]="busy()"
      [class.drop--done]="result() && !error()"
      (dragover)="$event.preventDefault(); dragging.set(true)"
      (dragleave)="dragging.set(false)"
      (drop)="onDrop($event)"
    >
      <input
        #picker
        type="file"
        accept="application/pdf"
        multiple
        hidden
        (change)="onPick($event)"
      />

      <span class="drop__icon" aria-hidden="true">
        @if (busy()) {
          <span class="spinner"></span>
        } @else if (result() && !error()) {
          &#10003;
        } @else {
          &#8595;
        }
      </span>

      <p class="drop__title">
        {{ result() && !error() ? 'Form 16 read' : 'Start from your Form 16' }}
      </p>
      <p class="drop__body">
        Drop the PDF here and the figures fill themselves in. Add your AIS or
        26AS too and disagreements between them get flagged.
      </p>

      <button type="button" class="btn" (click)="picker.click()" [disabled]="busy()">
        {{ busy() ? 'Reading…' : result() ? 'Choose a different PDF' : 'Choose PDF' }}
      </button>

      <p class="drop__note">
        Nothing is stored. Files are read in memory and discarded when the
        response is sent.
      </p>
    </div>

    @if (error()) {
      <p class="alert alert--bad" role="alert">{{ error() }}</p>
    }

    @if (result(); as r) {
      <div class="report">
        @for (doc of r.documents; track doc.filename) {
          <div class="doc" [class.doc--flagged]="doc.needs_human_review">
            <div class="doc__head">
              <span class="doc__name">{{ doc.filename }}</span>
              <span class="tag">{{ label(doc.doc_type) }}</span>
              <span class="tag tag--quiet">{{ strategyLabel(doc.strategy_used) }}</span>
            </div>

            @if (doc.needs_human_review) {
              <p class="doc__msg">
                Some figures didn't come through cleanly. Fill in what's missing
                below &mdash; everything found so far has been carried over.
              </p>
              <ul class="errs">
                @for (e of doc.validation_errors; track e) {
                  <li>{{ e }}</li>
                }
              </ul>
            } @else {
              <p class="doc__msg doc__msg--ok">
                {{ count(doc.fields) }} figures read. Check them below before computing.
              </p>
            }
          </div>
        }

        @if (r.reconciliation; as rec) {
          @if (rec.conflicts.length) {
            <div class="conflicts">
              <h3 class="conflicts__title">Your documents disagree</h3>
              @for (c of rec.conflicts; track c.field) {
                <div class="conflict">
                  <span class="conflict__field">{{ pretty(c.field) }}</span>
                  <span class="conflict__values">
                    @for (entry of pairs(c.values); track entry[0]) {
                      <span class="src">
                        <em>{{ label(entry[0]) }}</em> {{ money(entry[1]) }}
                      </span>
                    }
                  </span>
                  @if (c.resolution === 'precedence') {
                    <span class="conflict__fix">Using {{ label(c.chosen_source!) }} &mdash; {{ c.note }}</span>
                  } @else {
                    <span class="conflict__fix conflict__fix--you">
                      You'll need to decide this one. Enter the right figure below.
                    </span>
                  }
                </div>
              }
            </div>
          }
        }

        <button type="button" class="btn btn--gain next" (click)="goToFigures()">
          Review your figures &#8595;
        </button>
      </div>
    }
  `,
  styles: [
    `
      :host { display: block; }

      .drop {
        border: 2px dashed var(--rule-dark);
        background: linear-gradient(165deg, var(--surface), var(--tint));
        padding: 2.25rem 1.5rem;
        text-align: center;
        border-radius: var(--r-lg);
        transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
      }
      .drop--over {
        border-color: var(--stamp-bright);
        border-style: solid;
        background: var(--stamp-soft);
        box-shadow: var(--shadow-md);
      }
      .drop--done {
        border-color: var(--gain-bright);
        border-style: solid;
        background: linear-gradient(165deg, var(--surface), var(--gain-soft));
      }
      .drop--busy { border-color: var(--stamp-bright); }

      .drop__icon {
        width: 3rem;
        height: 3rem;
        margin: 0 auto 0.9rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: var(--stamp-soft);
        color: var(--stamp);
        font-size: 1.35rem;
        font-weight: 600;
      }
      .drop--done .drop__icon { background: var(--gain); color: #fff; }

      .spinner {
        width: 1.2rem;
        height: 1.2rem;
        border: 2px solid var(--stamp-soft);
        border-top-color: var(--stamp);
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
      }
      @keyframes spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 2s; } }

      .drop__title {
        font-family: var(--display);
        font-size: 1.2rem;
        font-weight: 600;
        margin: 0 0 0.5rem;
      }
      .drop__body {
        margin: 0 auto 1.25rem;
        max-width: 46ch;
        color: var(--muted);
        font-size: 0.92rem;
        line-height: 1.6;
      }
      .drop__note {
        margin: 1rem auto 0;
        max-width: 44ch;
        font-size: 0.78rem;
        color: var(--muted);
        line-height: 1.5;
      }

      .report {
        margin-top: 1.25rem;
        display: grid;
        gap: 0.75rem;
        justify-items: start;
      }
      .doc {
        width: 100%;
        border: 1px solid var(--rule);
        border-left: 4px solid var(--gain);
        padding: 0.9rem 1rem;
        background: var(--surface);
        border-radius: var(--r-sm);
        box-shadow: var(--shadow-sm);
      }
      .doc--flagged { border-left-color: var(--brass); }
      .doc__head {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        align-items: center;
        margin-bottom: 0.45rem;
      }
      .doc__name { font-weight: 600; font-size: 0.92rem; }
      .doc__msg {
        margin: 0;
        font-size: 0.88rem;
        color: var(--muted);
        line-height: 1.5;
      }
      .doc__msg--ok { color: var(--gain); font-weight: 500; }
      .errs {
        margin: 0.5rem 0 0;
        padding-left: 1.1rem;
        font-size: 0.82rem;
        color: var(--muted);
        line-height: 1.5;
      }

      .conflicts {
        width: 100%;
        border: 1px solid var(--brass-bright);
        border-left: 4px solid var(--brass);
        background: var(--brass-soft);
        padding: 1rem;
        border-radius: var(--r-sm);
      }
      .conflicts__title {
        font-family: var(--display);
        font-size: 1rem;
        margin: 0 0 0.75rem;
        color: var(--brass);
      }
      .conflict { display: grid; gap: 0.3rem; padding: 0.55rem 0; }
      .conflict + .conflict { border-top: 1px solid rgba(168, 121, 26, 0.25); }
      .conflict__field { font-weight: 600; font-size: 0.9rem; }
      .conflict__values { display: flex; flex-wrap: wrap; gap: 0.9rem; }
      .src {
        font-family: var(--mono);
        font-size: 0.82rem;
        font-variant-numeric: tabular-nums;
      }
      .src em { font-style: normal; color: var(--muted); margin-right: 0.3rem; }
      .conflict__fix { font-size: 0.82rem; color: var(--gain); }
      .conflict__fix--you { color: var(--levy); font-weight: 500; }

      .next { margin-top: 0.25rem; }
    `,
  ],
})
export class UploaderComponent {
  private readonly api = inject(ApiService);

  readonly extracted = output<Record<string, string>>();

  readonly busy = signal(false);
  readonly dragging = signal(false);
  readonly error = signal<string | null>(null);
  readonly result = signal<ExtractResponse | null>(null);

  onPick(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) this.send(Array.from(input.files));
    input.value = '';
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []).filter(
      (f) => f.type === 'application/pdf',
    );
    if (files.length) this.send(files);
    else this.error.set('Only PDF files can be read. Try your Form 16 PDF.');
  }

  goToFigures(): void {
    document.getElementById('figures')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  private async send(files: File[]): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      const response = await this.api.extract(files.slice(0, 3));
      this.result.set(response);

      // Reconciled values win where present; otherwise take the first document.
      const merged = response.reconciliation?.merged ?? {};
      const single = response.documents[0]?.fields ?? {};
      this.extracted.emit({ ...single, ...merged });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Could not read that file.');
    } finally {
      this.busy.set(false);
    }
  }

  count(fields: Record<string, string>): number {
    return Object.keys(fields).length;
  }

  pairs(values: Record<string, string>): [string, string][] {
    return Object.entries(values);
  }

  label(docType: string): string {
    return (
      { form16: 'Form 16', ais: 'AIS', '26as': 'Form 26AS', unknown: 'Unrecognised' }[
        docType
      ] ?? docType
    );
  }

  strategyLabel(strategy: string): string {
    return (
      { regex: 'read directly', llm: 'read by model', llm_verbose: 'read by model, 2nd pass' }[
        strategy
      ] ?? strategy
    );
  }

  pretty(field: string): string {
    return field.replace(/_/g, ' ').replace(/\bsec /, 'Section ');
  }

  money(value: string): string {
    const amount = Number(value);
    return Number.isFinite(amount)
      ? '₹' + amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })
      : value;
  }
}
