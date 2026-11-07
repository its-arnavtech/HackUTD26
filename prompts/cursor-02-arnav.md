# Cursor 02: Coding, backend engineering and infrastructure (Arnav)

**Tool:** Cursor (Agent mode) · **Folder:** `C:\HackUTD26` (ports 8000 and 5173) · **Run:** after the issues exist

Paste everything below the line.

---

I'm Arnav. In this repo, Cursor is my agent for **coding, backend engineering and infrastructure**. My other agents work in parallel in their own folders: Claude Code (POCs, testing, data pipelines), Codex (Hugging Face and Nemotron connections) and 6.1 Sol (frontend design). Lavanya's Claude Code builds the core runtime, store, cache, tool registry, agent and API. Don't edit their modules; code against their interfaces.

## Start of every session

1. `git fetch`. Read `AGENTS.md` (the `.cursor/rules` file points to it) and `CHANGELOG.md`.
2. `gh issue list --label agent:cursor --state open`. Resume anything with a checkpoint comment first.
3. Tell me in three lines which issue you're taking and why, then start.

## Work order

1. **A6** Dev infrastructure: GitHub Actions CI (`pytest` and `npm run build` on every PR, Python 3.11 and Node LTS, no secrets needed because tests run in replay mode), `scripts/dev.ps1` (starts backend and frontend on `API_PORT` and `WEB_PORT` from `.env`), and `docs/WORKTREES.md` (the steps from POC_MVP.md 12.2, verified on this machine).
2. **A10** `check_link` and `check_sender`. Plain functions first. Register them with Lavanya's tool registry (L5) once it merges. RDAP goes through her cache (L1) once it merges. Build the blocklist from the train split only (A1's saved split).
3. **A11** Nessie tools, once A2 (Claude Code) has merged the Nessie client. Return summaries with references exactly as DATA_SPEC 3.2 says. Never return names, account numbers or raw records to the agent.
4. **G1 support:** when L8 merges, help wire scenario 1 through `python -m scripts.run_scenario 1`. Fix integration bugs in my modules; report bugs in Lavanya's modules on her issue instead of editing them.
5. **A17** Frontend on the live API, once 6.1 Sol's screens (A14 to A16) and L9 have merged: replace mocks with real calls, add loading, error and retry states, stop polling at `done`, no console errors.
6. **G2 support** and performance or reliability fixes in my modules.

If a dependency isn't merged yet, take the next issue that isn't blocked and say so.

## How to work

- Follow AGENTS.md section 4 for each issue, and section 5 for claim, checkpoint and finish. Checkpoint after every sub-task, so another agent can continue if Cursor's context or usage runs out.
- Code to the contracts in `contracts.py`. If you need to change one, open a separate `[contracts]` PR and tell me.
- Keep functions small and typed, with tests next to each module.
- After each PR, tell me what changed and how to check it in two or three lines, then wait for "next".
