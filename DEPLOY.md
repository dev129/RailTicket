# Deploying railengine

The service is a single ASGI app: `railengine.api:app` (FastAPI), serving a
JSON API + a static UI at `/`.

## Deploy on Render (recommended — dashboard only, no CLI)

The repo has a `render.yaml` blueprint, so this is almost entirely clicks.

1. Go to **render.com** → sign up (use **Sign in with GitHub**).
2. **New +** → **Blueprint** → connect this repo (`dev129/RailTicket`).
   Render reads `render.yaml` and creates the `railengine` web service.
3. When prompted for the **`IRCTC_DEV_KEY`** environment variable, paste your
   irctc.dev API key → **Apply**.
4. Render builds the Docker image and gives a public HTTPS URL
   (`https://railengine-xxxx.onrender.com`). That's the live site.

Every push to the branch auto-redeploys. Free plan sleeps after inactivity
(first hit after idle takes ~30s to wake) — fine for a demo.

## Run locally

```bash
pip install -r requirements.txt
uvicorn railengine.api:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

## Run with Docker (portable artifact)

```bash
docker build -t railengine .
docker run -p 8000:8000 railengine
# live mode:
docker run -p 8000:8000 \
  -e RAIL_API_BASE="https://<irctc-style-host>" \
  -e RAIL_API_KEY="<key>" \
  -e RAIL_API_HOST="<rapidapi-host>" \
  railengine
```

The provider auto-selects: **live** when `RAIL_API_BASE` + `RAIL_API_KEY`
are present, otherwise the offline **mock** corridor.

## Option A — Google Cloud Run (recommended)

Runs the Dockerfile unchanged; exact parity with local. Builds from source via
Cloud Build, so you don't need Docker locally.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

gcloud run deploy railengine \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8000
```

The command prints the public HTTPS URL. For **live availability** (keep the
key out of the repo):

```bash
echo -n "YOUR_KEY" | gcloud secrets create rail-api-key --data-file=-
gcloud run services update railengine --region asia-south1 \
  --set-env-vars RAIL_API_BASE=https://HOST,RAIL_API_HOST=RAPIDAPI_HOST \
  --set-secrets RAIL_API_KEY=rail-api-key:latest
```

**Auto-deploy on push:** `.github/workflows/deploy-cloudrun.yml` is included —
add `GCP_SA_KEY` (secret) + `GCP_PROJECT_ID`, `GCP_REGION` (variables).

## Option B — Vercel

Serves the same FastAPI app as a Python serverless function via
`api/index.py` + `vercel.json`. Good if you also want the UI on Vercel's CDN.
Note: serverless = cold starts and per-request statelessness (fine here; the
provider cache just warms per instance).

```bash
npm i -g vercel
vercel          # first run links/creates the project
vercel --prod   # production deploy -> public URL
```

Set `RAIL_API_BASE` / `RAIL_API_KEY` / `RAIL_API_HOST` in
**Vercel → Project → Settings → Environment Variables** for live mode.

**Auto-deploy on push:** `.github/workflows/deploy-vercel.yml` is included —
add `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` secrets (the latter
two come from `.vercel/project.json` after `vercel link`).

## Other container hosts

The image listens on `$PORT`, so it also drops onto Fly (`fly launch`),
Render (Docker web service), Railway (`railway up`), or any VM
(`docker run -p 80:8000 railengine`). Set `RAIL_API_*` in the platform's
secret store — never commit keys.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness + active provider |
| GET | `/api/next-seat?train=&date=&from=&to=&classes=&full=` | Feature 2 |
| GET | `/api/break-journey?date=&from=&to=&classes=&min_connection_min=` | Feature 1 |
| GET | `/` | web UI |

`date` = `YYYY-MM-DD`; `classes` = comma list (`SL,3E,3A,2A,1A`); station codes
are IR codes (`JP`, `AII`, `UDZ`, `HMT`, `ASV` in the demo corridor).

## Production checklist (before a real launch)

- [ ] Real schedule source (the mock bundles only the demo corridor).
- [ ] Response cache + rate-limit/backoff in `LiveApiProvider`.
- [ ] CORS policy if the UI is served from a different origin.
- [ ] Pin dependency versions / add a lockfile.
