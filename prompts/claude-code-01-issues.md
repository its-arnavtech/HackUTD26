# Claude Code 01: Create every GitHub issue (Arnav)

**Tool:** Claude Code, Opus 5.5 · **Folder:** `C:\HackUTD26-cc` · **Run:** after `cursor-01-scaffold.md` has pushed

Paste everything below the line.

---

Create the GitHub issues for SentinelAI in `its-arnavtech/HackUTD26`. Pull `main` first, then read `AGENTS.md`, `CHANGELOG.md` and `docs/POC_MVP.md`. Section 13 of `POC_MVP.md` is the exact issue list: 22 Arnav issues, 12 Lavanya issues and 3 shared gates (37 in all). Don't add, drop or merge issues.

Use the `gh` CLI. Run `gh auth status` first. If it isn't authenticated, stop and tell me to run `gh auth login`.

## 1. Labels

Create these labels, or update them if they exist (`gh label create <name> --color <hex> --force`):

| Label | Color | | Label | Color |
| --- | --- | --- | --- | --- |
| `owner:arnav` | `1d76db` | | `agent:claude-code` | `d97757` |
| `owner:lavanya` | `d93f0b` | | `agent:codex` | `10a37f` |
| `owner:both` | `5319e7` | | `agent:cursor` | `000000` |
| `area:ml` | `0e8a16` | | `agent:design` | `f9a8d4` |
| `area:agent` | `006b75` | | `agent:any` | `cccccc` |
| `area:backend` | `0052cc` | | `track:tmobile` | `e20074` |
| `area:infra` | `5a5a5a` | | `track:nvidia` | `76b900` |
| `area:data` | `c2e0c6` | | `track:capitalone` | `004879` |
| `area:integration` | `c5def5` | | `priority:p0` | `b60205` |
| `area:frontend` | `fbca04` | | `priority:p1` | `d4c5f9` |
| `area:testing` | `bfdadc` | | `area:demo` | `bfd4f2` |

## 2. Milestones

Create `POC`, `MVP` and `Demo` with `gh api repos/its-arnavtech/HackUTD26/milestones -f title=... -f description=...`, skipping any that exist. Descriptions: POC = "Gates P1 to P5 (POC_MVP.md section 3)", MVP = "All three scenarios end to end (G1, G2)", Demo = "Fixtures, pitch, backup video, rehearsal".

## 3. Issues

Create every issue in section 13 in table order. Before each one, check whether an issue whose title starts with the same `[ID]` already exists and skip it if so, so this prompt is safe to rerun.

- **Title:** `[ID] Title`, for example `[A3] Redaction module`.
- **Milestone:** the table it sits in.
- **Labels:**
  - one `owner:` label;
  - one `agent:` label from the Agent column (`claude-code`, `codex`, `cursor`, `design`, `any`); A21 gets `area:data` and `area:ml`, A22 gets `area:demo`;
  - one or two `area:` labels;
  - every `track:` label it serves;
  - `priority:p0` for every POC issue (including A21 and A22) plus L5, L8, L9, A9, A11, A13, A14, A17, G1 and G2; `priority:p1` for the rest.
- **Assignee:** every `A*` and `G*` issue goes to `its-arnavtech`. **Every `L*` issue stays unassigned.**
- **Body:** this template, filled in only from the docs:

```markdown
## Goal
<one or two sentences>

## Owner and agent
<Arnav | Lavanya | Both> · <Claude Code | Codex | Cursor | 6.1 Sol | any>

## Read first
- AGENTS.md (workflow and the CHANGELOG handoff protocol)
- docs/POC_MVP.md section <n>
- docs/DATA_SPEC.md section <n>, if relevant

## Tasks
- [ ] Claim: comment on this issue and update CHANGELOG.md (AGENTS.md section 5)
- [ ] <concrete step>
- [ ] <concrete step>
- [ ] Tests
- [ ] Finish: CHANGELOG.md Done log line and Status board set to done

## Acceptance criteria
- [ ] <from the table, split into checkable items>

## Files
<paths from POC_MVP.md section 6 this issue touches>

## Depends on
<IDs; replaced with issue numbers in step 4>

## Tracks
<T-Mobile / NVIDIA / Capital One>

## Handoff
If an agent runs out of tokens, the latest checkpoint comment on this issue says where to resume.
```

## 4. Link the dependencies

When every issue exists, map each ID to its issue number. Edit every body so `Depends on` reads like `#4 (A3), #19 (L8)`, or `Scaffold (done)`, or `None`.

## 5. Tracking issue

Create `[BOARD] SentinelAI build tracker`, labeled `owner:both` and `agent:any`, assigned to `its-arnavtech`, and pin it with `gh issue pin`. Body: one section per milestone, and inside each a list per person and tool (Arnav: Claude Code, Codex, Cursor, 6.1 Sol; Lavanya: Claude Code; Both), each item a checkbox like `- [ ] #4 [A3] Redaction module`. End with: "Live status and handoffs: CHANGELOG.md. Hard rule: if G1 isn't done by hour 14, follow the cut order in POC_MVP.md section 11."

## 6. Update CHANGELOG.md

In the Status board, put each issue's number in the Branch / PR column as `#<n>`. Add a Done log line for issue creation. Commit `chore(changelog): add issue numbers` straight to `main` (docs-only change) and push.

## 7. Report back

1. A table of every issue: number, ID, title, owner, agent, milestone, assignee.
2. The link to the tracking issue.
3. Remind me that Lavanya must be a collaborator on the repo before she can push or claim issues, and that her prompt is `prompts/lavanya-claude-code.md`.
4. Remind me which prompt goes to which tool next (see `prompts/README.md`).
