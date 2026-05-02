# magicpin AI Challenge Bot

This workspace now contains a first-pass FastAPI bot for the Vera challenge.

## What is implemented

- `GET /v1/healthz`
- `GET /v1/metadata`
- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`
- In-memory context storage with version checks
- Deterministic rule-based composer for merchant-facing and customer-facing messages
- Basic auto-reply detection, opt-out handling, and intent-handoff routing

## Run locally

```bash
uvicorn bot:app --host 0.0.0.0 --port 8080
```

Then point the judge simulator at the local server:

```bash
python judge_simulator.py
```

## Deploy (Public URL)

This repo is now deployment-ready with:

- `Dockerfile`
- `.dockerignore`
- `Procfile`

### Option 1: Render (Fastest)

1. Push this folder to a GitHub repo.
2. In Render, create a new **Web Service** from the repo.
3. Use:
	- Runtime: `Docker`
	- Health check path: `/v1/healthz`
4. Deploy and copy the public URL.

### Option 2: Railway

1. Push this folder to a GitHub repo.
2. Create a new Railway project from the repo.
3. Railway will detect the `Dockerfile` and deploy automatically.
4. Copy the public URL from the Railway dashboard.

## Post-Deploy Smoke Test

Replace `<PUBLIC_URL>` and run:

```bash
curl <PUBLIC_URL>/v1/healthz
curl <PUBLIC_URL>/v1/metadata
```

Expected: both return HTTP 200 with JSON payloads.

## Notes

- The first implementation is intentionally deterministic and conservative.
- It uses only context already provided by the judge and avoids fabricated claims.
- The next step is to run the simulator, inspect failures, and tighten the trigger-specific messages.
- For local judge runs on Windows, prefer `127.0.0.1` over `localhost` for lower connection overhead.