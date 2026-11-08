# Recorded authored scenarios

These fixtures were recorded from NVIDIA Nemotron, Capital One's synthetic
Nessie bank, and RDAP using `python -m scripts.replay_demo record`.
`demo_profile.json` identifies the exact profile and observed plans.

The profile uses the real A1 baseline, redaction, feature extraction, L8 agent,
and five tools. Public search is deliberately returned as unavailable. This
makes cache keys independent of each developer's ignored local L7 artifact.
The public salt is for the authored synthetic demo numbers only.

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.replay_demo replay
.\.venv\Scripts\python.exe -m pytest -q tests/test_scenarios_e2e.py
```

Both commands block network sockets during scenario execution. Missing fixtures
fail the acceptance assertions; there is no live fallback. Normal pytest never
records or calls a live model. Fixture requests and responses were checked for
the configured API keys before commit. All bank records are synthetic.

These are CLI integration fixtures. They do not establish G2's live/replay app
acceptance, use L7's evaluation model, cover arbitrary new messages, or replace
the backup video. Changes to prompts, tool schemas/results, message IDs, model,
or classifier inputs require deliberate re-recording of authored scenarios.
