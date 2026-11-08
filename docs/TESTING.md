# Testing handoff

Use your own checkout and its `.env` ports. Keep the active L9 and A17 checkouts
with their owners. Never copy keys into a command, screenshot, issue, or video.

## Automated checks

From the repository root, after installing backend requirements and `npm ci`:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.replay_demo replay
cd ..\frontend
npm test
npm run build
npx playwright install chromium
$env:E2E_PYTHON = (Resolve-Path ..\backend\.venv\Scripts\python.exe).Path
npm run test:e2e
```

The scenario pytest tests run the real agent with recorded Nemotron/Nessie
responses and all network sockets blocked. The profile is explicitly A1
baseline plus five real tools, with public search unavailable. L7's classifier
tests and published accuracy reports are separate. Do not rerun held-out model
evaluation to check application wiring.

The Playwright smoke test starts isolated mock servers on 8021/5188, opens
scenario 1 from the inbox, checks its verdict, trail and privacy panel, checks
for browser exceptions, and confirms that viewing screens posts no action or
transaction confirmation. Override `E2E_API_PORT`/`E2E_WEB_PORT` if occupied.
It runs in the separate Browser smoke workflow on every PR. Failure traces,
screenshots and video are available in that workflow's artifacts.

## App acceptance, after L9 and A17 merge

The repeatable real-API browser gate and recorded app fixtures are documented
in [APP_GATE.md](APP_GATE.md). Use `npm run test:app` with `GATE_MODE=replay`
and the pinned local v2 classifier artifact for the authored offline flows.

Set `USE_MOCKS=false` in your own `.env`, use `DEMO_MODE=live`, and launch
`scripts/dev.ps1`. Check `/api/health`: every required route should be live.
Use the existing synthetic Nessie seed; no new banking writes are necessary.

| Check | Expected evidence |
| --- | --- |
| Scenario 1 | Likely scam; link/sender checks and a bank activity check; wording says what was checked |
| Scenario 2 | Tap the recovery button; new recovery trail; $900 purchase at Unknown Payee, 17 minutes after the text; answer Was this you; checklist |
| Scenario 3 | A different plan; T-Mobile bill completed on 2026-11-01 with $0 due; campaign match |
| Privacy | Redacted message and actual recipient payloads; no full bank history or payee names in model payloads |
| Consent | No protective action or transaction confirmation until a tap |
| Failure | Retry works; model/tool errors are honest; polling ends at done |
| Accuracy | Real `eval/metrics.json`; correct public development/holdout labels; no illustrative mock numbers presented as measured results |

Record the actual app requests and repeat the three flows with network access
blocked before marking G2/A19 complete. CLI cache keys are different from app
message IDs and classifier outputs; copying CLI fixtures alone is insufficient.
Save an under-three-minute backup video of the working app, then do three timed
human rehearsals. A successful mock browser test does not close those gates.
