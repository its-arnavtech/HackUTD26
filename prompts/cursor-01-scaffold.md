# Cursor 01: Scaffold the repo and set up the agent folders

**Tool:** Cursor (Agent mode) · **Folder:** `C:\HackUTD26` · **Run:** first, before anything else

Paste everything below the line.

---

You are setting up the SentinelAI repo for a 24-hour hackathon build. Read `AGENTS.md`, `CHANGELOG.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md` completely before doing anything. They are the source of truth.

Your job is the **scaffold only**: structure, shared contracts, mocks, stubs, setup, and one folder per agent. Do **not** implement features; those belong to the GitHub issues (section 13 of `POC_MVP.md`). Each stub should name the issue that fills it in.

## 1. Backend (`backend/`)

1. Create the layout from `POC_MVP.md` section 6, with `__init__.py` files so `python -m` works from `backend/`.
2. `requirements.txt` with pinned versions: fastapi, uvicorn[standard], pydantic (v2), pydantic-settings, httpx, openai (for NVIDIA's OpenAI-compatible API), google-genai, huggingface_hub, scikit-learn, pandas, numpy, tldextract, rapidfuzz, python-dotenv, pytest. Don't add spaCy, torch or transformers; the README notes they're optional (issues A3, A5 and L7 decide).
3. `app/config.py`: settings from env: `NVIDIA_API_KEY`, `NEMOTRON_BASE_URL` (default `https://integrate.api.nvidia.com/v1`), `NEMOTRON_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `NESSIE_API_KEY`, `NESSIE_BASE_URL` (default `http://api.nessieisreal.com`), `HF_TOKEN`, `DEMO_MODE` (`live`, `record` or `replay`; default `live`), `USE_MOCKS` (default `true`), `PHONE_HASH_SALT`, `API_PORT` (default 8000), `WEB_PORT` (default 5173).
4. `app/contracts.py`: Pydantic v2 models and enums for **every** JSON object in `DATA_SPEC.md`: message, redaction report, URL info, features, classifier output, agent input (3.1), each tool's args and result (3.2), Gemini input and output (4.1, 4.3), agent result (3.3), trail entry (3.4), campaign, metrics, privacy view, inbox item, result-poll response. Enums for verdict, confidence words, actions, sender type, trail kind, source type, demo mode.
5. `app/mocks/`: JSON mocks for every API route, valid against the contracts, based on the three scenarios in `POC_MVP.md` section 4.3.
6. `app/main.py`: every route in section 7.1. While `USE_MOCKS=true`, routes return mocks. `GET /api/messages/{id}/result` simulates progress: `queued`, then `running` with the trail growing by one entry per poll, then `done`. Mark mock code `# MOCK: replaced by L9`.
7. Stub modules for every file in section 6: typed signatures using the contracts, a docstring naming the issue ID, and `raise NotImplementedError`.
8. `backend/scripts/`: stubs for `seed_nessie.py`, `run_baseline.py`, `train_classifier.py`, `evaluate.py`, `run_scenario.py`.
9. `tests/test_contracts.py` (every mock validates against its model) and `tests/test_api_mocks.py` (every route returns 200 with mocks on).

## 2. Frontend (`frontend/`)

1. Vite + React + TypeScript + Tailwind. The dev server uses `WEB_PORT` and proxies `/api` to `http://localhost:${API_PORT}`, both read from the repo-root `.env`.
2. `src/types.ts` mirroring `contracts.py` exactly.
3. `src/api.ts`: one typed function per route plus `pollResult(id, onUpdate)`, which polls every second until `done`.
4. A `PhoneFrame` component (about 390x844, centered) and placeholder screens from section 8: Consent, Inbox, ResultCard, HowWeChecked, PrivacyPanel, Recovery, CampaignView, plus AccuracyPage outside the frame. Each placeholder shows its name and issue ID.
5. Tailwind tokens from section 8: 18px base text, 44px minimum tap targets, amber for likely scam, gray for not sure, green for likely safe.

## 3. Data, config, root files

1. `data/brands.json`: Capital One (`capitalone.com`) and T-Mobile (`t-mobile.com`) with `official_domains`, and empty `official_short_codes` and `official_sender_ids` arrays marked TODO. Don't invent short codes.
2. `data/scenarios/scenario_1.json`, `scenario_2.json`, `scenario_3.json` from section 4.3, shaped like the `POST /api/messages` body. Scenario 2 also records the "I clicked" tap.
3. `.gitkeep` in `data/raw/`, `data/fixtures/` and `eval/`.
4. `.env.example` listing every variable from config.py with a one-line comment each.
5. `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `*.sqlite`, and `data/raw/*` except `.gitkeep`. Fixtures and `eval/` are committed.
6. README "Setup" section with PowerShell commands: venv in `backend/`, install, copy `.env.example` to `.env`, `uvicorn app.main:app --reload --port $env:API_PORT` from `backend/`, `npm install` and `npm run dev` in `frontend/`, `pytest`. T-Mobile's files go in `data/raw/`.

## 4. Verify and push

1. `pytest` passes from `backend/`, the API starts and `GET /api/inbox` returns mocks, and `npm run build` passes.
2. Update `CHANGELOG.md`: add a Done log line for the scaffold and note anything you were unsure about under Blockers.
3. Commit `Scaffold SentinelAI backend, frontend and contracts` and push to `main` (the one allowed direct code push).

## 5. Create one folder per agent

After the push, follow `POC_MVP.md` section 12.2:

1. If `C:\HackUTD26\.env` doesn't exist, copy it from `.env.example` and ask me to paste my keys into it myself. Wait until I say "done" or "skip". Never print keys.
2. Create the worktrees `..\HackUTD26-cc`, `..\HackUTD26-codex` and `..\HackUTD26-design` from `origin/main` with `--detach`.
3. Copy `.env` into each one, then set `API_PORT` and `WEB_PORT` in each copy from the table in section 12.1 (cc: 8001 and 5174, codex: 8002 and 5176, design: 8003 and 5175). Leave the main folder on 8000 and 5173.
4. Run `git worktree list` and show me the result.

Finish with: the tree, how to run it, the worktree list, and what to run next (`prompts/claude-code-01-issues.md` in Claude Code, opened at `C:\HackUTD26-cc`).
