# EduSaarthi AI — Frontend

Frontend for **EduSaarthi AI**, an AI-powered Student Opportunity Navigator
(scholarships and education services). Built for the DevFest on Campus 2026
hackathon with plain HTML, CSS and JavaScript — no frameworks, no build step.

## Run it locally

The frontend is fully static. Serve the `frontend/` directory with any static
server, for example:

```bash
python3 -m http.server 8000      # from inside frontend/
```

Then open http://localhost:8000

You can also open `frontend/index.html` directly, but a server is recommended
(and required to call the same-origin backend).

## Backend integration

The frontend calls a single endpoint, which the backend teammate implements at:

```
POST /api/chat
```

Request body:

```json
{
  "message": "Find scholarships for my course",
  "conversation_id": null
}
```

Response body (the fields the frontend consumes):

```json
{
  "conversation_id": "demo-conversation",
  "status": "completed",
  "answer": "A concise response grounded in retrieved records.",
  "sources": [
    { "id": "SCHEME-001", "title": "Illustrative scheme", "url": "https://example.org" }
  ],
  "events": [
    { "tool": "search_schemes", "status": "completed", "summary": "Retrieved relevant records.", "detail": "optional expandable result detail" }
  ],
  "action_plan": [
    { "title": "Review the eligibility criteria", "completed": false }
  ]
}
```

Optional forward-compatible fields are rendered only when the backend provides
them (never fabricated): `matches[]`, `eligibility{met,missing,unknown}`,
`documents[]`, `steps[]`, `clarification{question,options[]}`. See
`js/api.js` for the full normalisation rules.

Notes for the backend:

- `status` is one of `completed`, `clarification`, `no_results`, `failed`.
- `events[].status` is one of `queued`, `running`, `completed`, `failed`.
- Deploying frontend and backend separately? The frontend uses a relative
  base URL by default. Set `window.EDUSAARTHI_API_BASE` (before `app.js`
  loads) or `localStorage`/build config as needed to point at the backend.
- External source URLs must be absolute `http`/`https` links; anything else is
  dropped before rendering.

## Demo mode

When the backend is unavailable, toggle **Demo mode** in the sidebar. All demo
responses come from `js/demo-data.js`, are deterministic and are labelled
"illustrative" throughout the UI. Demo is never silently substituted for real
results: switching is explicit, and the interface shows an amber banner.

## Configuration & persistence

- Investigation history and saved plans persist in `localStorage`
  (`edusaarthi.v1`) in the user's own browser. Only what the user typed is
  stored; no credentials are kept.
- `js/api.js` validates every response field and rejects invalid external links
  before they become clickable.

## Files

```
index.html        Structure, semantic shell, inline SVG icon sprite
css/styles.css    Design tokens, layout, base typography
css/components.css Buttons, messages, activities, result components
css/responsive.css Tablet/mobile behaviour
js/app.js         Bootstrap, event handling, orchestration
js/api.js         HTTP client + response/URL validation
js/state.js       Client state + localStorage persistence
js/render.js      Safe DOM rendering (textContent, no innerHTML)
js/demo-data.js   Clearly labelled illustrative fixtures
assets/           Reserved for static assets
```