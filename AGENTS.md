# SentinelAI: rules for every coding agent

This file is read by Claude Code (through `CLAUDE.md`), Codex and Cursor. Follow it whichever tool you are.

SentinelAI is a scam protection agent built at HackUTD 2026 by Arnav (`its-arnavtech`) and Lavanya, entered in the T-Mobile, NVIDIA (Nemotron) and Capital One (Nessie) tracks.

## 1. Read first, every session

1. `CHANGELOG.md`: what's done, what's in progress, what's left, and recent decisions.
2. `docs/POC_MVP.md`: scope, architecture, API, screens and the issue list (section 13). It is the source of truth.
3. `docs/DATA_SPEC.md`: every data contract. `backend/app/contracts.py` and `frontend/src/types.ts` must match it.
4. Your issue: `gh issue view <n> --comments`. The latest checkpoint comment tells you where the last agent stopped.

## 2. Who does what

| Person | Tool | Issues | Find them with |
| --- | --- | --- | --- |
| Arnav | Claude Code | POCs, testing, data pipelines | `gh issue list --assignee its-arnavtech --label agent:claude-code` |
| Arnav | Codex | Hugging Face and Nemotron connections | `gh issue list --label agent:codex` |
| Arnav | Cursor | Coding, backend engineering, infrastructure | `gh issue list --label agent:cursor` |
| Arnav | Codex design (GPT 6 Astra) | Frontend design | `gh issue list --label agent:design` |
| Lavanya | Claude Code | Core infrastructure, classifier, agent, Gemini, API | `gh issue list --label owner:lavanya` |
| Both | any | Gates G1 to G3 | `gh issue list --label owner:both` |

Work only on issues for your person and tool unless the human tells you otherwise. Don't edit modules another person owns (listed in each issue's Files section) without telling your human first.

## 3. One agent per folder

Each agent works in its own folder (a git worktree for Arnav's tools, section 12.2 of the plan). Never run two agents in the same folder. Use the `API_PORT` and `WEB_PORT` in your folder's `.env`.

## 4. Workflow for each issue

1. `git fetch`, then `git switch -c <id>-<short-name> origin/main` (for example `a3-redaction`). If the branch already exists because you are resuming, `git switch <branch>` and `git pull`.
2. **Claim** (section 5).
3. Restate the acceptance criteria in two or three lines, then implement.
4. Run `pytest` from `backend/` (and `npm run build` in `frontend/` for frontend work). Add tests for what you built.
5. Tick the issue's checkboxes, **finish** the CHANGELOG entry (section 5), and open a PR that says `Closes #<n>`, with a short summary and how you tested it.
6. Tell your human what changed and how to check it, then wait before starting another issue.

`backend/app/contracts.py` and `frontend/src/types.ts` are shared. Change them only in a separate PR titled `[contracts] ...`, and tell your human so the other person can review it.

Don't push code directly to `main`. Changes that only touch `docs/`, `prompts/` or `CHANGELOG.md` may go straight to `main`.

## 5. CHANGELOG and handoff protocol

Any agent can run out of tokens mid-task. These steps let any other agent continue exactly where you stopped.

**Claim**, when you start an issue:
- Post an issue comment: `Claimed by <tool> (<model>) in <folder>, branch <branch>.`
- In `CHANGELOG.md` on your branch, set your issue's row in the Status board to `in progress` with the branch name, and add a block under In progress using the template in that file.
- Commit `chore(changelog): claim <ID>` and push the branch.

**Checkpoint** after each sub-task, at least every 30 minutes, and immediately when your context is getting long or you are about to stop:
- Update your In progress block: done so far, the exact next step, files touched, commands to run, gotchas.
- Commit any work in progress plus the block as `chore(changelog): checkpoint <ID>` and push the branch.
- Post the same block as an issue comment, so it's visible before the branch merges.

**Finish**, in the PR for the issue:
- Delete your In progress block. Add one line at the top of the Done log: date and time, ID, tool, PR number, one-line summary, follow-ups.
- Set the Status board row to `done`.
- Add any decision other agents need to know to Decisions.

**Resume** someone else's work:
- Read the latest checkpoint comment on the issue, `git fetch`, `git switch <their branch>`, `git pull`.
- Add `Resumed by <tool> from <previous tool>` to the In progress block and continue from "Next step".

**Conflicts in CHANGELOG.md:** keep every entry from both sides, and for Status board rows keep the most advanced status. Never delete another agent's block.

Times are Central time (America/Chicago), `YYYY-MM-DD HH:MM`.

## 6. Conventions

- Both people develop on Windows. Give PowerShell commands and use `python -m ...` for scripts.
- Backend: Python 3.11+, FastAPI, Pydantic v2, pytest. Frontend: Vite, React, TypeScript, Tailwind.
- Every external call (Nemotron, Gemini, Nessie, RDAP, Hugging Face) goes through `backend/app/integrations/cache.py`, which respects `DEMO_MODE` (`live`, `record`, `replay`).
- Secrets live in `.env`, which is never committed. Never print a key. Add new variables to `.env.example`.
- No new infrastructure: no Docker, Postgres, vector databases, graph databases or WebSockets. SQLite and polling only.
- Synthetic data only. Never put a real person's data in fixtures or tests.

## 7. Rules that must never break

- Redaction runs before the classifier, Nemotron, or any outside service sees a message.
- Nemotron receives only the payloads in `DATA_SPEC.md` section 3. Gemini receives only section 4.1.
- The test split is never used for training, tuning, blocklists, campaign seeds or prompts.
- Every protective action waits for a customer tap. The agent never acts on money.
- The UI never shows a phone number or link that came from search results or model output.
- UI wording follows `POC_MVP.md` section 4.4: say what was checked, never "your account is fine".
