# SentinelAI: Full handoff (as of 2026-11-07 23:40 CT)

Read this first if you are a new assistant (ChatGPT, Codex, Claude, Cursor) picking up the project. It summarizes everything; the detailed sources of truth are linked.

## 1. The project in one minute

- **What:** SentinelAI, a scam protection agent for phone and bank customers. A suspicious text arrives → personal details are redacted → a classifier tags the scam type → a **Nemotron agent plans its own checks** (link, sender, scam campaigns, the customer's real bank activity and bills through **Capital One's Nessie API**, public scam reports through **Gemini**) → the customer sees one calm result card: verdict in words, honest confidence, a one-sentence reason, at most 3 actions. If they already clicked, **recovery mode** finds the suspicious transaction and asks "Was this you?".
- **Demo customer:** Linda, 67. Three scenarios (POC_MVP 4.3): (1) fake Capital One "account locked" text → likely scam, no unusual activity; (2) same text, Linda tapped "I clicked" → agent re-plans and finds a planted $900 payment to "Unknown Payee"; (3) fake T-Mobile "bill overdue" text → different plan, bill shown as paid, matched to a scam campaign.
- **Event:** HackUTD 2026. **Final Devpost submission 12:00 PM Sunday Nov 8; judging 1:00–4:00 PM.** Initial Devpost draft is already submitted.
- **Tracks:** T-Mobile (scam protection; judged on creativity, impact, usability, security and privacy, detection accuracy), NVIDIA (Nemotron beyond a chatbot), Capital One (best use of Nessie), plus HackUTD Best Design and General. MLH Gemini API prize applies if Gemini ships.
- **Repo:** https://github.com/its-arnavtech/HackUTD26 (private). Team: Arnav (`its-arnavtech`) and Lavanya (`lavanyabansal03`).

## 2. Sources of truth in the repo

| File | What it holds |
| --- | --- |
| `docs/POC_MVP.md` | Scope, architecture, API (7.1), agent loop (7.2), guardrails (7.4), screens (8), demo script (9), timeline (10), risks and cut order (11), agents and folders (12), the issue list (13), definition of done (14) |
| `docs/DATA_SPEC.md` | Every data contract: what Nemotron receives (3.1), tool results (3.2), agent output (3.3), trail (3.4), Gemini inputs and rules (4), redaction (5), Nessie objects (6), metrics (7) |
| `AGENTS.md` | Rules for every coding agent: ownership, one agent per folder, workflow, the shared-branch exception, the CHANGELOG handoff protocol, rules that must never break |
| `CHANGELOG.md` | Status board for every issue, In progress blocks, Done log, Decisions, Blockers. **Read Decisions top-down for recent changes.** |
| `docs/POC_RESULTS.md` | Gate P1 to P5 results and G1 results |
| `docs/SECURITY_PLAN.md` | Lavanya's security plan (retention, SSRF, honest wording: "privacy-preserving audit log", never "zero-knowledge") |
| `prompts/` | The prompt for each tool, plus `resume-any-agent.md` for picking up stopped work |
| GitHub issue #38 | Pinned build tracker |

## 3. Tech and integrations

- **Backend:** Python 3.12 venv (system Python on Arnav's laptop is 3.10; use `py -3.12`), FastAPI, Pydantic v2, pytest, SQLite. **Frontend:** Vite, React, TypeScript, Tailwind, Vitest. No Docker, Postgres, vector DBs or WebSockets; the UI polls.
- **Nemotron:** NVIDIA hosted API, OpenAI-compatible, `https://integrate.api.nvidia.com/v1`. Agent model `nvidia/nemotron-3.5-bolt-e4b` (native tool calling passed 5/5; JSON-action fallback also 5/5). Embeddings `nvidia/nemotron-3.5-embed-1b`. Local laptop fallback tried and dropped (3/5); **replay mode is the fallback**.
- **DeepSeek:** used only offline to generate the training/test dataset (T-Mobile provided no data).
- **Gemini:** grounded Google Search for the public-report tool (L4 smoke test, L10 tool). **Waiting on a `GEMINI_API_KEY`.** Never substitute another model for it; it must cite sources.
- **Nessie (live quirks, all handled in code):** must use `https://api.nessieisreal.com`; list endpoints return 404 "No … found" for empty lists (treated as `[]`); amounts are stored as whole dollars; **no DELETE for purchases**; **transfers cannot name a receiving account**, so the planted $900 is a **purchase at merchant "Unknown Payee" at 09:31**, 17 minutes after scenario 2's 09:14 message (the exact time lives in `data/nessie_seed.json`). Demo customer is **"Linda Sentinel", 802 Demo Way**; an older duplicate Linda at 800 and a "Probe Throwaway" customer are abandoned. A purchase is flagged at 10x Linda's 30-day median (her cheap coffees pull the median to about $18); the $900 shows as about 23x.
- **Record and replay:** every external call goes through `backend/app/integrations/cache.py` with `DEMO_MODE=live|record|replay`. Record all three scenarios before the demo (A19).
- **Keys** live in each folder's `.env` (never committed, never printed): `NVIDIA_API_KEY`, `NEMOTRON_MODEL`, `NEMOTRON_EMBED_MODEL`, `DEEPSEEK_*`, `NESSIE_API_KEY`, `NESSIE_BASE_URL` (https), `HF_TOKEN` (optional), `GEMINI_API_KEY` (missing), `PHONE_HASH_SALT` (required; redaction refuses to run without it), `USE_MOCKS`, `DEMO_MODE`, `API_PORT`, `WEB_PORT`.

## 4. Who works where

| Person | Tool | Folder on Arnav's laptop | Ports | Branching |
| --- | --- | --- | --- | --- |
| Arnav | Claude Code (Opus 5.5), session A | `C:\HackUTD26` | 8000 / 5173 | Branch per issue |
| Arnav | Claude Code, session B | `C:\HackUTD26-main` | own | Branch per issue |
| Arnav | Claude Code (original) | `C:\HackUTD26-cc` | 8001 / 5174 | Shared branch `arnav-shared` |
| Arnav | Codex connections (GPT-6) | `C:\HackUTD26-codex` | 8002 / 5176 | Shared `arnav-shared` (local branch `codex-shared`, push `HEAD:arnav-shared`) |
| Arnav | Codex design (GPT 6 Astra) | `C:\HackUTD26-design`, lab at `C:\HackUTD26-design-lab` | 8003 / 5175 | Branch per issue |
| Arnav | Cursor (cloud agent, cannot comment on issues, no Nessie key) | cloud | n/a | Branch per issue, `cursor/...` |
| Lavanya | Claude Code (Opus 5.5) | her own clone | her own | Branch per issue (`l*-...`) |

Rules that matter most: one agent per folder; stage only your own files on `arnav-shared` and use `git pull --rebase=merges` there; **merge PRs with merge commits, never squash**; `contracts.py` and `types.ts` change only in `[contracts]` PRs; CHANGELOG conflicts keep both sides. Usage limits: Codex and Cursor have run out once each tonight; any agent can resume another's work with `prompts/resume-any-agent.md`.

## 5. Status

### Done and merged (closed issues)
A21 dataset (2,596 generated messages; split train 1,818 / val 390 / test 388, test = separate prompt set + 50 hand-written), A1 baseline, A2 Nessie client and seed, A3 redaction, A4 Nemotron connection, A5 Hugging Face (public UCI SMS set, 5,574 rows; DistilBERT cached), A6 CI and dev scripts, A7 phone shell, inbox and gallery, A8 POC report, A9 feature extraction, A10 link and sender checks (+ blocklist from A1's train split), A11 Nessie tools, A12 campaign store (scenario 3 matches a cluster of 28 historical messages, similarity 0.924; 24-hour count is 0 because the training timestamps end Nov 6), A13 evaluation harness, A14 result card, trail and privacy panel, A22 Devpost draft, L1 replay cache, L2 core runtime, L3 state store and job runner, L5 tool registry, L7 classifier (PR #58), L8 agent loop (PR #56).

### Gates
| Gate | Result |
| --- | --- |
| P1 dataset and baseline | Pass. Baseline macro F1 0.807, FPR 0.127 |
| P2 Nemotron tool calling | Pass, 5/5 |
| P3 Gemini cited search | Pending the Gemini key |
| P4 Nessie seed | Pass, live (second run created 0) |
| P5 redaction | Pass, 20/20 |
| G1 scenario 1 with real agent | PR #61 open |
| G2 all scenarios in the app | Not yet |

### Accuracy numbers (for the T-Mobile pitch)
- Synthetic test (388, redacted): baseline macro F1 0.807 / FPR 0.127 → L7 **0.878 / 0.113**.
- Public real SMS set: L7 binary F1 0.530 vs baseline 0.588 (worse), with fewer false positives. An **L7 follow-up issue** is open: split the public set 50/50, train on one half, score only the held-out half, report old and new side by side. Be honest about this in the pitch.

### Open PRs (merge with merge commits once CI is green)
| PR | What | Notes |
| --- | --- | --- |
| #61 | G1: scenarios with the real L8 agent | Review results in `docs/POC_RESULTS.md` |
| #60 | Privacy chips match lowercase hex phone tags | Small frontend fix |
| #57 | L6 privacy audit log + `GET /api/privacy/{id}` | Had conflicts after L8; Claude Code session B is fixing and adding one-line hooks into L8; Lavanya must add hooks in L9 (listed in the PR) |
| #55 | A15 recovery UI + A16 consent, campaign view, accuracy page | Had conflicts; Claude Code session A fixing. #54 closed as superseded |

### Work in progress (branches without PRs yet)
- `l9-pipeline`: **Lavanya, L9 API endpoints and pipeline. This is the critical path**; the live app waits on it.
- `a17-live-api`: Claude Code session A, A17 frontend on the live API.

### Open issues and owners
| Issue | Owner / agent | Next step |
| --- | --- | --- |
| L9 #24 API and pipeline | Lavanya | Finish, include L6 hooks |
| L11 #27 recovery re-plan | Arnav's Claude Code session B, **if Lavanya hasn't started it** (check for an `l11` branch or a claim first) | After G1 and #57 |
| L6 #16 | Claude Code session B | Get #57 green and merged |
| A15 #29, A16 #30 | Claude Code session A | Get #55 green and merged |
| A17 #31 | Claude Code session A | Wire to L9 when it merges |
| L7 follow-up | Codex connections | Public-set split fix |
| L4 #12, L10 #26 Gemini | Codex connections | Needs `GEMINI_API_KEY` (free at aistudio.google.com); follow DATA_SPEC 4 exactly |
| G1 #25 | Shared | Merge #61 if results are right |
| A18 #32 end-to-end tests | Claude Code session B | Replay mode, real agent, all 3 scenarios |
| G2 #33 | Shared | All 3 scenarios in the app, live and replay |
| A19 #34 fixtures + backup video | Claude Code + Arnav | After G2; record with `DEMO_MODE=record`, test with Wi-Fi off |
| A20 #35 Capital One + Best Design pitch | Arnav | After G2 |
| L12 #36 NVIDIA + T-Mobile pitch, Devpost | Lavanya | After G2 |
| G3 #37 rehearse 3× | Both | Each run under 3:00 |
| Codex design | polish + `docs/screenshots/` for Devpost | Branch `design-polish` |

## 6. Plan to the deadline

1. **Now to ~00:30:** merge #61, #60, #55, #57 as each goes green. Lavanya finishes L9.
2. **~00:30 to 03:00:** L9 merges → A17 wired → L11 and L10 (if Gemini key) → **G2**. Then both people bug-bash in the play folder (below).
3. **Overnight / early morning:** A18 tests, L7 follow-up, design polish, screenshots.
4. **By 10:30:** A19 fixtures recorded and replay tested with Wi-Fi off, backup video; **code freeze**.
5. **10:30 to 11:45:** A20 and L12 pitch paragraphs, final Devpost text (one paragraph per track naming its criteria and demo moment), G3 rehearsals.
6. **Before 12:00:** final Devpost submission.

Cut order if late (POC_MVP 11): campaign view polish → Gemini tool → consent polish → RDAP. **Never cut:** scenario 3's bill check, the trail, the privacy panel, the accuracy table.

## 7. How to run and explore it yourself

Use a separate play folder so you don't disturb the agents:

```powershell
cd C:\HackUTD26
git fetch
git worktree add --detach ..\HackUTD26-play origin/main
Copy-Item .env ..\HackUTD26-play\.env
cd ..\HackUTD26-play
(Get-Content .env) -replace '^API_PORT=.*','API_PORT=8010' -replace '^WEB_PORT=.*','WEB_PORT=5180' | Set-Content .env
cd backend; py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; python -m pip install -r requirements.txt
python -m scripts.run_scenario 1      # also 2 and 3; --json for raw output
cd ..\frontend; npm install; cd ..
.\scripts\dev.ps1
```

Open `http://localhost:5180/gallery`, `/result/msg_0001`, `/trail/msg_0001`, `/privacy/msg_0001`. Update later with `git fetch; git checkout --detach origin/main`. Set `USE_MOCKS=false` in that folder's `.env` once L9 and A17 have merged.

## 8. Demo script (3 minutes)

0:00 hook (Linda gets the "account locked" text) · 0:20 accuracy page (ours vs baseline, by category, false positives, real public set) · 0:40 scenario 1 live (trail fills in, Nessie shows no unusual activity, verdict, privacy panel) · 1:20 scenario 2 ("I clicked" → re-plan → $900 at Unknown Payee → "Was this you?" → checklist) · 2:00 scenario 3 (different plan, bill paid, campaign, cited public reports if Gemini ships) · 2:40 close: "Nemotron plans, Nessie checks the money, the customer decides."

## 9. Rules that must never break

Redaction runs first; Nemotron and Gemini receive only what DATA_SPEC allows; the test split is never used for training or tuning; every protective action waits for the customer's tap; the UI never shows a phone number or link from search or model output; wording says what was checked ("we found no unusual activity"), never "your account is fine"; no percentages inside the phone UI.

## 10. Gotchas

- `AGENTS.md` keeps picking up Windows line endings in `C:\HackUTD26`; `git restore AGENTS.md` before pulling if it shows as modified.
- On `arnav-shared`, use `git pull --rebase=merges` (a plain rebase tries to flatten merge commits).
- Cursor's cloud agent can't comment on issues and has no Nessie key; anything needing live Nessie runs on Arnav's laptop.
- The scenario domains aren't registered, so RDAP reports "no registration record" rather than a domain age.
- T-Mobile's official short codes are unknown (left empty in `data/brands.json`); Capital One's come from its SMS terms page.
- CI must be green before merging; `requirements.txt` pins numpy 2.4.6 for Python 3.11 support and includes pyarrow for A13.
