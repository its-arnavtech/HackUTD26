# SentinelAI

**Detect. Investigate. Protect.** A scam protection agent that checks a suspicious text and the customer's real bank activity together, then tells them exactly what to do.

HackUTD 2026 · Arnav and Lavanya · T-Mobile, NVIDIA (Nemotron) and Capital One (Nessie) tracks

## Docs

- [POC and MVP plan](docs/POC_MVP.md): scope, architecture, API, screens, demo script, issue breakdown
- [Data spec](docs/DATA_SPEC.md): exactly what Nemotron and Gemini receive, tool contracts, redaction
- [Claude Code prompts](prompts/README.md): the prompts we use to scaffold, create issues and build

## How it works

1. A text arrives in the customer's simulated inbox.
2. Personal details are redacted.
3. A classifier tags the scam type using T-Mobile's taxonomy.
4. A Nemotron agent plans and runs its own checks: link, sender, scam campaigns, Nessie account activity and bills, and Gemini-grounded public reports.
5. The customer sees one result card: verdict, confidence in words, a one-sentence reason and at most three actions.
6. If they already clicked, recovery mode looks for activity they didn't make and walks them through next steps.

Setup instructions are added by the scaffold step.
