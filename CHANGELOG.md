# CHANGELOG and handoff log

This file is how any agent (Claude Code, Codex, Cursor) or person sees what's done, what's in progress, and what's left, and picks up where another agent stopped. The protocol is in `AGENTS.md` section 5. Short version:

1. **Claim:** set your row to `in progress`, add an In progress block, comment on the issue, push.
2. **Checkpoint** after each sub-task, every 30 minutes, and whenever context runs long: update your block, commit, push, and post the block as an issue comment.
3. **Finish:** in the PR, delete your block, add a Done log line, set your row to `done`.
4. **Resume:** read the issue's latest checkpoint comment, switch to its branch, continue from "Next step".

On merge conflicts in this file, keep every entry from both sides. For Status board rows, keep the most advanced status (`todo` < `in progress` < `in review` < `done`; `blocked` needs a note in Blockers).

---

## Status board

Statuses: `todo`, `in progress`, `blocked`, `in review`, `done`. Issue numbers are added when the issues are created.

| ID | Issue | Owner | Agent | Milestone | Depends on | Status | Branch / PR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A21 | Synthetic message dataset generator | Arnav | Claude Code | POC | scaffold | done | #1 · #41 (arnav-shared) |
| A1 | Dataset loader, stratified split and baseline metrics | Arnav | Claude Code | POC | A21 | done | #2 · #41 (arnav-shared) |
| A2 | Nessie client and idempotent seed script | Arnav | Cursor | POC | scaffold | todo | #3 |
| A3 | Redaction module | Arnav | Codex | POC | scaffold | done | #4 · #41 (arnav-shared) |
| A4 | Nemotron connection and tool-calling smoke test | Arnav | Codex | POC | scaffold | done | #41 (arnav-shared) |
| A5 | Hugging Face connection | Arnav | Codex | POC | scaffold | done | #41 (arnav-shared) |
| A6 | Dev infrastructure: CI, dev scripts, worktrees | Arnav | Cursor | POC | scaffold | done | #7 · PR #40 |
| A7 | Phone shell and inbox on the mock API | Arnav | Codex design (GPT 6 Astra) | POC | scaffold | todo | #8 |
| L1 | Record and replay cache | Lavanya | Claude Code | POC | scaffold | done | #9 · PR #42 |
| L2 | Core runtime: app factory, settings, logging, errors | Lavanya | Claude Code | POC | scaffold | done | #10 · PR #39 |
| L3 | State store and background job runner | Lavanya | Claude Code | POC | L2 | done | #11 · PR #47 |
| L4 | Gemini grounded search smoke test (Sunday morning, when the Gemini key is set) | Lavanya | Claude Code | POC | scaffold | todo | #12 |
| A22 | Initial Devpost draft by 11:00 PM Saturday | Arnav | any | POC | none | todo | #13 |
| A8 | POC gate report | Arnav | Claude Code | POC | A1, A2, A3, A4, L4 | todo | #14 |
| L5 | Tool registry and runtime | Lavanya | Claude Code | MVP | L2 | done | #15 · PR #48 |
| L6 | Privacy audit log and `/api/privacy` | Lavanya | Claude Code | MVP | L3, L5 | todo | #16 |
| A9 | Feature extraction | Arnav | Codex | MVP | A3 | todo | #17 |
| A10 | `check_link` and `check_sender` tools | Arnav | Cursor | MVP | L1 | done | #18 · PR #43 |
| A11 | Nessie tools | Arnav | Cursor | MVP | A2 | todo | #19 |
| A12 | Campaign store, seeding and `match_campaign` | Arnav | Codex | MVP | A1, A3 | todo | #20 |
| A13 | Evaluation harness | Arnav | Claude Code | MVP | A1 | todo | #21 |
| L7 | Improved classifier | Lavanya | Claude Code | MVP | A1, A9, A13 | todo | #22 |
| L8 | Agent loop with plan, re-plan and guardrails | Lavanya | Claude Code | MVP | A4, L5 | todo | #23 |
| L9 | API endpoints and pipeline orchestration | Lavanya | Claude Code | MVP | L3, L8 | todo | #24 |
| G1 | Gate: scenario 1 end to end in the CLI | Both | any | MVP | A3, A9, A10, A11, L8 | in progress | #25 · `cursor/g1-run-scenario-55c7` (prep: stand-in agent until L8) |
| L10 | `public_scam_reports` tool | Lavanya | Claude Code | MVP | L4, L5 | todo | #26 |
| L11 | Recovery mode re-plan | Lavanya | Claude Code | MVP | L8, A11 | todo | #27 |
| A14 | Result card, "How we checked" and privacy panel | Arnav | Codex design (GPT 6 Astra) | MVP | A7 | todo | #28 |
| A15 | Recovery UI | Arnav | Codex design (GPT 6 Astra) | MVP | A14 | todo | #29 |
| A16 | Consent screen, campaign view and accuracy page | Arnav | Codex design (GPT 6 Astra) | MVP | A7 | todo | #30 |
| A17 | Frontend on the live API | Arnav | Cursor | MVP | A14, A15, A16, L9 | todo | #31 |
| A18 | End-to-end scenario tests | Arnav | Claude Code | MVP | G1 | todo | #32 |
| G2 | Gate: all three scenarios end to end in the app | Both | any | MVP | A17, A18, L10, L11 | todo | #33 |
| A19 | Replay fixtures and backup video | Arnav | Claude Code | Demo | G2 | todo | #34 |
| A20 | Capital One and Best Design pitch | Arnav | any | Demo | G2 | todo | #35 |
| L12 | NVIDIA and T-Mobile pitch, Devpost | Lavanya | Claude Code | Demo | G2 | todo | #36 |
| G3 | Rehearse the 3-minute demo three times | Both | any | Demo | A19, A20, L12 | todo | #37 |

---

## In progress

<!-- One block per active issue. Copy the template, keep it current at every checkpoint. -->

### G1 Gate: scenario 1 end to end in the CLI (#25), prep
- Agent: Cursor (Claude Opus 5.5, cloud agent) · Person: Arnav · Folder: Cursor cloud VM (`/workspace`) · Branch: `cursor/g1-run-scenario-55c7`
- Started: 2026-11-07 19:17 · Last checkpoint: 2026-11-07 20:40
- Done so far:
  - Claimed (CHANGELOG only)
  - `scripts/run_scenario.py`: redaction, sender redaction, URL features, message features, claimed brand and classifier each use the real module (or, for the classifier, A1's baseline) once it stops raising `NotImplementedError`, and a marked stand-in until then. The stages table prints which one ran. Tools run through a `TOOLS` table, with errors returned as data. The stand-in agent (rule-based plan and verdict, no model) is the single line `AGENT = stand_in_agent`. Supports scenarios 1 to 3 (2 runs in recovery mode) and `--json`.
  - 9 tests (`tests/test_run_scenario.py`). The suite passes on 3.11 and 3.12 and in replay mode.
  - Verified in a scratch merge with A10 and A11 (not committed) against the seeded fake Nessie: scenario 1 gives plan `check_link, check_sender, nessie_recent_activity` (the expected plan) and `likely_scam / very likely`; scenario 2 flags the planted transfer; scenario 3 finds the paid bill
  - PR #46 open
  - 2026-11-07 20:22: rebased onto `main`; real A3 redaction and A1's baseline are picked up automatically (baseline trained once per run, train split only). Redaction needs `PHONE_HASH_SALT` in `.env`, and the CLI says so instead of falling back to the stand-in. Scratch merge with #43 and #45: 321 tests pass, scenario 1 runs with real redaction and gives the expected plan and `likely_scam / very likely`
  - 2026-11-07 20:40: moved off the #44/#45 chain onto `main` (#40 and #43 merged), so it can merge before #44; 296 tests pass
- Next step (exact): when L8 merges, change `AGENT = stand_in_agent` to `AGENT = run_agent` in `scripts/run_scenario.py`. Register the tools with L5 (TODOs in `tools/link.py`, `tools/sender.py`, `tools/nessie_tools.py`). Run `python -m scripts.run_scenario 1` with the real seed (A2) and check the trail and verdict. Then finish G1.
- Files touched: `backend/scripts/run_scenario.py`, `backend/tests/test_run_scenario.py`, `CHANGELOG.md`
- How to run or test: from `backend/`: `python -m scripts.run_scenario 1`, then `python -m pytest`
- Notes and gotchas: set `PHONE_HASH_SALT` in `.env` (any random string) or the run stops at redaction. Based directly on `main` (not on #44): on `main` today, redaction and `check_link`/`check_sender` are real, the classifier is A1's baseline, and the Nessie tools say "not available yet" until #44 and #45 merge; scenario 1 already gives the expected plan and `likely_scam / very likely`. `match_campaign` (A12) and `public_scam_reports` (L10) aren't in the stand-in's `TOOLS` table, so scenario 3's plan differs from its expected plan until L8 drives the tools through L5's registry.
- Resumed by: none



```
### <ID> <title> (#<issue>)
- Agent: <tool> (<model>) · Person: <Arnav | Lavanya> · Folder: <path> · Branch: <branch>
- Started: YYYY-MM-DD HH:MM · Last checkpoint: YYYY-MM-DD HH:MM
- Done so far:
  - ...
- Next step (exact): ...
- Files touched: ...
- How to run or test: ...
- Notes and gotchas: ...
- Resumed by: <tool> from <tool>, if any
```


---

## Done log

Newest first. One line per finished issue or setup step: `YYYY-MM-DD HH:MM · ID · tool · PR · summary · follow-ups`.

- 2026-11-07 20:19 · L5 · Claude Code (Opus 5.5, Lavanya) · #48 · `agent/registry.py`: `ToolRegistry` with the six built-in tools registered (tool modules untouched); OpenAI `tools=[...]` schemas with refs inlined and injected fields hidden; `call_tool` validates args, runs with a per-tool timeout (Gemini 20 s, others 10 s), returns `ToolCall` with errors as data (`unknown_tool`, `invalid_args`, `timeout`, `unavailable`, `tool_error`) and generic messages; `on_call` gets a `PrivacyRecipient` with exactly what the tool received; 33 tests (266 pass) · follow-ups: L8 uses `openai_tool_schemas()` and `call_tool`; L6 stores the `on_call` records
- 2026-11-07 19:32 · A3 · Codex (GPT-6) · #41 · Local redactor, HMAC phone/sender handling, private URL ordering and report; P5 20/20, 50 redaction tests; full merged backend 219 passed in credential-free child process; real L1 adapters synced · follow-ups: A9, A13 redaction-cost evaluation; regex name/address limits documented

- 2026-11-07 19:18 · A1 · Claude Code (Opus 5.5) · #41 · Loader into `Message`, saved 70/15/15 split (`data/generated/splits.json`: train 1,818 / val 390 / test 388, test = `test_v1` + hand-written), baseline keyword rules + TF-IDF + LR; `eval/baseline_metrics.json` test macro F1 0.807, FPR 0.127; `eval/baseline_details.json` adds val, per-subset scores and confusion; 121 tests pass · follow-ups: rescore on redacted text once A3 lands (A13 redaction cost)
- 2026-11-07 19:07 · A5 · Codex (GPT-6) · #41 · HF login and .env token verified; public SMS 5574 rows downloaded; DistilBERT cached; pinned revisions/checksums; local Bolt 3/5, stopped and documented; full shared backend suite 108 passed · follow-ups: A13/L7 use handoff; local fallback not selected
- 2026-11-07 18:58 · A10 · Cursor (Claude Opus 5.5, cloud agent) · #43 · `check_link` (look-alike, official domain, shortener, TLD, blocklist, RDAP age) and `check_sender` (official short codes, long codes, sender IDs, email domains) as plain functions; `integrations/rdap.py`; blocklist from a provisional train split; Capital One channels in `brands.json` from its own SMS terms page ; RDAP goes through L1's `cached_call` (a replay miss counts as "lookup not available") · follow-ups: register both specs when L5 merges; point the blocklist builder at A1's split (`data/generated/splits.json` ids, not the `data/splits/train.jsonl` it expects) and rerun `python -m scripts.build_blocklist`

- 2026-11-07 19:00 · A21 · Claude Code (Opus 5.5) · #41 · Taxonomy v1 (8 scam categories + `legit`); DeepSeek generator with separate `train_v1`/`test_v1` prompt sets, cached calls, quality filter, dedupe incl. test-vs-train; 2,596 messages (train_v1 2,208, test_v1 338, hand-written 50), 38% legit; datasheet `data/generated/README.md`; 100 tests pass incl. offline rebuild · follow-ups: hand-written set approved by Arnav; A1 splits per the Decisions entry; mock `metrics.json` says `legitimate`, real id is `legit` (A13)
- 2026-11-07 19:07 · A4 · Codex (GPT-6) · #41 · Hosted Bolt native 5/5 (median 3082ms, worst 3908ms), JSON fallback also 5/5 (1128ms, 2171ms), embedding 2048D; mocked tests pass · follow-ups: L1 cache and L8 production loop

- 2026-11-07 19:29 · L3 · Claude Code (Opus 5.5, Lavanya) · #47 · `app/state.py`: in-memory SQLite `StateStore` (messages, runs, results, trail), `JobRunner` (queued, running, done on worker threads, context copied so logs keep `message_id`), `TrailWriter` as the agent's `on_trail` (`.add()` numbers steps); a new run (recovery) supersedes the old one; a crashed job ends `done` with an honest unsure result; non-mock inbox, message, result, clicked and reset routes use the store via `pipeline.pipeline_job`; 20 tests (104 pass) · follow-ups: L9 fills `run_pipeline` and reloads scenario messages on reset; L11 calls `store.set_was_this_you`
- 2026-11-07 18:56 · L1 · Claude Code (Opus 5.5, Lavanya) · #42 · `integrations/cache.py`: `cached_call(service, request, fn)` with live, record and replay; key = SHA-256 of the canonical request (order-independent, secret field names dropped, optional `volatile` fields); fixtures at `data/fixtures/<service>/<key>.json`, written atomically; replay never calls out and raises `FixtureMissingError` on a miss; `decode=` rebuilds pydantic types; 21 tests (57 pass) · follow-ups: A2 (Nessie), A10 (RDAP) and L4 (Gemini) wrap their calls with `cached_call`; A4 already does
- 2026-11-07 18:46 · A6 · Cursor (Claude Opus 5.5, cloud agent) · #40 · CI (`pytest` on Python 3.11 and 3.12, `npm run build` on Node LTS, Windows smoke test of `dev.ps1`, no secrets); `scripts/dev.ps1` starts both servers on the folder's `.env` ports; `docs/WORKTREES.md`; `numpy` pinned to 2.4.6 for Python 3.11 · follow-ups: make CI required on `main` in branch protection; tick #7's checkboxes (cloud agent can't edit issues)
- 2026-11-07 18:38 · L2 · Claude Code (Opus 5.5, Lavanya) · #39 · `create_app()` factory; settings validated at startup with clear messages (missing Nemotron key is an error only when a real route calls out in live/record); JSON logs carrying `message_id` (`app/logs.py`); one JSON error shape (`app/errors.py`); `GET /api/health` with integration modes; per-route mocks via `MOCK_ROUTES` / `LIVE_ROUTES`; 27 new tests (63 pass) · follow-ups: L3's runner must copy the context so logs keep `message_id`
- 2026-11-07 18:14 · setup (issues) · Claude Code (Opus 5.5) · direct to main · Labels, milestones (POC, MVP, Demo) and all 37 issues #1 to #37 from POC_MVP section 13 (A* and G* assigned to its-arnavtech, L* unassigned), dependencies linked by number, pinned tracker #38 · follow-ups: add Lavanya as a collaborator
- 2026-11-07 18:11 · setup (folders) · Claude Code (Opus 5.5) · local only · Worktrees `C:\HackUTD26-cc` (8001/5174), `C:\HackUTD26-codex` (8002/5176), `C:\HackUTD26-design` (8003/5175) detached at origin/main, each with its own `.env`; main stays on 8000/5173 · follow-ups: keys were skipped, so paste them into each folder's `.env`
- 2026-11-07 18:06 · setup (scaffold) · Claude Code (Opus 5.5) · direct to main (0772b5d, a35986e) · Backend contracts, config, mock API with simulated progress, stubs naming their issue, tests (36 pass); Vite + React + TS + Tailwind shell with `types.ts`, `api.ts` and placeholder screens (build passes); data files, `.env.example`, README setup. Includes the cff46b6 plan changes (DeepSeek vars, Bolt E4B default, taxonomy placeholder, `data/generated/`, A21 script stub) · follow-ups: none

- 2026-11-07 17:50 · setup · Claude (chat) · direct to main · Re-split work across Arnav's four agents and Lavanya's Claude Code; added AGENTS.md, CHANGELOG.md, Cursor rule and per-tool prompts · next: Cursor runs `prompts/cursor-01-scaffold.md`
- 2026-11-07 17:30 · setup · Claude (chat) · direct to main (2d4f228) · Added POC/MVP plan, data spec and first prompts

---

## Decisions

- 2026-11-07 20:19 · L5 tool contract: a tool is a plain function `fn(args: ArgsModel, agent_input: AgentInput) -> ResultModel` in its own module; the registry imports and registers it in `builtin_tools()`, so tool authors don't touch the registry. Raise `NotImplementedError` until built (the agent sees "unavailable"). `match_campaign`'s `message_id` is filled in by code from the agent input, not by the model.
- 2026-11-07 19:32 · A4/A5 integration after L1 merge: removed scaffold bypasses from Nemotron and HF bootstrap; cached_call now receives the selected DEMO_MODE explicitly. Offline tests verify recording, credential-free replay and strict misses with no network. Local-fallback doc updated; production scenarios still need A19 fixtures. Full merged backend suite: 219 passed; test process clears inherited service credentials because L2 make_settings ignores .env but still reads environment variables (no global or .env changes).

- 2026-11-07 19:25 · A3 P5: local regex redaction with span priorities (whole URLs before embedded emails/phones/digits), occurrence counts, HMAC-SHA256 phone tags truncated to 16 hex chars, and no fixed salt fallback. US phone formatting and extensions normalize to one tag. Known brands/IDs come from data/brands.json; amounts/deadlines and contextual short codes remain. Regex names/addresses are heuristic; redact(text, person_names=...) accepts known customer names locally. Unknown alphanumeric sender values are suppressed to <UNKNOWN_SENDER>. All incoming phone/URL redaction placeholders fail closed: raw text is untrusted, and forged tags must not bypass masking or corrupt A9 URL mapping. raw_urls stays private/in memory; no contract changes.
- 2026-11-07 18:58 · A10: `data/brands.json` lists only channels found on the brand's own pages. T-Mobile's pages don't publish its texting numbers, so `check_sender` reports `official_channels_known: false` for T-Mobile until a T-Mobile page or mentor confirms them. `check_link` never visits a link (`final_redirect_domain` stays null). The demo scenario domains aren't registered, so live RDAP reports "no registration record found" for them rather than an age.
- 2026-11-07 18:58 · A10: until A1 saves `data/splits/train.jsonl`, the blocklist is built from `data/provisional/train.jsonl` (18 hand-written synthetic messages, no scenario domains). The builder refuses any file that isn't a train split and switches to A1's split automatically.

- 2026-11-07 19:16 · **Gate P1 baseline (A1):** keyword rules + TF-IDF + logistic regression, fit on train only (1,818), no tuning. Test (388 = `test_v1` 338 + hand-written 50): **macro F1 0.807, FPR 0.127** (legit messages flagged as scam), scam recall 0.882. Validation: macro F1 0.898, FPR 0.054. Macro F1 is well under 0.97, so no P1 pivot: the accuracy story is "beat the baseline per category and cut false alarms". Weakest categories on test: `bank_impersonation` 0.64, `conversation_lure` 0.70, `account_security` 0.75. Raw text (A3 redaction not built yet). Split saved in `data/generated/splits.json`; L7 and A13 must use it.

- 2026-11-07 19:07 · A5 public evaluation: `ucirvine/sms_spam` revision `cae486f927c250fe1d4a5b55f11357964ed1646c`; parquet `data/raw/public_sms/plain_text/train-00000-of-00001.parquet` = 358869 bytes (363852 including README). Verified 5574 rows: 0=ham 4827, 1=spam 747. HF card license unknown; [upstream UCI](https://archive.ics.uci.edu/dataset/228/sms+spam+collection) specifies CC BY 4.0. Every row is external evaluation ONLY, even though upstream split is named train; never train/tune/prompts/blocklists/campaign seeds. pyarrow 26.0.1 installed in project venv for aggregate verification only. Raw data and manifest are ignored.
- 2026-11-07 19:07 · A5 L7 optional base: `distilbert/distilbert-base-uncased` revision `12040accade4e8a0f71eabdb258fecc2e7e948be`, approximately 67M parameters, Apache-2.0; 268672802 bytes cached (safetensors/config/tokenizer/card/license). Small English encoder without SMS fine-tuning; add a classification head using only allowed synthetic train data. `python -m scripts.setup_huggingface` reproduces artifacts and writes local paths/checksums to ignored `data/raw/public_sms/manifest.json`.
- 2026-11-07 19:07 · A5 local fallback attempted within 45 minutes: official `nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB` revision `1db54d5b12533ff1bcaa8e42cf4c667988a1f1be`, Q4_K_M GGUF 6180446208 bytes, existing Ollama 0.32.1 isolated on port 8080. Native smoke 3/5; first two calls timed out at 30 seconds during startup. Completed calls median 14278.5ms, worst 18804ms (timeouts excluded). Not selected for demo. Server/model stopped; artifacts retained. Exact steps and results: `docs/LOCAL_NEMOTRON.md`. No system-wide installation.

- 2026-11-07 19:00 · A21 taxonomy v1 is final unless T-Mobile shares one: `bank_impersonation`, `billing_scam`, `delivery_scam`, `account_security`, `toll_government`, `prize_refund`, `job_offer`, `conversation_lure`, `legit`. The classifier, Nemotron and the UI use only these ids (`legit`, not `legitimate`).
- 2026-11-07 19:00 · A21 split protocol for A1: train + validation = `data/generated/messages.jsonl` rows with `prompt_set == "train_v1"` (2,208; split about 82/18 stratified by category, fixed seed, = 70/15 of the total). Test = `prompt_set == "test_v1"` (338) plus `data/generated/handwritten.jsonl` (50) = 388, 15%. Senders in the generated set are assigned by rule, so sender-type features mean little on it.
- 2026-11-07 19:00 · A21 caches DeepSeek calls inside `scripts/generate_dataset.py` (under `data/generated/cache/`, committed) instead of `integrations/cache.py`: L1 isn't built, and DeepSeek is offline data generation only, not a runtime call. `--offline` rebuilds the dataset with no key.

- 2026-11-07 19:07 · A4 verified `nvidia/nemotron-3.5-bolt-e4b` via GET /v1/models: native 5/5 (median step 3082ms, worst 3908ms); JSON action fallback 5/5 (1128ms, 2171ms). Use NEMOTRON_PROTOCOL=native. Initial failures were corrected by separating tool dispatch from final schema and making protocol envelopes explicit; retain one invalid-output retry. `nvidia/nemotron-3.5-embed-1b` returns 2048 dimensions. L1 remains a scaffold; live-only TODO, record/replay fail closed.

- 2026-11-07 19:29 · L3 store: SQLite runs in memory (`:memory:`) because DATA_SPEC 5 keeps message text for the session only; a restart or `/api/demo/reset` clears it. The agent writes the trail through the `on_trail` it's given (`TrailWriter`): call it with a `TrailEntry`, or `on_trail.add(kind, tool=..., why=..., finding=..., ms=...)`. Each run of a message (check, then recovery) gets a new run number and only the latest shows in the poll.
- 2026-11-07 19:15 · A3 (#4), A9 (#17) and A12 (#20) move from Claude Code to Codex (connections session), on the shared `arnav-shared` branch. Claude Code keeps A1, A13, A8, A18 and A19. A12 may use `nemotron-3.5-embed-1b` for similarity. Local Nemotron fallback scored 3/5 and is not used; replay mode is the fallback.
- 2026-11-07 18:56 · L1 cache rules: call `cache.cached_call("<service>", request, fn)` for every outside call. `request` holds everything that changes the response and nothing secret (fixtures are committed); leave timestamps out or list them in `volatile=`. Replay is strict: an unrecorded request raises `FixtureMissingError`, so record each scenario with `DEMO_MODE=record` before switching to replay.
- 2026-11-07 18:38 · L2 runtime conventions for every backend module: raise `app.errors` exceptions (`NotFoundError`, `IntegrationError(service, msg)`, `NotImplementedYetError(issue)`, ...) instead of `HTTPException`; every error response is `{"detail", "error": {code, message, details, message_id}}`. Log with `logging.getLogger(__name__)` and `extra={"fields": {...}}`; wrap per-message work in `app.logs.bind_message_id(id)`. Routes read settings through the `SettingsDep` dependency. Route mocks: `USE_MOCKS` is the default, `MOCK_ROUTES` / `LIVE_ROUTES` override per route (names in `app.config.ROUTES`).
- 2026-11-07 18:55 · A2 (Nessie client and seed, #3) moves from Claude Code to Cursor: Cursor was idle and A11 needs A2, while Claude Code's queue is long. Branch commands now use `--no-track` plus `git push -u` (AGENTS.md section 4).
- 2026-11-07 18:46 · `numpy` stays on 2.4.x while Python 3.11 is supported: 2.5.x has no 3.11 wheels. CI tests 3.11 and 3.12, so a dependency bump that drops 3.11 fails CI.
- 2026-11-07 18:46 · Per-issue branches use `git switch --no-track -c <branch> origin/main`, then `git push -u origin <branch>`. Plain `-c <branch> origin/main` tracks `origin/main`, so `git push` fails and `git pull` pulls `main` (`docs/WORKTREES.md`).
- 2026-11-07 18:20 · Arnav's Claude Code and Codex (connections) share the remote branch `arnav-shared` (AGENTS.md section 4, exception). Cursor and the Codex design session keep a branch per issue.
- 2026-11-07 18:06 · Scaffold was run by Claude Code instead of Cursor.
- 2026-11-07 18:05 · Frontend design moves from 6.1 Sol to a second Codex session running GPT 6 Astra (`agent:design`). It starts now in a design lab outside the repo (`prompts/codex-00-design-lab.md`) and ports the prototype into `frontend/` for A7 and A14 to A16.
- 2026-11-07 18:00 · Deadlines from the opening ceremony: initial Devpost draft by 11:00 PM Saturday, final Devpost by 12:00 PM Sunday, judging 1:00 to 4:00 PM Sunday.
- 2026-11-07 18:00 · T-Mobile doesn't provide a message set. We generate one with DeepSeek (A21), with a separate prompt set and hand-written messages for test, and validate on a public real SMS spam set from Hugging Face (A5). Our baseline is keyword rules plus TF-IDF and logistic regression (A1).
- 2026-11-07 18:00 · Agent model: Nemotron 3.5 Bolt E4B (`nvidia/nemotron-3.5-bolt-e4b`, confirm with `GET /v1/models`). Optional: `nemotron-3.5-embed-1b` for campaign similarity and classifier features. Local fallback: the same Bolt model from Hugging Face on Arnav's laptop.
- 2026-11-07 18:00 · DeepSeek key stands in for Gemini until Sunday morning, for dataset generation only. The Gemini tool (L4, L10) waits for the Gemini key. DeepSeek never produces public-report results, because it can't cite sources.
- 2026-11-07 · Arnav uses Claude Code (POCs, testing, data pipelines), Codex (Hugging Face and Nemotron connections), Cursor (coding, backend, infrastructure) and a second Codex session with GPT 6 Astra (frontend design). Lavanya uses Claude Code for core infrastructure plus the classifier, agent, Gemini and API work. Both Claude Code sessions use Opus 5.5.
- 2026-11-07 · Each of Arnav's agents works in its own git worktree with its own ports (POC_MVP.md section 12.2).
- 2026-11-07 · Tracks: T-Mobile, NVIDIA and Capital One, plus HackUTD Best Design and General.

---

## Blockers and open questions

- Gemini key arrives Sunday morning; L4 and L10 wait for it.
- T-Mobile's official texting short codes: not published on T-Mobile's pages (checked 2026-11-07). Ask a T-Mobile mentor, then fill `data/brands.json` (A10 follow-up).
- Taxonomy: ours (v1) is in `data/taxonomy.json` (A21). If a mentor shares T-Mobile's, map it and regenerate.
