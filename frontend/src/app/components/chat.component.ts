import { Component, ElementRef, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { AnswerMeta, AnswerSource } from '../core/models';

interface Turn {
  role: 'you' | 'assistant';
  text: string;
  meta?: AnswerMeta;
  sources?: AnswerSource[];
  failed?: boolean;
}

const SUGGESTIONS = [
  'Can I claim HRA and home loan interest together?',
  'What survives into the new regime?',
  'How does marginal relief work above ₹12 lakh?',
];

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [FormsModule],
  host: { '(document:keydown.escape)': 'isOpen.set(false)' },
  template: `
    <button
      type="button"
      class="launcher"
      [class.launcher--hidden]="isOpen()"
      (click)="isOpen.set(true)"
      aria-label="Ask Munshi about tax law"
    >
      <span class="launcher__avatar" aria-hidden="true">M</span>
      <span class="launcher__text">
        <span class="launcher__name">Ask Munshi</span>
        <span class="launcher__sub">Questions about the law</span>
      </span>
    </button>

    @if (isOpen()) {
      <div class="panel" role="dialog" aria-label="Munshi, the tax law assistant">
        <header class="panel__head">
          <span class="panel__avatar" aria-hidden="true">M</span>
          <div class="panel__id">
            <p class="panel__title">Munshi</p>
            <p class="panel__sub">Answers cite the section they come from</p>
          </div>
          <button
            type="button"
            class="panel__close"
            (click)="isOpen.set(false)"
            aria-label="Close"
          >&times;</button>
        </header>

        <div class="panel__log" #log>
          @if (!turns().length) {
            <p class="empty">
              I read the Income-tax Act, not your figures. Ask about deductions,
              exemptions, or what each regime allows.
            </p>
            <div class="suggestions">
              @for (s of suggestions; track s) {
                <button type="button" class="chip" (click)="ask(s)">{{ s }}</button>
              }
            </div>
          }

          @for (turn of turns(); track $index) {
            <div class="turn" [class.turn--you]="turn.role === 'you'">
              <div
                class="bubble"
                [class.bubble--you]="turn.role === 'you'"
                [class.bubble--failed]="turn.failed"
              >
                {{ turn.text }}@if (turn.role === 'assistant' && streaming() && $last) {
                  <span class="caret" aria-hidden="true"></span>
                }
              </div>

              @if (turn.meta?.route === 'computation') {
                <p class="hint">That one's a calculation &mdash; use the form on the page.</p>
              }

              @if (turn.sources?.length) {
                <div class="sources">
                  @for (s of turn.sources!; track s.section) {
                    @if (s.section) {
                      <span class="src">{{ s.section }}</span>
                    }
                  }
                  @if (turn.meta?.rewrites) {
                    <span class="src src--note">reworded {{ turn.meta!.rewrites }}&times;</span>
                  }
                  @if (turn.meta?.used_web) {
                    <span class="src src--note">web</span>
                  }
                </div>
              }
            </div>
          }
        </div>

        <form class="composer" (ngSubmit)="ask(draft())">
          <input
            #qinput
            class="composer__input"
            name="q"
            [ngModel]="draft()"
            (ngModelChange)="draft.set($event)"
            placeholder="Ask about a section or deduction"
            autocomplete="off"
            [disabled]="streaming()"
          />
          @if (streaming()) {
            <button type="button" class="composer__btn composer__btn--stop" (click)="stop()">
              Stop
            </button>
          } @else {
            <button class="composer__btn" type="submit" [disabled]="!draft().trim()">Ask</button>
          }
        </form>
      </div>
    }
  `,
  styles: [
    `
      /* ---- launcher ---- */
      .launcher {
        position: fixed;
        right: 1.5rem;
        bottom: 1.5rem;
        z-index: 40;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font: inherit;
        text-align: left;
        background: linear-gradient(165deg, var(--ink), var(--ink-deep));
        color: var(--on-dark);
        border: 1px solid rgba(214, 167, 58, 0.32);
        padding: 0.6rem 1.4rem 0.6rem 0.6rem;
        border-radius: 999px;
        cursor: pointer;
        /* Layered rather than a ::before: .launcher is fixed with z-index, so
           it forms a stacking context and a negative-z-index child would paint
           above its own background instead of behind it. The last two layers
           are the warm halo; the first is ordinary drop shadow. */
        box-shadow:
          0 10px 28px rgba(12, 23, 41, 0.34),
          0 0 20px 3px rgba(214, 167, 58, 0.38),
          0 0 44px 12px rgba(214, 167, 58, 0.18);
        animation: halo 3s ease-in-out infinite;
        transition: transform 0.18s, opacity 0.2s, filter 0.18s;
      }
      /* Base rule carries a static halo, so when reduced-motion collapses the
         animation the glow stays put instead of vanishing. */
      @keyframes halo {
        50% {
          box-shadow:
            0 10px 28px rgba(12, 23, 41, 0.34),
            0 0 28px 7px rgba(214, 167, 58, 0.55),
            0 0 62px 18px rgba(214, 167, 58, 0.28);
        }
      }
      .launcher:hover {
        transform: translateY(-2px) scale(1.02);
        filter: brightness(1.1);
      }
      .launcher--hidden {
        opacity: 0;
        pointer-events: none;
        transform: scale(0.9);
        animation: none;
      }
      .launcher__avatar {
        width: 2.5rem;
        height: 2.5rem;
        flex: none;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: linear-gradient(165deg, var(--brass-bright), var(--brass));
        color: var(--ink-deep);
        font-family: var(--display);
        font-weight: 700;
        font-size: 1.15rem;
        box-shadow: 0 0 0 1px rgba(246, 243, 234, 0.22),
          0 2px 8px rgba(12, 23, 41, 0.35);
      }
      .launcher__text { display: grid; gap: 0.1rem; }
      .launcher__name { font-size: 0.95rem; font-weight: 600; letter-spacing: 0.01em; }
      .launcher__sub {
        font-size: 0.72rem;
        color: var(--on-dark-muted);
      }

      /* ---- panel ---- */
      .panel {
        position: fixed;
        right: 1.5rem;
        bottom: 1.5rem;
        z-index: 50;
        width: min(24.5rem, calc(100vw - 3rem));
        height: min(33rem, calc(100vh - 3rem));
        background: var(--surface);
        border: 1px solid var(--rule-dark);
        border-radius: var(--r-lg);
        box-shadow: var(--shadow-lg);
        display: grid;
        grid-template-rows: auto 1fr auto;
        overflow: hidden;
        animation: rise 0.18s ease-out;
      }
      @keyframes rise {
        from { opacity: 0; transform: translateY(10px) scale(0.98); }
      }

      .panel__head {
        display: flex;
        align-items: center;
        gap: 0.7rem;
        padding: 0.85rem 1rem;
        background: linear-gradient(165deg, var(--ink), var(--ink-deep));
        color: var(--on-dark);
      }
      .panel__avatar {
        width: 2.2rem;
        height: 2.2rem;
        flex: none;
        display: grid;
        place-items: center;
        border-radius: 50%;
        background: linear-gradient(165deg, var(--brass-bright), var(--brass));
        color: var(--ink-deep);
        font-family: var(--display);
        font-weight: 700;
        font-size: 1.05rem;
      }
      .panel__id { flex: 1; min-width: 0; }
      .panel__title {
        margin: 0;
        font-family: var(--display);
        font-size: 1.02rem;
        font-weight: 600;
        letter-spacing: 0.01em;
      }
      .panel__sub {
        margin: 0.1rem 0 0;
        font-size: 0.73rem;
        color: var(--on-dark-muted);
      }
      .panel__close {
        font: inherit;
        font-size: 1.5rem;
        line-height: 1;
        background: none;
        border: none;
        color: var(--on-dark-muted);
        cursor: pointer;
        padding: 0 0.25rem;
        border-radius: var(--r-sm);
      }
      .panel__close:hover { color: var(--on-dark); }

      .panel__log {
        padding: 1rem;
        overflow-y: auto;
        display: grid;
        gap: 0.9rem;
        align-content: start;
        background: var(--paper);
      }
      .empty {
        margin: 0;
        color: var(--muted);
        font-size: 0.86rem;
        line-height: 1.6;
      }
      .suggestions { display: grid; gap: 0.4rem; }
      .chip {
        font: inherit;
        font-size: 0.79rem;
        border: 1px solid var(--rule-dark);
        background: var(--surface);
        color: var(--ink);
        padding: 0.45rem 0.7rem;
        border-radius: var(--r-sm);
        cursor: pointer;
        text-align: left;
        line-height: 1.4;
        transition: border-color 0.15s, background 0.15s, color 0.15s;
      }
      .chip:hover {
        border-color: var(--stamp-bright);
        background: var(--stamp-soft);
        color: var(--stamp);
      }

      .turn { display: grid; gap: 0.3rem; justify-items: start; }
      .turn--you { justify-items: end; }
      .bubble {
        font-size: 0.87rem;
        line-height: 1.6;
        white-space: pre-wrap;
        background: var(--surface);
        border: 1px solid var(--rule);
        border-radius: var(--r-md);
        border-bottom-left-radius: 3px;
        padding: 0.6rem 0.8rem;
        max-width: 92%;
        box-shadow: var(--shadow-sm);
      }
      .bubble--you {
        background: linear-gradient(165deg, var(--stamp-bright), var(--stamp));
        border-color: var(--stamp);
        color: #fff;
        border-radius: var(--r-md);
        border-bottom-right-radius: 3px;
      }
      .bubble--failed {
        background: var(--levy-soft);
        border-color: #E6B3A6;
        color: var(--levy);
      }
      .caret {
        display: inline-block;
        width: 0.4rem;
        height: 0.95em;
        background: var(--stamp);
        vertical-align: text-bottom;
        margin-left: 2px;
        animation: blink 1s steps(2) infinite;
      }
      @keyframes blink { 50% { opacity: 0; } }
      @media (prefers-reduced-motion: reduce) {
        .caret { animation: none; }
        .panel { animation: none; }
      }

      .hint { margin: 0; font-size: 0.76rem; color: var(--muted); }
      .sources { display: flex; flex-wrap: wrap; gap: 0.3rem; }
      .src {
        font-family: var(--mono);
        font-size: 0.64rem;
        border: 1px solid var(--rule-dark);
        background: var(--stamp-soft);
        color: var(--stamp);
        padding: 0.1rem 0.35rem;
        border-radius: 999px;
      }
      .src--note { color: var(--muted); border-color: var(--rule); background: var(--tint); }

      .composer {
        display: flex;
        gap: 0.4rem;
        border-top: 1px solid var(--rule);
        padding: 0.7rem;
        background: var(--surface);
      }
      .composer__input {
        flex: 1;
        font: inherit;
        font-size: 0.87rem;
        border: 1px solid var(--rule-dark);
        padding: 0.5rem 0.65rem;
        border-radius: var(--r-sm);
        min-width: 0;
        transition: border-color 0.15s, box-shadow 0.15s;
      }
      .composer__input:focus {
        outline: none;
        border-color: var(--stamp-bright);
        box-shadow: 0 0 0 3px var(--stamp-soft);
      }
      .composer__btn {
        font: inherit;
        font-size: 0.85rem;
        font-weight: 500;
        border: 1px solid var(--stamp);
        background: linear-gradient(165deg, var(--stamp-bright), var(--stamp));
        color: #fff;
        padding: 0.5rem 0.95rem;
        border-radius: var(--r-sm);
        cursor: pointer;
        transition: filter 0.15s;
      }
      .composer__btn:hover:not(:disabled) { filter: brightness(1.08); }
      .composer__btn:disabled { opacity: 0.4; cursor: not-allowed; }
      .composer__btn--stop {
        background: none;
        color: var(--levy);
        border-color: var(--levy);
      }

      @media (max-width: 520px) {
        .panel {
          right: 0;
          bottom: 0;
          width: 100vw;
          height: 80vh;
          border-radius: var(--r-lg) var(--r-lg) 0 0;
        }
        .launcher { right: 1rem; bottom: 1rem; }
        .launcher__sub { display: none; }
      }
    `,
  ],
})
export class ChatComponent {
  private readonly api = inject(ApiService);
  private readonly log = viewChild<ElementRef<HTMLDivElement>>('log');
  private readonly qinput = viewChild<ElementRef<HTMLInputElement>>('qinput');
  private controller: AbortController | null = null;

  readonly suggestions = SUGGESTIONS;
  readonly isOpen = signal(false);
  readonly turns = signal<Turn[]>([]);
  readonly draft = signal('');
  readonly streaming = signal(false);

  constructor() {
    // Opening a chat panel and leaving focus behind on the launcher means the
    // first thing a keyboard user does is hunt for the input.
    effect(() => {
      if (this.isOpen()) this.qinput()?.nativeElement.focus();
    });
  }

  async ask(question: string): Promise<void> {
    const text = question.trim();
    if (!text || this.streaming()) return;

    this.draft.set('');
    this.turns.update((t) => [
      ...t,
      { role: 'you', text },
      { role: 'assistant', text: '' },
    ]);
    this.streaming.set(true);
    this.controller = new AbortController();

    await this.api.ask(
      text,
      {
        onMeta: (meta) => this.patchLast({ meta }),
        onToken: (chunk) =>
          this.turns.update((turns) => {
            const next = [...turns];
            const last = next.at(-1)!;
            next[next.length - 1] = { ...last, text: last.text + chunk };
            return next;
          }),
        onDone: (sources) => this.patchLast({ sources }),
        onError: (message) => this.patchLast({ text: message, failed: true }),
      },
      this.controller.signal,
    );

    this.streaming.set(false);
    this.controller = null;
    this.scroll();
  }

  stop(): void {
    this.controller?.abort();
  }

  private patchLast(patch: Partial<Turn>): void {
    this.turns.update((turns) => {
      const next = [...turns];
      next[next.length - 1] = { ...next.at(-1)!, ...patch };
      return next;
    });
    this.scroll();
  }

  private scroll(): void {
    queueMicrotask(() => {
      const element = this.log()?.nativeElement;
      if (element) element.scrollTop = element.scrollHeight;
    });
  }
}
