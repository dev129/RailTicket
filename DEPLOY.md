# Deploying railengine

The service is a single ASGI app: `railengine.api:app` (FastAPI), serving a
JSON API + a static UI at `/`.

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

## Hosting targets

The container listens on `$PORT` (default 8000), so it drops onto any
container host unchanged:

| Target | Command |
|---|---|
| **Fly.io** | `fly launch` (detects Dockerfile) → `fly deploy` |
| **Render** | New Web Service → Docker → repo; set env vars in dashboard |
| **Railway** | `railway up` (Dockerfile auto-detected) |
| **Google Cloud Run** | `gcloud run deploy railengine --source .` |
| **Any VM** | `docker run -p 80:8000 railengine` behind a reverse proxy |

Set `RAIL_API_*` as secrets in the platform's env/secret store — never commit
keys.

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
