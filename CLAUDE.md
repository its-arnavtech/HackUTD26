# SentinelAI: instructions for Claude Code

SentinelAI is a scam protection agent built at HackUTD 2026 by Arnav (`its-arnavtech`) and Lavanya. It is entered in the T-Mobile, NVIDIA (Nemotron) and Capital One (Nessie) tracks.

## Read first

1. `docs/POC_MVP.md`: scope, architecture, API, screens, issue breakdown. It is the source of truth.
2. `docs/DATA_SPEC.md`: every data contract. `backend/app/contracts.py` and `frontend/src/types.ts` must match it.

## Who owns what

- Lavanya: dataset and baseline, classifier, Nemotron agent loop, Gemini tool, recovery re-plan, API and pipeline, accuracy page (issues `L1` to `L11`, label `owner:lavanya`).
- Arnav: Nessie client and seed, redaction, replay cache, link, sender, campaign and Nessie tools, all phone UI screens (issues `A1` to `A11`, label `owner:arnav`).
- Shared gates `G1` to `G3` (label `owner:both`).

Work only on issues owned by the person you are helping, unless they say otherwise.

## Workflow

- One branch per issue, named `<id>-<short-name>`, for example `a2-redaction` or `l6-agent-loop`.
- Small commits. Run `pytest` (and `npm run build` for frontend work), tick the issue's checkboxes, then open a PR that says `Closes #<issue number>`, with a short summary and how you tested it.
- Before starting, pull `main`. Before opening a PR, merge or rebase `main` again.
- `backend/app/contracts.py` and `frontend/src/types.ts` are shared. Change them only in a PR whose title starts with `[contracts]`, and tell the user so the other person can review it.
- Don't push code directly to `main` after the scaffold commit. Changes that only touch `docs/` or `prompts/` may go straight to `main`.

## Conventions

- Both people develop on Windows. Give commands that work in PowerShell. Use `python -m ...` for scripts.
- Backend: Python 3.11+, FastAPI, Pydantic v2, pytest. Frontend: Vite, React, TypeScript, Tailwind.
- Every external call (Nemotron, Gemini, Nessie, RDAP) goes through `backend/app/integrations/cache.py`, which respects `DEMO_MODE` (`live`, `record`, `replay`).
- Secrets live in `.env` (never committed). Add new variables to `.env.example`.
- No new infrastructure: no Docker, Postgres, vector databases, graph databases or WebSockets. SQLite and polling only.
- Synthetic data only. Never put a real person's data in fixtures or tests.

## Rules that must never break

- Redaction runs before the classifier, Nemotron, or any outside service sees a message.
- Nemotron receives only the payloads in `DATA_SPEC.md` section 3. Gemini receives only section 4.1.
- The test split is never used for training, tuning, blocklists, campaign seeds or prompts.
- Every protective action waits for a customer tap. The agent never acts on money.
- The UI never shows a phone number or link that came from search results or model output.
- UI wording follows `POC_MVP.md` section 4.4: say what was checked, never "your account is fine".
