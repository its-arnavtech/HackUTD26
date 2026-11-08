# Claude Code 02: POCs, testing and data pipelines (Arnav)

**Tool:** Claude Code, Opus 5.5 · **Folder:** `C:\HackUTD26-cc` (ports 8001 and 5174) · **Run:** after the issues exist

Paste everything below the line.

---

I'm Arnav (`its-arnavtech`). In this repo you are my Claude Code agent for **POCs, testing and data pipelines**. My other agents work in parallel in their own folders: Codex (Hugging Face and Nemotron connections), Cursor (backend engineering and infrastructure) and a second Codex session with GPT 6 Astra (frontend design). Lavanya's Claude Code builds the core infrastructure, classifier, agent and API. Don't edit their modules.

## Start of every session

1. `git fetch`. Read `AGENTS.md`, then `CHANGELOG.md`: the Status board, In progress, Decisions and Blockers.
2. Run `gh issue list --assignee its-arnavtech --label agent:claude-code --state open`.
3. If any of my Claude Code issues is `in progress` in the CHANGELOG or has a checkpoint comment, resume it first (AGENTS.md section 5, Resume). Otherwise take the next one in the work order below whose dependencies are done.
4. Tell me in three lines which issue you're taking and why, then start.

## Work order

1. **A21** Synthetic message dataset generator. T-Mobile gives us no data, so this blocks everything downstream. Use DeepSeek (`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` in `.env`; its API is OpenAI-compatible). Aim for about 2,000 to 3,000 messages across the categories in `data/taxonomy.json`, with at least a third legitimate, including hard look-alikes (real-style bank alerts, carrier bill notices, one-time codes, delivery updates). Generate test from a separate prompt set and personas, ask me for about 50 hand-written test messages (or draft them for my approval), dedupe, and write the datasheet. Cache generation calls so reruns are free.
2. **A1** Split and baseline (gate P1). Write the baseline's macro F1 and FPR into CHANGELOG Decisions as soon as you have them; the P1 pivot depends on it.
3. **A3** Redaction module (gate P5).
4. ~~A2~~ moved to Cursor on 2026-11-07. Skip it.
5. **A9** Feature extraction. Lavanya's classifier (L7) waits on it.
6. **A13** Evaluation harness. L7 waits on it too. Score both test sets: the synthetic test split and the public real SMS set from Codex's A5.
7. **A8** POC gate report, once A1, A2, A3, A4 (Codex) and L4 (Lavanya) are done. If A4 or L4 isn't done, report what's known and mark the rest pending.
8. **A12** Campaign store, seeding and `match_campaign`.
9. **A18** End-to-end scenario tests, after gate G1.
10. **A19** Replay fixtures, after gate G2.

Remind me at 10:15 PM about **A22**, the initial Devpost draft due at 11:00 PM.

## Branch

You share the remote branch `arnav-shared` with my Codex connections session. Follow AGENTS.md section 4, "Exception: Arnav's Claude Code and Codex (connections) share one branch", exactly: `git pull --rebase` before every commit, stage only your own files, merge-commit PRs.

## How to work

- Follow AGENTS.md section 4 for each issue, and section 5 for claim, checkpoint and finish. **Checkpoint after every sub-task and whenever this conversation is getting long**, so Cursor or Codex can take over if I run out of tokens here.
- Data pipelines must be reproducible: fixed seeds, saved splits, and a single command to rerun each. Never use the test split for anything but final scoring.
- Tests are part of every issue, not an extra. Keep them fast and runnable offline in replay mode.
- After the PR, tell me what changed and how to check it in two or three lines, then wait for me to say "next".
- If something blocks you for more than about 20 minutes, stop, write it under Blockers in the CHANGELOG, and tell me the fallback from POC_MVP.md section 11.
