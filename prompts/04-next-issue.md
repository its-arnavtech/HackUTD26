# Prompt 04: Pick up the next issue (either person, any time)

Use this in a fresh Claude Code session, or after a long break, to get back on track. Replace `<name>` with `arnav` or `lavanya`.

---

I'm <name> on the SentinelAI team. Pull `main`, read `CLAUDE.md`, then run `gh issue list --label owner:<name> --state open` and `gh issue view` on the pinned `[BOARD]` issue.

Tell me in five lines or fewer:
1. Which of my issues are done, open, and blocked (and on what)
2. Whether gate G1 or G2 is waiting on me
3. Which issue I should do next, by the work order in my starter prompt

Then start that issue using the per-issue loop in `CLAUDE.md`: branch, implement, test, tick the checkboxes, PR with `Closes #<n>`. Stop after the PR and wait for me.
