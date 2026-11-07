# Prompt 01: Scaffold the repo (Arnav runs this first)

Paste everything below the line into Claude Code, opened at the repo root.

---

You are setting up the SentinelAI repo for a 24-hour hackathon build by two people. Read `CLAUDE.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md` completely before doing anything. They are the source of truth.

Your job is the **scaffold only**: structure, shared contracts, mocks, stubs and setup. Do **not** implement features; those belong to the GitHub issues created next. Each stub should make it obvious which issue fills it in.

## 1. Backend (`backend/`)

1. Create the layout from `docs/POC_MVP.md` section 6, with `__init__.py` files so `python -m` works from `backend/`.
2. `requirements.txt` with pinned versions: fastapi, uvicorn[standard], pydantic (v2), pydantic-settings, httpx, openai (for NVIDIA's OpenAI-compatible API), google-genai, scikit-learn, pandas, numpy, tldextract, rapidfuzz, python-dotenv, pytest. Do not add spaCy; mention in the README that it is optional for redaction.
3. `app/config.py`: settings loaded from env: `NVIDIA_API_KEY`, `NEMOTRON_BASE_URL` (default `https://integrate.api.nvidia.com/v1`), `NEMOTRON_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `NESSIE_API_KEY`, `NESSIE_BASE_URL` (default `http://api.nessieisreal.com`), `DEMO_MODE` (`live`, `record`, `replay`; default `live`), `USE_MOCKS` (default `true`), `PHONE_HASH_SALT`.
4. `app/contracts.py`: Pydantic v2 models and enums for **every** JSON object in `docs/DATA_SPEC.md`: message, redaction report, URL info, features, classifier output, agent input (3.1), each tool's args and result (3.2), Gemini input and output (4.1, 4.3), agent result (3.3), trail entry (3.4), campaign, metrics, privacy view, inbox item, result-poll response. Enums for verdict, confidence words, actions, sender type, trail kind, source type, demo mode.
5. `app/mocks/`: JSON mock responses for every API route, valid against the contracts. Base them on the three scenarios in `POC_MVP.md` section 4.3.
6. `app/main.py`: every route in `POC_MVP.md` section 7.1. While `USE_MOCKS=true`, routes return the mocks. `GET /api/messages/{id}/result` must simulate progress: `queued`, then `running` with the trail growing by one entry per poll, then `done` with the result. Mark mock code with `# MOCK: replaced by <issue id>`.
7. Stub modules for every file in section 6 with typed function signatures that use the contracts, a docstring naming the issue ID that implements it (from section 12), and `raise NotImplementedError`.
8. `scripts/`: stub `seed_nessie.py`, `run_baseline.py`, `train_classifier.py`, `evaluate.py`, `run_scenario.py` the same way.
9. `tests/test_contracts.py`: every mock file validates against its model. `tests/test_api_mocks.py`: every route returns 200 with mocks on.

## 2. Frontend (`frontend/`)

1. Vite + React + TypeScript + Tailwind. Proxy `/api` to `http://localhost:8000`.
2. `src/types.ts` mirroring `contracts.py` exactly.
3. `src/api.ts` with one typed function per route, plus a `pollResult(id, onUpdate)` helper that polls every second until `done`.
4. A `PhoneFrame` component (about 390x844, centered) and placeholder screens from `POC_MVP.md` section 8: Consent, Inbox, ResultCard, HowWeChecked, PrivacyPanel, Recovery, CampaignView, plus an AccuracyPage outside the phone frame. Each placeholder shows its name and the issue ID that builds it.
5. Design tokens in Tailwind config following section 8: 18px base text, 44px minimum tap targets, amber for likely scam, gray for not sure, green for likely safe.

## 3. Data and config

1. `data/brands.json`: entries for Capital One (`capitalone.com`) and T-Mobile (`t-mobile.com`) with `official_domains`, and empty `official_short_codes` and `official_sender_ids` arrays marked TODO. Do not invent short codes.
2. `data/scenarios/scenario_1.json`, `scenario_2.json`, `scenario_3.json` from section 4.3, shaped like the `POST /api/messages` body. Scenario 2 also records that the customer taps "I clicked".
3. `data/raw/.gitkeep`, `data/fixtures/.gitkeep`, `eval/.gitkeep`.
4. `.env.example` with every variable from config.py and a one-line comment each.
5. `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `*.sqlite`, and `data/raw/*` except `.gitkeep`. Fixtures and `eval/` **are** committed.

## 4. README

Add a "Setup" section with PowerShell commands: create and activate a venv in `backend/`, install requirements, copy `.env.example` to `.env`, run `uvicorn app.main:app --reload` from `backend/`, run `npm install` and `npm run dev` in `frontend/`, run `pytest`. Note where T-Mobile's dataset files go (`data/raw/`).

## 5. Verify, then push

1. `pytest` passes from `backend/`.
2. The API starts and `GET /api/inbox` returns mock data.
3. `npm run build` passes in `frontend/`.
4. Commit everything as `Scaffold SentinelAI backend, frontend and contracts` and push to `main`.

Finish with a short summary: the tree, how to run it, and anything you were unsure about.
