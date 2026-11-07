# Prompt 02: Create the GitHub issues and Lavanya's starter prompt (Arnav runs this second)

Run this after prompt 01's scaffold is pushed. Paste everything below the line into Claude Code at the repo root.

---

Create the GitHub issues for SentinelAI in `its-arnavtech/HackUTD26`, then write a starter prompt for my teammate Lavanya. Read `CLAUDE.md` and `docs/POC_MVP.md` first. Section 12 of `POC_MVP.md` is the exact issue list; don't add, drop or merge issues.

Use the `gh` CLI. Run `gh auth status` first. If it isn't authenticated, stop and tell me to run `gh auth login`. If you have GitHub tools instead of `gh`, use those.

## 1. Labels

Create these labels if they don't already exist (`gh label create ... --force` is fine):

| Label | Color |
| --- | --- |
| `owner:arnav` | `1d76db` |
| `owner:lavanya` | `d93f0b` |
| `owner:both` | `5319e7` |
| `area:ml` | `0e8a16` |
| `area:agent` | `006b75` |
| `area:backend` | `0052cc` |
| `area:integration` | `c5def5` |
| `area:frontend` | `fbca04` |
| `area:demo` | `bfd4f2` |
| `track:tmobile` | `e99695` |
| `track:nvidia` | `76b900` |
| `track:capitalone` | `004879` |
| `priority:p0` | `b60205` |
| `priority:p1` | `d4c5f9` |

## 2. Milestones

Create `POC`, `MVP` and `Demo` with `gh api repos/its-arnavtech/HackUTD26/milestones -f title=...`, skipping any that already exist. Descriptions: POC = "Gates P1 to P5 from POC_MVP.md section 3", MVP = "All three scenarios end to end (G1, G2)", Demo = "Pitch, fixtures, backup video, rehearsal".

## 3. Issues

Create every issue in section 12, in table order (POC, then MVP, then Demo). Before creating each one, check whether an issue whose title starts with the same `[ID]` already exists; if so, skip it. That makes this prompt safe to rerun.

- **Title:** `[ID] Title`, for example `[A2] Redaction module`.
- **Milestone:** the table it sits in.
- **Labels:** one owner label; one or two `area:` labels; every `track:` label it serves; `priority:p0` for everything in POC, G1, L6, A7, L8, A8, A9 and G2, and `priority:p1` for the rest.
- **Assignee:** Arnav's issues (`A*`) and shared gates (`G*`) go to `its-arnavtech`. **Lavanya's issues (`L*`) stay unassigned.**
- **Body:** use this template, filled in from the doc. Don't invent requirements beyond the doc.

```markdown
## Goal
<one or two sentences>

## Owner
<Arnav | Lavanya | Both>

## Read first
- docs/POC_MVP.md section <n>
- docs/DATA_SPEC.md section <n> (if relevant)

## Tasks
- [ ] <concrete step>
- [ ] <concrete step>
- [ ] Tests

## Acceptance criteria
- [ ] <from the table, split into checkable items>

## Files
<paths from POC_MVP.md section 6 this issue touches>

## Depends on
<IDs; replaced with issue numbers in step 4>

## Tracks
<T-Mobile / NVIDIA / Capital One>
```

## 4. Link the dependencies

When all issues exist, build a map from ID to issue number. Edit every body so `Depends on` reads like `#3 (A2), #12 (L6)`, or `None`.

## 5. Tracking issue

Create `[BOARD] SentinelAI build tracker`, labeled `owner:both`, assigned to `its-arnavtech`, and pin it with `gh issue pin`. Its body has one section per milestone, then one sub-list per owner (Arnav, Lavanya, Both), each item a checkbox like `- [ ] #3 [A2] Redaction module`. End with the hard rule from section 10: if G1 isn't done by hour 14, follow the cut order in section 11.

## 6. Lavanya's starter prompt

Write `prompts/lavanya-start.md`. It's a prompt Lavanya will paste into her own Claude Code session, so it must stand alone and use the **real issue numbers** you just created. Include:

1. **Who she is and the goal:** she's Lavanya, building the intelligence half of SentinelAI (classifier, Nemotron agent, Gemini tool, API) for the T-Mobile, NVIDIA and Capital One tracks at HackUTD 2026.
2. **Setup** (PowerShell): clone `https://github.com/its-arnavtech/HackUTD26` if needed, pull `main`, read `CLAUDE.md`, `docs/POC_MVP.md` and `docs/DATA_SPEC.md`, create the venv and install, copy `.env.example` to `.env`. She needs `NVIDIA_API_KEY`, `NEMOTRON_MODEL` (from NVIDIA's HackUTD guide) and `GEMINI_API_KEY`; Claude should ask her to paste them into `.env` herself and never commit them. T-Mobile's dataset files go in `data/raw/`. Run `pytest` to confirm the scaffold works.
3. **Claim her issues:** `gh auth status`, then `gh issue list --label owner:lavanya`, then assign herself to each with `gh issue edit <n> --add-assignee @me`.
4. **Work order with numbers:** L1, L2, L3 (POC gates P1 to P3), then L4 and L6 (needed for gate G1 with Arnav), then L5, L9, L7, L8, L10, L11.
5. **The loop for each issue:** pull `main`; create branch `<id>-<short-name>`; read the issue and the doc sections it names; implement; write tests; run `pytest`; tick the issue's checkboxes; open a PR with `Closes #<n>`; tell Lavanya what changed and how to check it; move to the next issue.
6. **Coordination rules:** contract changes go in a PR titled `[contracts] ...` and Arnav must see it; G1 is a joint gate with Arnav; Arnav owns Nessie, redaction, the replay cache, the link, sender and campaign tools, and the UI, so don't edit those modules. Report POC gate results (P1 to P3, including the baseline's macro F1) to Arnav as soon as they're known.
7. **The rules from `CLAUDE.md` that must never break.**

Commit `prompts/lavanya-start.md` straight to `main` (docs-only change) with the message `Add Lavanya's starter prompt`, and push.

## 7. Report back

Finish with:
1. A table of every issue: number, ID, title, owner, milestone, assignee.
2. The link to the tracking issue.
3. Lavanya's complete starter prompt in a single code block I can copy and send her. Use a four-backtick fence (````) around it so the code blocks inside it don't break it.
4. A reminder that Lavanya must be a collaborator on the repo (Settings, Collaborators) before she can push or be assigned.
