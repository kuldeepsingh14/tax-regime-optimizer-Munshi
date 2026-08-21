# Hosting: Vercel + Render, free tier

This repo is a **monorepo**. Both platforms deploy from it using a root-directory
setting, so you push once and both halves redeploy:

```
frontend/   → Vercel   (Angular static site)
backend/    → Render   (FastAPI service)
render.yaml → read by Render from the repo root
```

> Supersedes `docs/02-deployment.md`, which describes an older two-repo layout.

---

## Step 1 — Push to GitHub

The repo is already committed locally on branch `main`. Create an **empty**
repo at <https://github.com/new> (no README, no .gitignore), then:

```bash
cd "tax-regime-optimizer/tax-regime-optimizer"
git remote add origin https://github.com/<YOU>/tax-regime-optimizer.git
git push -u origin main
```

`.env` is gitignored and was verified absent from the commit. Keep it that way —
a committed key stays in history even after you delete the file.

---

## Step 2 — Backend on Render

1. <https://dashboard.render.com> → **New** → **Blueprint** → connect the repo.
   Render reads `render.yaml` and fills in build command, start command, health
   check, and region automatically.
2. It will prompt for the env vars marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `ALLOWED_ORIGINS` | Leave blank for now — you fill it in at Step 4 |
   | `GROQ_API_KEY` | Your Groq key, or blank (extraction falls back to regex-only) |
   | `PINECONE_API_KEY` | Blank is fine — the in-memory store handles this corpus size |

3. Deploy. First build takes ~5 minutes (it caches the ONNX embedding model).
4. Copy the service URL, e.g. `https://taxopt-api.onrender.com`, and confirm:

   ```bash
   curl https://taxopt-api.onrender.com/health     # -> {"status":"ok"}
   ```

**If the build fails on the FastEmbed step**, set `EMBEDDER=lexical` in the
Render dashboard and redeploy. The app works fine on lexical retrieval and
starts in about a second.

---

## Step 3 — Frontend on Vercel

1. <https://vercel.com/new> → import the same repo.
2. Set these — the root directory is the part people miss:

   | Setting | Value |
   |---|---|
   | **Root Directory** | `frontend` |
   | Framework Preset | Other |
   | Build / Output | leave blank — `frontend/vercel.json` sets them |

3. **Environment Variables** → add:

   | Name | Value |
   |---|---|
   | `API_BASE` | `https://taxopt-api.onrender.com` (your Render URL, no trailing slash) |

   `frontend/scripts/set-env.js` reads this at build time and writes
   `environment.prod.ts`, so the API URL never lives in source. To point the app
   at a different API later, change this variable and redeploy — no code change.

4. Deploy. Copy your Vercel URL, e.g. `https://tax-regime-optimizer.vercel.app`.

---

## Step 4 — Close the CORS loop

The browser blocks every API call until Render knows the frontend's origin, and
the failure looks exactly like the API being down.

Render dashboard → your service → **Environment** → set:

```
ALLOWED_ORIGINS = https://tax-regime-optimizer.vercel.app
```

Save; Render restarts automatically. Preview deployments are already covered by
the `https://.*\.vercel\.app` regex in `app/main.py`.

---

## Step 5 — Keep it always on

Render's free tier suspends a web service after ~15 minutes of no traffic, and
the next visitor waits ~50 seconds for the cold start. `.github/workflows/keep-alive.yml`
pings `/health` every 10 minutes to prevent that.

Turn it on: repo → **Settings** → **Secrets and variables** → **Actions** →
**Variables** tab → **New repository variable**

```
Name:  API_URL
Value: https://taxopt-api.onrender.com
```

Then **Actions** tab → **keep-alive** → **Run workflow** to verify it goes green
once before trusting the schedule.

### What "always on" actually costs you

- **Render gives 750 instance-hours/month, free.** A month is ~730 hours, so
  one always-awake service fits. **Do not keep a second free service awake** —
  you would exceed the budget and Render suspends everything until the month
  rolls over.
- **GitHub cron is best-effort.** Scheduled runs queue on shared runners and can
  drift to 15-20 minutes under load. Occasionally a visitor still hits a cold
  start. That is the honest trade at zero cost.
- **GitHub disables scheduled workflows after 60 days with no repo commits.**
  Push anything, or hit **Run workflow** manually, to reset the clock.
- Vercel static hosting never sleeps — the frontend is always instant regardless.

If you later want a genuinely uninterrupted API with no caveats, Render's
Starter plan (~$7/month) removes the sleep entirely and you can delete the
workflow. Nothing else about the setup changes.

---

## Redeploying

Both platforms watch `main`:

```bash
git push          # Vercel rebuilds frontend/, Render rebuilds backend/
```

Render only rebuilds when files under `backend/` change, and Vercel only when
`frontend/` changes, so a docs-only commit is cheap.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Frontend loads, every API call fails | `ALLOWED_ORIGINS` missing your Vercel URL | Step 4 |
| Calls go to `localhost:8000` | `API_BASE` unset on Vercel at build time | Add it, then **redeploy** — it is read at build, not runtime |
| First request takes ~50s | Service was asleep | Step 5 |
| Render build OOMs | Something pulled in PyTorch | Keep `fastembed`; never add `sentence-transformers` (512 MB cap) |
| 404 on refresh of a deep link | SPA rewrite missing | `frontend/vercel.json` handles it — confirm Root Directory is `frontend` |
