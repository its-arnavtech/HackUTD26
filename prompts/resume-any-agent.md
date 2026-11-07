# Resume: pick up where another agent stopped (any tool)

Use this when an agent runs out of tokens or usage, or when you switch tools mid-issue (for example Claude Code to Cursor). It works in Claude Code, Codex, Cursor or Codex design (GPT 6 Astra). Fill in the two blanks.

---

I'm <Arnav | Lavanya>. Another agent was working on issue <ID or #number> and stopped. You're taking over.

1. `git fetch`. Read `AGENTS.md` (especially section 5, the handoff protocol) and `CHANGELOG.md`.
2. Find the work: the issue's latest checkpoint comment (`gh issue view <n> --comments`), its In progress block (in `CHANGELOG.md` on its branch: `git show origin/<branch>:CHANGELOG.md`), and the branch's recent commits (`git log origin/<branch> -10 --oneline`).
3. `git switch <branch>` and `git pull`. Run the tests named in the block to confirm the state matches what it says.
4. In three or four lines, tell me what's done, what the exact next step is, and anything that doesn't match the notes.
5. Add `Resumed by <your tool> from <previous tool>` to the In progress block, commit and push, and post a short issue comment saying you've taken over.
6. Continue from "Next step" with the normal workflow: checkpoint after each sub-task, then finish with the CHANGELOG update and a PR.

If you're not sure which issue stopped, list every issue that is `in progress` in the CHANGELOG Status board or has a claim or checkpoint comment newer than its last PR, and ask me which to take.
