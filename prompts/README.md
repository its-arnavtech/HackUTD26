# Prompts: which one goes to which tool

Every agent follows `AGENTS.md` (Claude Code loads it through `CLAUDE.md`, Codex reads it directly, and Cursor reads it through `.cursor/rules/sentinel.mdc`). Progress and handoffs live in `CHANGELOG.md`.

## Order

| Step | Prompt | Tool | Person | Folder | Runs when |
| --- | --- | --- | --- | --- | --- |
| 1 | [cursor-01-scaffold.md](cursor-01-scaffold.md) | Cursor | Arnav | `C:\HackUTD26` | First |
| 2 | [claude-code-01-issues.md](claude-code-01-issues.md) | Claude Code (Opus 5.5) | Arnav | `C:\HackUTD26-cc` | After step 1 pushes |
| 3 | [lavanya-claude-code.md](lavanya-claude-code.md) | Claude Code (Opus 5.5) | Lavanya | Her clone | After step 2. Send her this file. |
| 4a | [claude-code-02-arnav.md](claude-code-02-arnav.md) | Claude Code (Opus 5.5) | Arnav | `C:\HackUTD26-cc` | After step 2, in parallel with 4b to 4d |
| 4b | [codex-01-connections.md](codex-01-connections.md) | Codex | Arnav | `C:\HackUTD26-codex` | After step 2 |
| 4c | [cursor-02-arnav.md](cursor-02-arnav.md) | Cursor | Arnav | `C:\HackUTD26` | After step 2 |
| 4d | [design-01-frontend.md](design-01-frontend.md) | 6.1 Sol | Arnav | `C:\HackUTD26-design` | After step 2 |
| Any time | [resume-any-agent.md](resume-any-agent.md) | Any | Either | The stopped agent's folder, or a free one | An agent ran out of tokens, or you switch tools |

## Before step 2

- Add Lavanya as a collaborator on the GitHub repo (Settings, then Collaborators).
- Make sure `gh` is installed and `gh auth login` is done on your laptop.

## Short version to paste

Each agent can read its prompt from the repo:

```
Read prompts/<file>.md and follow it exactly.
```
