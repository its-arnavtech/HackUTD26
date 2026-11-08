# G2 app integration and offline replay

The browser gate uses the real FastAPI routes, L9 pipeline, frozen local L7 v2
classifier, L8 agent, tool registry, synthetic Nessie bank, and real frontend.
`USE_MOCKS=false` is asserted. Optional public search is explicitly unavailable.
No model evaluation, held-out scoring, or banking write is performed.

The integration candidate first combined published A17 `b2ad7f05` with L9 and
passed 65 frontend tests/build, 673 backend tests, and all three app flows in
record mode and offline replay. A17's owner checkout and branch were not
changed. Gate tooling is submitted separately so A17 stays with its owner.

The same gate also passed directly on the main-based frontend in record mode
and offline replay. The gate PR contains no A17 implementation commits.

## Run the gate

Use a checkout with backend requirements, frontend dependencies, and the same
locally generated v2 artifact as the recording. The artifact is ignored and
trusted locally; its hash is pinned in `data/fixtures/app_gate/profile.json`.
Do not download or load an untrusted pickle. A fresh local artifact can be
produced with `python -m scripts.train_public_classifier` using the documented
public cache. Never add `--evaluate` to validate application wiring.

From the repository root:

```powershell
cd frontend
$env:E2E_PYTHON = (Resolve-Path ..\backend\.venv\Scripts\python.exe).Path
$env:GATE_MODE = 'replay'
npm run test:app
```

The gate starts isolated API/web servers on 8022/5189 and stops them afterward.
`GATE_API_PORT` and `GATE_WEB_PORT` can override those ports. It permits only
loopback DNS and socket connections during backend replay; service cache misses
cannot silently reach a live API. The same frozen classifier and original
authored scenario timestamps are used in both runs.

For manual exploration, use two PowerShell terminals from this checkout:

```powershell
# Terminal 1, backend/
.\.venv\Scripts\python.exe -m scripts.serve_app_gate replay --port 8022

# Terminal 2, frontend/
$env:API_PORT = '8022'
$env:WEB_PORT = '5189'
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5189`. Replay covers the authored inbox and recovery
flow; arbitrary new messages need their own deliberate recording or live mode.

For deliberate re-recording of these authored/synthetic scenarios, set
`GATE_MODE='record'`. NVIDIA/Nessie credentials must already be private in that
checkout's `.env`. This makes actual read-only service calls and writes new
fixtures. Do not re-record arbitrary customer messages.

## What is checked

- Bank text: scam result, a bank activity check, visible trail, and no recovery
  references in check mode.
- Bill text: a different plan, bill completed on 2026-11-01, and $0 due.
- Recovery: customer taps first, a new recovery run, `txn_28`, $900 at Unknown
  Payee 17 minutes later, then a second tap records the answer and shows the
  three-step checklist. Viewing screens never posts protective actions.
- Privacy: actual Nemotron receipt is recorded; no raw name/full message link
  or payee detail appears in the model-facing audit data.
- Campaigns and accuracy: actual API data renders, campaign details expand,
  category rows match the current metrics, and the public holdout disclosure
  is visible. There are no browser page or console errors.

Aggregate observations are in `eval/app_gate_record.json` and
`eval/app_gate_replay.json`. The app recordings are separate from A18's
artifact-independent CLI baseline profile. This work covers implementation and
testing; presentation, video and Gemini access are outside the current request.
