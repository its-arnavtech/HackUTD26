# CHANGELOG and handoff log

This file is how any agent (Claude Code, Codex, Cursor, 6.1 Sol) or person sees what's done, what's in progress, and what's left, and picks up where another agent stopped. The protocol is in `AGENTS.md` section 5. Short version:

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
| A1 | Dataset loader, stratified split and baseline metrics | Arnav | Claude Code | POC | scaffold | todo | |
| A2 | Nessie client and idempotent seed script | Arnav | Claude Code | POC | scaffold | todo | |
| A3 | Redaction module | Arnav | Claude Code | POC | scaffold | todo | |
| A4 | Nemotron connection and tool-calling smoke test | Arnav | Codex | POC | scaffold | todo | |
| A5 | Hugging Face connection | Arnav | Codex | POC | scaffold | todo | |
| A6 | Dev infrastructure: CI, dev scripts, worktrees | Arnav | Cursor | POC | scaffold | todo | |
| A7 | Phone shell and inbox on the mock API | Arnav | 6.1 Sol | POC | scaffold | todo | |
| L1 | Record and replay cache | Lavanya | Claude Code | POC | scaffold | todo | |
| L2 | Core runtime: app factory, settings, logging, errors | Lavanya | Claude Code | POC | scaffold | todo | |
| L3 | State store and background job runner | Lavanya | Claude Code | POC | L2 | todo | |
| L4 | Gemini grounded search smoke test | Lavanya | Claude Code | POC | scaffold | todo | |
| A8 | POC gate report | Arnav | Claude Code | POC | A1, A2, A3, A4, L4 | todo | |
| L5 | Tool registry and runtime | Lavanya | Claude Code | MVP | L2 | todo | |
| L6 | Privacy audit log and `/api/privacy` | Lavanya | Claude Code | MVP | L3, L5 | todo | |
| A9 | Feature extraction | Arnav | Claude Code | MVP | A3 | todo | |
| A10 | `check_link` and `check_sender` tools | Arnav | Cursor | MVP | L1 | todo | |
| A11 | Nessie tools | Arnav | Cursor | MVP | A2 | todo | |
| A12 | Campaign store, seeding and `match_campaign` | Arnav | Claude Code | MVP | A1, A3 | todo | |
| A13 | Evaluation harness | Arnav | Claude Code | MVP | A1 | todo | |
| L7 | Improved classifier | Lavanya | Claude Code | MVP | A1, A9, A13 | todo | |
| L8 | Agent loop with plan, re-plan and guardrails | Lavanya | Claude Code | MVP | A4, L5 | todo | |
| L9 | API endpoints and pipeline orchestration | Lavanya | Claude Code | MVP | L3, L8 | todo | |
| G1 | Gate: scenario 1 end to end in the CLI | Both | any | MVP | A3, A9, A10, A11, L8 | todo | |
| L10 | `public_scam_reports` tool | Lavanya | Claude Code | MVP | L4, L5 | todo | |
| L11 | Recovery mode re-plan | Lavanya | Claude Code | MVP | L8, A11 | todo | |
| A14 | Result card, "How we checked" and privacy panel | Arnav | 6.1 Sol | MVP | A7 | todo | |
| A15 | Recovery UI | Arnav | 6.1 Sol | MVP | A14 | todo | |
| A16 | Consent screen, campaign view and accuracy page | Arnav | 6.1 Sol | MVP | A7 | todo | |
| A17 | Frontend on the live API | Arnav | Cursor | MVP | A14, A15, A16, L9 | todo | |
| A18 | End-to-end scenario tests | Arnav | Claude Code | MVP | G1 | todo | |
| G2 | Gate: all three scenarios end to end in the app | Both | any | MVP | A17, A18, L10, L11 | todo | |
| A19 | Replay fixtures and backup video | Arnav | Claude Code | Demo | G2 | todo | |
| A20 | Capital One and Best Design pitch | Arnav | any | Demo | G2 | todo | |
| L12 | NVIDIA and T-Mobile pitch, Devpost | Lavanya | Claude Code | Demo | G2 | todo | |
| G3 | Rehearse the 3-minute demo three times | Both | any | Demo | A19, A20, L12 | todo | |

---

## In progress

<!-- One block per active issue. Copy the template, keep it current at every checkpoint. -->

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

_None yet._

---

## Done log

Newest first. One line per finished issue or setup step: `YYYY-MM-DD HH:MM · ID · tool · PR · summary · follow-ups`.

- 2026-11-07 17:50 · setup · Claude (chat) · direct to main · Re-split work across Arnav's four agents and Lavanya's Claude Code; added AGENTS.md, CHANGELOG.md, Cursor rule and per-tool prompts · next: Cursor runs `prompts/cursor-01-scaffold.md`
- 2026-11-07 17:30 · setup · Claude (chat) · direct to main (2d4f228) · Added POC/MVP plan, data spec and first prompts

---

## Decisions

- 2026-11-07 · Arnav uses Claude Code (POCs, testing, data pipelines), Codex (Hugging Face and Nemotron connections), Cursor (coding, backend, infrastructure) and 6.1 Sol (frontend design). Lavanya uses Claude Code for core infrastructure plus the classifier, agent, Gemini and API work. Both Claude Code sessions use Opus 5.5.
- 2026-11-07 · Each of Arnav's agents works in its own git worktree with its own ports (POC_MVP.md section 12.2).
- 2026-11-07 · Tracks: T-Mobile, NVIDIA and Capital One, plus HackUTD Best Design and General.

---

## Blockers and open questions

- Exact Nemotron model ID: take it from NVIDIA's HackUTD guide (A4).
- Official short codes and sender IDs for the demo brands: fill `data/brands.json` from the brands' own pages (A10).
- T-Mobile dataset field names and taxonomy labels: confirm on load (A1).
