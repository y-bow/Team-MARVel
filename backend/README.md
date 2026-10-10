# EduSaarthi AI — Backend

Student opportunity navigator for DevFest on Campus 2026.  
This directory contains the Python/Flask backend only.  
The frontend, knowledge-base JSON, and deployment config are maintained by separate teammates.

---

## Team boundaries

| Directory / file | Owner |
|---|---|
| `backend/` | Backend (this README) |
| `requirements.txt` | Backend |
| `.env.example` | Backend |
| `data/schemes.json` | Knowledge-base teammate |
| `frontend/` | Frontend teammate |
| Deployment config | DevOps/deployment teammate |

> ⚠️ **Assumption flags** — see [§ Assumptions for teammates](#assumptions-for-teammates) if the knowledge-base schema or API contract differs from what is described here.

---

## Architecture overview

```
POST /api/chat
      │
      ▼
  app.py  ──  request validation  ──►  400 on bad input
      │
      ▼
  agent.py  ──  OpenRouterProvider  ──►  OpenAI-compatible API  ──►  OpenRouter
      │              │
      │        function-calling loop
      │              │
      ▼              ▼
  tools.py  ◄──  tool_registry  ──►  repository.py  ──►  data/schemes.json
```

**Modules**

| Module | Responsibility |
|---|---|
| `config.py` | Load all env vars; fail fast with ConfigurationError if OPENROUTER_API_KEY is missing |
| `schemas.py` | `SchemeRecord` dataclass + `scheme_from_dict` factory |
| `repository.py` | `BaseRepository` interface + `JSONRepository` implementation |
| `tools.py` | 5 tool functions (search, eligibility, requirements, deadline, action plan) |
| `agent.py` | `OpenRouterProvider`, `AgentLoop`, tool registry, conversation state |
| `app.py` | Flask app factory, `/health`, `/api/chat` |

---

## Quick start (Linux / macOS)

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd Team-MARVel
git checkout backend
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Windows note:** `gunicorn` is not available on Windows. Use `flask run` or `python backend/app.py` for local development.

### 4. Set environment variables

```bash
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY to your real key and OPENROUTER_MODEL.
```

The server **refuses to start** if `OPENROUTER_API_KEY` is missing, so this step is required.

### 5. Run Flask locally (development)

```bash
python backend/app.py
# or
flask --app backend.app:create_app run --port 5000
```

The server starts on `http://localhost:5000`.

---

## Running tests

```bash
# Offline tests — no API key required, no paid calls
pytest

# Or with more output
pytest -v

# Integration tests (requires a real OPENROUTER_API_KEY and uses paid quota)
OPENROUTER_API_KEY=your_key pytest tests/test_integration.py -v
```

Tests use synthetic JSON data and mocked LLM responses. They run fully offline.

---

## Running in production (Gunicorn)

```bash
# The platform provides $PORT; bind to 0.0.0.0 so the reverse proxy can reach it.
gunicorn "backend.app:create_app()" \
  --bind 0.0.0.0:$PORT \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

- `--workers 2` — suitable for a single-instance hackathon deployment.
- Conversation history is in-process memory; it resets on restart or when workers recycle.
  For multi-worker or persistent sessions, replace `_CONVERSATIONS` in `agent.py` with
  a Redis-backed store.

---

## API contract

### `GET /health`

```
200 OK
{
  "status": "ok",
  "version": "1.0.0",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "data_loaded": true,
  "scheme_count": 42
}
```

### `POST /api/chat`

**Request:**
```json
{
  "message": "string (required, 1–4000 chars)",
  "conversation_id": "string | null"
}
```

**Success (200):**
```json
{
  "conversation_id": "uuid-string",
  "status": "completed",
  "answer": "...",
  "sources": [
    {"id": "scheme-id", "title": "Scheme Name", "url": "https://..."}
  ],
  "events": [
    {"tool": "search_schemes", "status": "completed", "summary": "Found 3 scheme(s)"}
  ],
  "action_plan": [
    {"title": "...", "action_type": "apply", "completed": false, "requires_user_verification": true}
  ],
  "matches": [
    {"id": "scheme-id", "title": "Scheme Name", "summary": "...", "url": "https://..."}
  ],
  "eligibility": {
    "met": ["education_level (required: One of: ['10th', 'UG'])", "..."],
    "missing": ["percentage (required: >= 55%)", "..."],
    "unknown": ["annual_family_income (required: <= ₹250,000)"]
  },
  "documents": ["Aadhaar card", "..."],
  "steps": ["Step 1: Register", "..."],
  "clarification": {"question": "Which state do you live in?", "options": []}
}
```

`events[].status` is normalised at the API boundary and is always one of
`queued`, `running`, `completed`, `failed`. Internal tool statuses `ok`/`error`
are never exposed to the client.

Optional fields are included only when the supporting tools ran and returned
data (they are never fabricated):

- `matches[]` — from `search_schemes`
- `eligibility{met,missing,unknown}` — from `check_eligibility`
  (`satisfied_criteria` → `met`, `unsatisfied_criteria` → `missing`,
  `unknown_criteria` → `unknown`)
- `documents[]`, `steps[]` — from `get_requirements`
- `clarification{question,options[]}` — present when `status` is
  `needs_clarification`

**Status values:**

| Value | Meaning |
|---|---|
| `completed` | Agent produced a final answer |
| `needs_clarification` | Agent is asking the student a follow-up question (also includes `clarification` object for frontend normalisation) |

**Error responses:**

| HTTP | `code` field | Cause |
|---|---|---|
| 400 | `MISSING_FIELD` | `message` absent |
| 400 | `INVALID_FIELD` | `message` wrong type, empty, or invalid `conversation_id` |
| 400 | `MESSAGE_TOO_LONG` | `message` exceeds 4000 chars |
| 400 | `INVALID_CONTENT_TYPE` | Not `application/json` |
| 400 | `INVALID_JSON` | Malformed JSON body |
| 429 | `PROVIDER_ERROR` | LLM API quota exceeded |
| 503 | `PROVIDER_ERROR` | LLM API unavailable |
| 500 | `AGENT_ERROR` | Unexpected internal error |
| 500 | `INTERNAL_ERROR` | Unhandled Flask exception |

All errors: `{"error": "human-readable message", "code": "ERROR_CODE"}`

---

## Assumptions for teammates

> These assumptions are made because no API contract or schema file existed when the backend was first created. Teammates should review and flag discrepancies.

### Knowledge-base JSON (`data/schemes.json`)

Expected top-level format: **JSON array of scheme objects**.  
Override the path with the `DATA_PATH` env var if the file lives elsewhere.

Minimum required fields per record:

```jsonc
{
  "id": "unique-slug",          // Required
  "name": "Scheme Name",        // Required
  "description": "...",         // Required
  "criteria": {
    "education_levels": [...],  // e.g. ["10th", "UG"] or null
    "state": "Maharashtra",     // null = all-India
    "caste_categories": [...],  // e.g. ["SC", "ST"] or ["any"]
    "min_percentage": 55.0,     // null = no restriction
    "annual_family_income_max": 250000, // null = no restriction
    "gender": "Female",         // "any" or null = no restriction
    "disability_required": null
  },
  "documents": [...],           // list of strings; [] is valid
  "application_steps": [...],   // list of strings; [] is valid
  "deadline": "2024-10-31",     // ISO date string or null
  "source_url": "https://...",  // null = not available
  "verified": true,             // boolean
  "last_checked": "2024-09-15", // ISO date string or null
  "tags": [...]                 // list of strings; [] is valid
}
```

See `backend/schemas.py` for the full `SchemeRecord` definition.

### Conversation state

Conversation history is stored **in-process** (Python dict in `agent.py`).  
It resets when the server restarts. Suitable for the hackathon; note this if deploying with multiple workers.

---

## Tool descriptions

| Tool | Description |
|---|---|
| `search_schemes(query, education_level?, state?)` | Keyword search + structured filters |
| `check_eligibility(scheme_id, student_info)` | Deterministic eligibility against scheme criteria |
| `get_requirements(scheme_id)` | Documents, steps, official URLs, verification metadata |
| `verify_deadline(scheme_id)` | Deadline status (current/past/stale/unverified/unknown) |
| `create_action_plan(goal, scheme_ids, eligibility_results, missing_info)` | Structured next steps |

---

## Safety rules (enforced in code)

- Missing `OPENROUTER_API_KEY` → `ConfigurationError` at startup, server does not start.
- Max iterations: 8 (configurable via `MAX_ITERATIONS`). Prevents infinite loops.
- Max search results: 10 (configurable via `MAX_SEARCH_RESULTS`).
- Message length capped at 4000 chars; answer capped at 8000 chars.
- Unregistered tool names → structured error returned to model, loop continues.
- Stack traces, API keys, and internal paths are **never** exposed to clients.
- Deadlines are never called "current" unless `verified=true` and `last_checked` is within `DEADLINE_STALE_DAYS`.
- Eligibility gaps are always reported honestly; missing info is never treated as proof of eligibility.
