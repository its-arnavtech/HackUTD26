# Prompt 03: Arnav starts on his issues

Run this after prompt 02. Paste everything below the line into Claude Code at the repo root.

---

I'm Arnav (`its-arnavtech`). Help me build my half of SentinelAI: the Nessie integration, redaction, the replay cache, the link, sender, campaign and Nessie tools, and every phone UI screen. Lavanya builds the classifier, the Nemotron agent, the Gemini tool and the API; don't edit her modules.

## Setup

1. Pull `main`. Read `CLAUDE.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md`.
2. Check that the backend venv exists and `pytest` passes from `backend/`, and that `npm run dev` works in `frontend/`. Fix setup problems before writing features.
3. Check that `.env` exists. I need `NESSIE_API_KEY` set. Ask me to paste keys into `.env` myself; never print or commit them.
4. Run `gh issue list --assignee @me --state open` and show me my issues in work order.

## Work order

A1, A2, A3, A4 (POC), then A5 and A7 (needed for gate G1 with Lavanya), then A8, A6, A9, A10, then A11. G1, G2 and G3 are joint gates: check them when their dependencies close.

Start with A1. Nessie is the riskiest external dependency, so confirm its real field names on the first call and record any difference from `DATA_SPEC.md` section 6 in the PR.

## For each issue

1. Pull `main` and create branch `<id>-<short-name>`, for example `a1-nessie-seed`.
2. Read the issue and every doc section it names. Restate the acceptance criteria in two or three lines before coding.
3. Implement it. Route every external call through `integrations/cache.py` once A3 exists.
4. Write tests and run `pytest` (and `npm run build` for frontend work).
5. Tick the issue's checkboxes with `gh issue edit`, open a PR that says `Closes #<n>`, and tell me what changed and how to check it in two or three lines.
6. Stop and wait for me to say "next" before starting the next issue.

## Rules

- If a change needs `contracts.py` or `types.ts`, make it a separate PR titled `[contracts] ...` and tell me, so Lavanya can review it.
- UI wording follows `POC_MVP.md` section 4.4. Screens follow section 8.
- If something blocks an issue for more than about 20 minutes, stop and tell me, with the fallback from section 11 that applies.
