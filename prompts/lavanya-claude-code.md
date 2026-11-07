# Lavanya: Claude Code starter prompt

**Tool:** Claude Code, Opus 5.5 (select it with `/model` before pasting) · **Folder:** your own clone of the repo · **Run:** once Arnav says the scaffold and issues are up

Paste everything below the line.

---

I'm Lavanya, building SentinelAI with Arnav at HackUTD 2026 for the T-Mobile, NVIDIA (Nemotron) and Capital One (Nessie) tracks. You're my Claude Code agent. My half is the **core infrastructure** (runtime, state store, replay cache, tool registry, privacy log, API and pipeline) plus the **intelligence** (Gemini, classifier, Nemotron agent loop, recovery re-plan). Arnav runs four agents of his own in parallel: Claude Code, Codex, Cursor and a design model. They build against my interfaces, so my core pieces unblock them.

## 1. Setup (PowerShell)

1. If the repo isn't cloned: `git clone https://github.com/its-arnavtech/HackUTD26.git`, then `cd HackUTD26`. Otherwise `git pull` on `main`.
2. Read `AGENTS.md` (the rules for every agent, including the CHANGELOG handoff protocol in section 5), `CHANGELOG.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md` completely.
3. In `backend/`: create and activate a venv, `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env` at the repo root. Ask me to paste my keys into it myself: `NVIDIA_API_KEY` and `NEMOTRON_MODEL` (Nemotron 3.5 Bolt E4B; Arnav's Codex records the exact ID in CHANGELOG Decisions) tonight, and `GEMINI_API_KEY` on Sunday morning. Never print or commit keys.
5. T-Mobile doesn't provide data. Arnav's Claude Code generates our dataset (A21) and splits it (A1), so I only need it when I train the classifier (L7).
6. Run `pytest` from `backend/` to confirm the scaffold works. Fix setup problems before writing features.

## 2. Claim my issues

1. `gh auth status`. If I'm not logged in, tell me to run `gh auth login`.
2. `gh issue list --label owner:lavanya --state open`.
3. Assign me to each: `gh issue edit <n> --add-assignee @me`.
4. Show me the list in the work order below, with issue numbers.

## 3. Work order

| Order | ID | Issue | Why now |
| --- | --- | --- | --- |
| 1 | L2 | Core runtime: app factory, settings, logging, errors | Everything else runs on it |
| 2 | L1 | Record and replay cache | Arnav's Nessie, Nemotron and RDAP clients wrap it |
| 3 | L3 | State store and background job runner | The API and agent trail need it |
| 4 | L4 | Gemini grounded search smoke test | Gate P3. Needs the Gemini key, so do it first thing Sunday morning and move on to L5 tonight. |
| 5 | L5 | Tool registry and runtime | Arnav's tools register with it |
| 6 | L8 | Agent loop with plan, re-plan and guardrails | Needs A4 (Arnav's Nemotron client) and L5 |
| 7 | L6 | Privacy audit log and `/api/privacy` | Feeds the privacy panel |
| 8 | L9 | API endpoints and pipeline orchestration | Gate G1, then the live UI |
| 9 | L7 | Improved classifier | Needs A1, A9 and A13 from Arnav |
| 10 | L10 | `public_scam_reports` Gemini tool | Scenario 3 |
| 11 | L11 | Recovery mode re-plan | Scenario 2 |
| 12 | L12 | NVIDIA and T-Mobile pitch, Devpost | After G2 |

If an issue's dependency isn't merged, take the next unblocked one and say so.

**Interfaces first:** for L1, L2, L3 and L5, open a small first PR with just the public interface (signatures, contract models, docstrings, and a fake implementation if needed), get it merged, then build the real implementation. Arnav's agents can code against it right away.

## 4. For each issue

1. **Claim** it (AGENTS.md section 5): issue comment, Status board row `in progress`, In progress block in `CHANGELOG.md`, push the branch.
2. `git fetch`, then `git switch -c <id>-<short-name> origin/main` (for example `l2-core-runtime`).
3. Read the issue and every doc section it names. Restate the acceptance criteria in two or three lines.
4. Implement, with tests. Run `pytest`.
5. **Checkpoint** after each sub-task, every 30 minutes, and right away if this conversation is getting long: update the In progress block, commit, push, and post the block as an issue comment. If I run out of tokens, the next session resumes from it.
6. **Finish:** tick the checkboxes, move the CHANGELOG block to the Done log, set the row to `done`, open a PR with `Closes #<n>`.
7. Tell me in two or three lines what changed and how to check it, then wait for me to say "next".

Deadlines: initial Devpost draft by 11:00 PM Saturday (Arnav submits it), final Devpost by 12:00 PM Sunday, judging 1:00 to 4:00 PM.

## 5. Coordination

- Arnav's modules: Nessie client and tools, redaction, features, link, sender and campaign tools, dataset and evaluation scripts, the Nemotron and Hugging Face clients, CI, and the whole frontend. Don't edit them. If one has a bug that blocks me, comment on its issue and tell me.
- Shared contracts (`contracts.py`, `types.ts`): change them only in a separate PR titled `[contracts] ...`, and tell me so Arnav can review it.
- G1 (scenario 1 end to end) is a joint gate. When L8 and L9 are close, tell me so I can sync with Arnav.
- Post gate P3 results (Gemini returns cited URLs, or not) on the L4 issue and in CHANGELOG Decisions as soon as they're known.

## 6. Rules that must never break

Follow AGENTS.md section 7: redaction first; Nemotron and Gemini receive only what DATA_SPEC allows; the test split is never used for training or tuning; every protective action waits for a customer tap; no phone numbers or links from search or the model in the UI; honest wording ("we found no unusual activity", never "your account is fine").

Start with setup step 1.
