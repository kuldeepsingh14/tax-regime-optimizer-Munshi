# Phase 6 — Deployment

Backend to Render, frontend to Vercel. Both free tiers. About 25 minutes
end to end.

---

## Before you start

Two separate Git repositories are simplest, because Render and Vercel each
want a repo root:

```
taxopt-backend/    → Render
taxopt-web/        → Vercel
```

A monorepo works too — both platforms accept a root directory setting — but
two repos removes a class of path problems on the first deploy.

Verify locally first. A deploy is a bad place to discover a broken test:

```bash
cd taxopt-backend && pip install -r requirements-dev.txt && pytest -q
cd taxopt-web && npm install && npm run build
```

---

## Part 1 — Backend on Render

### 1. Push the repo

```bash
cd taxopt-backend
git init && git add . && git commit -m "Tax regime optimizer API"
git remote add origin git@github.com:YOU/taxopt-backend.git
git push -u origin main
```

`.gitignore` already excludes `.env`. Confirm it isn't staged before you push
— a committed `.env` is the single most common way credentials leak from a
student project, and it stays in history even after you delete the file.

### 2. Create the service

Render Dashboard → **New** → **Web Service** → connect the repo.

`render.yaml` is committed, so Render reads its settings automatically. If it
doesn't pick them up, enter them by hand:

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check path | `/health` |
| Region | Singapore |
| Instance type | Free |

**One worker, deliberately.** Two would double memory on a 512 MB box for no
throughput gain on a single shared CPU. The app is stateless, so scaling is
horizontal when it matters.

### 3. Set environment variables

In **Environment**, add:

```
ALLOWED_ORIGINS = https://your-app.vercel.app
EMBEDDER        = auto
```

Optional, and the app works fully without them:

```
GROQ_API_KEY     = gsk_...     # non-standard Form 16 templates
PINECONE_API_KEY = pcsk_...    # otherwise served from memory
```

You won't know the Vercel URL yet. Put a placeholder, deploy the frontend,
then come back and correct it. Preview deployments are already covered by the
`https://.*\.vercel\.app` regex in `main.py`.

### 4. Deploy and verify

```bash
curl https://taxopt-api.onrender.com/health
# {"status":"ok"}

curl https://taxopt-api.onrender.com/api/v1/index/status
# {"embedder":"FastEmbedder","store":"InMemoryStore","chunks":11}
```

If `embedder` says `LexicalEmbedder`, the build-time model cache failed. That
is not a broken deploy — retrieval still works. See troubleshooting.

Full computation check:

```bash
curl -X POST https://taxopt-api.onrender.com/api/v1/compute \
  -H 'Content-Type: application/json' \
  -d '{"salary":{"gross_salary":"1400000"}}'
```

---

## Part 2 — Frontend on Vercel

### 1. Point it at the API

Edit `src/environments/environment.prod.ts`:

```ts
export const environment = {
  production: true,
  apiBase: 'https://taxopt-api.onrender.com',   // no trailing slash
};
```

A trailing slash produces `//api/v1/compute`, which 404s in a way that looks
like the backend is down.

### 2. Push and import

```bash
cd taxopt-web
git init && git add . && git commit -m "Tax regime optimizer UI"
git remote add origin git@github.com:YOU/taxopt-web.git
git push -u origin main
```

Vercel Dashboard → **Add New** → **Project** → import the repo.

`vercel.json` is committed and sets everything. If asked manually:

| Setting | Value |
|---|---|
| Framework preset | Other |
| Build command | `npm run build` |
| Output directory | `dist/taxopt-web/browser` |
| Install command | `npm install` |

The `browser` subdirectory matters. Angular's application builder emits
`dist/<project>/browser`, and pointing at `dist/<project>` deploys an empty
directory that returns 404 with no error in the build log.

### 3. Close the CORS loop

Copy your Vercel URL, go back to Render → Environment, set
`ALLOWED_ORIGINS` to it, and save. Render redeploys automatically.

Until you do this, every request fails in the browser with a CORS error while
`curl` works perfectly — which reliably sends people hunting in the wrong
place.

---

## Part 3 — Verify end to end

Open the Vercel URL and check:

1. The first load shows the waking-up notice, then clears.
2. Enter a gross salary → **Compare both regimes** → the ledger renders with
   struck-through rows in the new-regime column.
3. Ask "what is the 80C limit?" → tokens stream in with a section citation.
4. Ask "how much tax will I pay?" → routed to the calculator, not answered
   by the model. This is the architecture working; check it explicitly.
5. Open DevTools → Network → confirm no CORS errors.

---

## The cold start

Render's free tier sleeps after ~15 minutes idle. The next request takes
roughly 50 seconds to wake the container.

The frontend already handles this honestly: it pings `/health` on load and
says the first request may take a minute. A spinner that lies is worse than a
wait that's explained.

If you're sending the link to a recruiter, hit it yourself a minute before.
Keeping it permanently warm needs an external cron pinging `/health`, which
is against the spirit of the free tier — the honest loading state is the
better answer, and it's a better interview answer too.

---

## Memory budget

Measured, not estimated:

| Stage | Resident |
|---|---|
| Interpreter | 12 MB |
| + FastAPI, Pydantic | 48 MB |
| + LangGraph | 82 MB |
| + pdfplumber | 91 MB |
| + app and routes | 92 MB |
| + index, lexical | 143 MB |
| + index, FastEmbed | ~300 MB |

Against 512 MB, that leaves comfortable headroom.

**This is why `sentence-transformers` is not in `requirements.txt`.** It pulls
PyTorch at roughly 800 MB installed and cannot fit. FastEmbed runs the same
class of model through ONNX Runtime in about 50 MB. If an interviewer asks
what constrained the architecture, this is the answer — a real limit that
changed a real decision.

---

## Troubleshooting

**Every browser request fails, `curl` works.**
CORS. `ALLOWED_ORIGINS` on Render doesn't match your Vercel origin. Match it
exactly — scheme included, no trailing slash.

**Vercel deploys but the site is blank, no build error.**
Output directory is wrong. It must be `dist/taxopt-web/browser`.

**First request after idle takes ~90s instead of ~50s.**
The FastEmbed model isn't cached, so cold start includes a download attempt
with exponential backoff. Either fix the build-time cache or set
`EMBEDDER=lexical` — that starts in about a second.

**`index/status` reports `LexicalEmbedder` when you wanted FastEmbed.**
The build-time cache step failed. Check the Render build log for the
`TextEmbedding(...)` line. Retrieval still works; lexical is genuinely
effective on statutory text because the vocabulary is precise, and the
rewrite node compensates for conversational phrasing.

**Render build succeeds, service won't start.**
Almost always the start command. It must bind `0.0.0.0` and `$PORT`, not a
hardcoded 8000.

**Extraction always escalates to manual entry.**
No `GROQ_API_KEY`, so only regex extraction runs. Standard Form 16 templates
still work; non-standard ones need the model.

**Upload returns 413.**
Files over 10 MB are rejected in `extract_routes.py`. Raise `MAX_UPLOAD_BYTES`
if you need to, but watch memory — the file is read fully into RAM.

---

## What to say about this in an interview

The deployment constraints shaped the architecture, and that's the useful
story. The 512 MB limit ruled out PyTorch, which forced the FastEmbed
decision. The sleep behaviour made lazy index construction necessary rather
than convenient. The single shared CPU made one worker correct rather than a
compromise.

And every external dependency degrades instead of failing: no Groq key falls
back to regex extraction, no Pinecone falls back to in-memory, no FastEmbed
falls back to lexical retrieval. The app is fully functional on a bare
checkout with zero API keys — which is also why 132 tests run in under a
second with no network.
