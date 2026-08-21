# Tax Regime Optimizer — Frontend (Phase 5)

Angular 18, standalone components, signals. No NgModules, no RxJS in app code.

## Run

```bash
npm install
npm start                 # http://localhost:4200, expects API on :8000
npm run build             # production bundle -> dist/taxopt-web/browser
```

Point `src/environments/environment.prod.ts` at your Render URL before
deploying.

## Design direction

**The ledger.** Tax computation is a two-column ledger, so the page is one.
Stamp-ink navy on cool paper; brass used once, on the recommended verdict.
IBM Plex Serif for display, Plex Sans for body, Plex Mono for every figure —
with tabular numerals, because money columns that don't align are money
columns people don't trust. Indian digit grouping throughout (14,00,000).

**The signature element** is the strike-through. A deduction the old regime
grants and the new regime refuses still gets a row in the new column, struck
through. Other calculators show you what you save; this shows what you give
up. The absence is the information.

## Structure

```
core/models.ts          contracts mirroring the FastAPI schemas
core/api.service.ts     fetch + SSE reader, cold-start warm-up
components/uploader     Form 16 drop zone, extraction feedback, conflicts
components/tax-form     inputs, prefilled from extraction
components/ledger       THE SIGNATURE — aligned two-column trail
components/chat         SSE token stream with citations
```

## Notes on decisions

**Money is a string end to end.** The backend serialises Decimal to string so
JavaScript's float never touches a rupee figure. Parsed for display only.

**SSE over `fetch`, not `EventSource`.** EventSource can't POST. Frames split
across chunks, so the reader buffers and parses only complete frames.

**Cold start is surfaced, not hidden.** Render's free tier sleeps; the app
pings `/health` on load and says plainly that the first request takes up to a
minute. A spinner that lies is worse than a wait that's explained.

**Prefill never overwrites.** Extracted values fill only empty fields, so
anything typed by hand wins.

**Fonts load from `index.html`, not `@import`.** Angular's production build
inlines `@import`ed fonts at build time, which makes the build depend on
reaching a third-party CDN. Disabled via `optimization.fonts.inline`.

## Build output

67 kB transfer, strict templates on.
