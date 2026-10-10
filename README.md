# EduSaarthi AI

An AI-powered Student Opportunity Navigator for scholarships and education
services, built for the DevFest on Campus 2026 hackathon.

The backend (Flask + OpenRouter + tool-based agent) also serves the static
frontend, so a single command runs the whole app.

## Quick start (single-command run)

**Local demo URL: http://localhost:5000**

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Configure the OpenRouter API key (the server fails fast if it is missing)
cp .env.example .env
# then edit .env and set OPENROUTER_API_KEY=<your key> and OPENROUTER_MODEL=<model id>

# 3. Run the app — backend and frontend together
python -m backend.app
```

This serves everything on one origin:

| URL | Description |
|---|---|
| `http://localhost:5000/` | Frontend UI (`frontend/index.html`) |
| `GET /health` | Health check (status, model, scheme count) |
| `POST /api/chat` | Chat / investigation endpoint |

`python backend/app.py` works too. For production, use Gunicorn:

```bash
gunicorn "backend.app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

## Demo mode

If the backend (or its LLM API) is unavailable, toggle **Demo mode** in the
sidebar. Demo responses come from `frontend/js/demo-data.js`, are deterministic,
and are labelled "illustrative" throughout the UI.

## Running tests

Offline tests use mocked LLM responses — no API key or paid calls:

```bash
pytest
```

Integration tests against the live API are skipped unless `EDUSAARTHI_LIVE_TESTS=1`
is set:

```bash
EDUSAARTHI_LIVE_TESTS=1 OPENROUTER_API_KEY=your_key pytest tests/test_integration.py -v
```

## Project structure

```
frontend/          Static UI (HTML/CSS/JS, no build step) — see frontend/README.md
backend/           Flask API, LLM agent, tools — see backend/README.md
data/schemes.json  Verified scheme knowledge base
tests/             Pytest suite and fixtures (offline by default)
```

## Configuration

Environment variables (see `.env.example`):

- `OPENROUTER_API_KEY` — required. OpenRouter API key from
  https://openrouter.ai/keys
- `OPENROUTER_MODEL` — required. OpenRouter model id, must support tool
  calling (e.g. `nvidia/nemotron-3-ultra-550b-a55b:free`)
- `OPENROUTER_BASE_URL` — default `https://openrouter.ai/api/v1`
- `DATA_PATH` — default `data/schemes.json`
- `HOST` / `PORT` — default `0.0.0.0:5000`
- `MAX_ITERATIONS`, `MAX_SEARCH_RESULTS`, `MAX_MESSAGE_LENGTH`,
  `MAX_ANSWER_LENGTH`, `DEADLINE_STALE_DAYS`, `APP_VERSION` — optional knobs

## Frontend-only development

To iterate on the UI without the backend, serve `frontend/` with any static
server and use Demo mode:

```bash
python3 -m http.server 8000     # from inside frontend/
```

Then open http://localhost:8000. The frontend calls a relative `/api/chat` by
default; set `window.EDUSAARTHI_API_BASE` to the backend URL when hosting the
two separately.

## Safety and honesty rules

- Answers are grounded in tool results; criteria, deadlines and documents are
  never invented.
- Eligibility is deterministic, and gaps or missing information are reported
  honestly.
- API keys and secrets stay on the server and are never exposed to the client.
- Source URLs must be absolute `http(s)` links; unverified or unchecked
  deadlines are always flagged.
