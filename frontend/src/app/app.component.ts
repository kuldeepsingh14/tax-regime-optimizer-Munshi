import { Component, inject, signal } from '@angular/core';
import { ApiService } from './core/api.service';
import { Comparison, ComputeRequest } from './core/models';
import { ChatComponent } from './components/chat.component';
import { LedgerComponent } from './components/ledger.component';
import { TaxFormComponent } from './components/tax-form.component';
import { UploaderComponent } from './components/uploader.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [UploaderComponent, TaxFormComponent, LedgerComponent, ChatComponent],
  template: `
    <header class="masthead">
      <div class="masthead__texture" aria-hidden="true"></div>
      <div class="shell masthead__inner">
        <p class="masthead__mark">
          <span class="masthead__mark-old">Old</span>
          <span class="masthead__mark-slash">/</span>
          <span class="masthead__mark-new">New</span>
        </p>
        <h1 class="masthead__title">Which regime costs you less</h1>
        <p class="masthead__lede">
          Both regimes computed to the rupee for assessment year 2026&ndash;27,
          with every line shown. Upload your Form 16 or type the figures in.
        </p>
      </div>
      <div class="rule--brass"></div>
    </header>

    <main class="shell">
      @if (api.waking()) {
        <p class="alert" role="status">
          Waking the server. The free tier sleeps when idle, so this first
          request takes up to a minute.
        </p>
      }

      <section class="step">
        <h2 class="step__title"><span class="step__n">1</span> Your figures</h2>
        <app-uploader (extracted)="onExtracted($event)" />
        <app-tax-form
          id="figures"
          [prefill]="prefill()"
          [busy]="computing()"
          (compute)="run($event)"
        />
      </section>

      @if (error()) {
        <p class="alert alert--bad" role="alert">{{ error() }}</p>
      }

      @if (result(); as comparison) {
        <section class="step" id="result">
          <h2 class="step__title"><span class="step__n">2</span> The comparison</h2>
          <app-ledger [c]="comparison" />
        </section>
      }

    </main>

    <app-chat />

    <footer class="footer">
      <div class="rule--brass"></div>
      <div class="shell footer__inner">
        <p class="footer__mark">Old&nbsp;/&nbsp;New</p>
        <p>
          Rates as amended by the Finance Act 2026. This is a calculator, not
          tax advice &mdash; check anything consequential with a professional.
        </p>
        <p class="footer__privacy">
          Documents are read in memory and discarded. Nothing you enter is stored.
        </p>
        <p class="footer__copyright">
          &copy; {{ year }} Kuldeep Singh
        </p>
      </div>
    </footer>
  `,
  styles: [
    `
      .masthead {
        position: relative;
        background: linear-gradient(165deg, var(--ink) 0%, var(--ink-deep) 100%);
        padding: 4.5rem 0 3.5rem;
        overflow: hidden;
      }
      .masthead__texture {
        position: absolute;
        inset: 0;
        background-image: repeating-linear-gradient(
          115deg,
          rgba(246, 243, 234, 0.05) 0px,
          rgba(246, 243, 234, 0.05) 1px,
          transparent 1px,
          transparent 64px
        );
        pointer-events: none;
      }
      .masthead__inner {
        position: relative;
      }
      .masthead__mark {
        font-family: var(--mono);
        font-size: 0.72rem;
        letter-spacing: 0.24em;
        text-transform: uppercase;
        margin: 0 0 1.4rem;
        display: flex;
        gap: 0.5rem;
        align-items: center;
      }
      .masthead__mark-old {
        color: var(--brass-bright);
      }
      .masthead__mark-slash {
        color: var(--on-dark-rule);
      }
      .masthead__mark-new {
        color: var(--on-dark);
      }
      .masthead__title {
        font-family: var(--display);
        font-weight: 700;
        color: var(--on-dark);
        font-size: clamp(2.1rem, 6vw, 3.4rem);
        line-height: 1.06;
        letter-spacing: -0.02em;
        margin: 0;
        max-width: 16ch;
      }
      .masthead__lede {
        margin: 1.15rem 0 0;
        max-width: 54ch;
        color: var(--on-dark-muted);
        line-height: 1.65;
        font-size: 1.02rem;
      }

      main {
        padding: 2.5rem 0 4rem;
        display: grid;
        gap: 3rem;
      }
      .step__title {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font-family: var(--display);
        font-weight: 600;
        font-size: 1.35rem;
        margin: 0 0 1.4rem;
        padding-bottom: 0.7rem;
        border-bottom: 1px solid var(--rule);
        position: relative;
      }
      .step__title::after {
        content: '';
        position: absolute;
        left: 0;
        bottom: -1px;
        width: 3.5rem;
        height: 3px;
        border-radius: 2px;
        background: linear-gradient(90deg, var(--stamp), var(--brass));
      }
      .step__n {
        font-family: var(--mono);
        font-weight: 600;
        font-size: 0.75rem;
        color: #fff;
        background: linear-gradient(165deg, var(--stamp-bright), var(--stamp));
        box-shadow: var(--shadow-sm);
        width: 1.75rem;
        height: 1.75rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        flex: none;
      }
      app-uploader {
        display: block;
        margin-bottom: 2rem;
      }

      .footer {
        background: var(--ink-deep);
        /* Extra bottom room so the fixed chat launcher never sits on top of
           the privacy line. */
        padding: 2.25rem 0 6rem;
        font-size: 0.82rem;
        color: var(--on-dark-muted);
        line-height: 1.6;
        margin-top: 1rem;
      }
      .footer__inner {
        padding-top: 1.75rem;
      }
      .footer__mark {
        font-family: var(--mono);
        font-size: 0.66rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
        color: var(--brass-bright);
        margin: 0 0 1rem;
      }
      .footer__copyright {
        margin-top: 1.25rem;
        padding-top: 1rem;
        border-top: 1px solid rgb(255 255 255 / 0.1);
        font-size: 0.78rem;
        opacity: 0.75;
      }
      .footer p {
        margin: 0 0 0.5rem;
        max-width: 60ch;
      }
      .footer__privacy {
        color: var(--gain-on-dark);
      }
    `,
  ],
})
export class AppComponent {
  readonly api = inject(ApiService);

  /** Rendered in the footer copyright, so it never goes stale. */
  readonly year = new Date().getFullYear();

  readonly prefill = signal<Record<string, string> | null>(null);
  readonly result = signal<Comparison | null>(null);
  readonly computing = signal(false);
  readonly error = signal<string | null>(null);

  constructor() {
    void this.api.warm();
  }

  onExtracted(fields: Record<string, string>): void {
    this.prefill.set(fields);
    // Extraction succeeding is invisible if the filled form is below the fold.
    queueMicrotask(() =>
      document.getElementById('figures')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
    );
  }

  async run(request: ComputeRequest): Promise<void> {
    this.computing.set(true);
    this.error.set(null);
    try {
      this.result.set(await this.api.compute(request));
      queueMicrotask(() =>
        document.getElementById('result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      );
    } catch (e) {
      this.error.set(
        e instanceof Error ? e.message : 'Could not compute that. Check the figures and try again.',
      );
    } finally {
      this.computing.set(false);
    }
  }
}
