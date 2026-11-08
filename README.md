# SentinelAI

**Detect. Investigate. Protect.** A scam protection agent that checks a suspicious text and the customer's real bank activity together, then tells them exactly what to do.

HackUTD 2026 · Arnav and Lavanya · T-Mobile, NVIDIA (Nemotron) and Capital One (Nessie) tracks

## Docs

- [POC and MVP plan](docs/POC_MVP.md): scope, architecture, API, screens, demo script, issue breakdown
- [Data spec](docs/DATA_SPEC.md): exactly what Nemotron and Gemini receive, tool contracts, redaction
- [Agent rules](AGENTS.md): shared rules for Claude Code, Codex and Cursor
- [CHANGELOG](CHANGELOG.md): status board, in-progress handoffs, done log, decisions
- [Prompts](prompts/README.md): which prompt goes to which tool, in order

## How it works

1. A text arrives in the customer's simulated inbox.
2. Personal details are redacted.
3. A classifier tags the scam type using T-Mobile's taxonomy.
4. A Nemotron agent plans and runs its own checks: link, sender, scam campaigns, Nessie account activity and bills, and Gemini-grounded public reports.
5. The customer sees one result card: verdict, confidence in words, a one-sentence reason and at most three actions.
6. If they already clicked, recovery mode looks for activity they didn't make and walks them through next steps.

## Setup (Windows, PowerShell)

Needs Python 3.11 or newer, Node 20 or newer, and git. Run everything from the repo root unless noted.

```powershell
# 1. Secrets: copy the template, then paste your keys into .env yourself (never commit it)
Copy-Item .env.example .env

# 2. Backend: venv and dependencies (use any Python 3.11+, e.g. py -3.12)
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 3. Run the API with mocks (USE_MOCKS=true in .env). Ports come from your folder's .env.
$env:API_PORT = (Select-String -Path ..\.env -Pattern '^API_PORT=(\d+)').Matches[0].Groups[1].Value
uvicorn app.main:app --reload --port $env:API_PORT

# 4. Tests (from backend/)
python -m pytest
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev     # serves on WEB_PORT and proxies /api to API_PORT, both from the repo-root .env
npm run build   # type-check and production build
```

Optional packages (spaCy, torch, transformers) are not in `requirements.txt`; issues A3, A5 and L7 decide whether to add them.

### Data

- `data/generated/`: our generated message set and its datasheet (A21, committed)
- `data/raw/`: downloaded public datasets such as the public SMS spam set (A5, gitignored)
- `data/taxonomy.json`: scam categories plus `legit` (placeholder until A21)
- `data/brands.json`: official domains and channels for the demo brands (A10 fills the channels)
- `data/scenarios/`: the three demo scenario messages
- `data/fixtures/`: record and replay cache (L1)
- `eval/`: metrics written by the scripts

### Agent folders

Each of Arnav's agents works in its own git worktree with its own ports (see `docs/POC_MVP.md` section 12): `C:\HackUTD26` (8000/5173), `C:\HackUTD26-cc` (8001/5174), `C:\HackUTD26-codex` (8002/5176), `C:\HackUTD26-design` (8003/5175).
