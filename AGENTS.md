# EduSaarthi AI - Project Instructions

## Project Overview
EduSaarthi AI is an AI-powered student opportunity navigator for scholarships and student services. It uses an LLM agent, backend tools, and verified data sources to help students understand their options and next steps.

## Project Structure
- `frontend/`: User interface and client-side code.
- `backend/`: Flask API, AI agent, tools, and data access.
- `data/`: Scheme records and supporting datasets.
- `tests/`: Automated tests and test fixtures.
- `README.md`: Setup instructions and project documentation.

Check the actual repository structure before assuming a file exists.

## Architecture
- Frontend communicates with the backend through HTTP APIs.
- `POST /api/chat`: Main chat endpoint.
- `GET /health`: Health check.
- The backend owns LLM calls, tool execution, eligibility logic, and source validation.
- Keep data access behind the repository abstraction.
- Keep API keys and secrets on the server. Never expose them in frontend code.

## Team Collaboration
- Work only on your assigned files unless the team agrees otherwise.
- Do not overwrite another teammate's changes.
- Do not change the agreed API contract without informing the team.
- Inspect `git status` and existing changes before editing.
- Use separate branches and commit focused changes.
- Do not commit `.env` files, credentials, or generated secrets.

## AI Agent Rules
- Use registered, explicitly defined tools only.
- Use deterministic code for objective eligibility checks.
- Never invent eligibility criteria, deadlines, requirements, or source URLs.
- Distinguish verified facts from unknown or unverified information.
- Use synthetic data for personal student examples.
- Recommend actions and draft guidance. Do not impersonate universities or government authorities.

## Development Rules
- Inspect existing files before creating replacements.
- Preserve the project's existing framework and dependencies.
- Avoid unnecessary dependencies and unrelated refactoring.
- Handle API errors, empty results, and loading states.
- Add or update tests for changed functionality.
- Run relevant tests before declaring work complete.
- Update the README when setup or commands change.

## Completion Report
When finishing a task, report:
1. Files created or modified.
2. Features implemented.
3. Tests and commands run, including failures.
4. Remaining issues or assumptions.