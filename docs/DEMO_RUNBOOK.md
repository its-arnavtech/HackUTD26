# SentinelAI demo runbook

PowerShell, from a checkout that already has `.env`. Never print a key. Actions stay simulated: a tap records the choice, and the app does not send a text, freeze a card, or move money.

The planted $900 is a **purchase at Unknown Payee**, 17 minutes after scenario 2's text. Scenario 3's campaign match is **historical** (28 on record). The last-24-hour count is 0 because those fingerprints keep their original dates. Say "on record", not "today" or "in the last day".

Public reports are the merged L10 tool (PR #66). The live Gemini citation gate is blocked: 3.5 returns 429 and the listed 2.5 model returns 404. Say a public report only when that tool actually returned a citation. The A18 CLI profile and PR #69's app-gate profile both set public search explicitly unavailable. Do not invent a citation.

## Startup

```powershell
cd C:\HackUTD26
# .env must set PHONE_HASH_SALT (any long random string), USE_MOCKS=false, DEMO_MODE=live
# and NVIDIA_API_KEY, NESSIE_API_KEY, NEMOTRON_MODEL=nvidia/nemotron-3.5-bolt-e4b
cd backend
.\.venv\Scripts\Activate.ps1
python -m scripts.seed_campaigns --verify-scenario3
cd ..
.\scripts\dev.ps1
```

Open the URL `dev.ps1` prints (the folder's `WEB_PORT`). The first real check trains the baseline classifier if `data/models/classifier-v2.pkl` is absent (about half a minute, in the background). `GET /api/health` should show `use_mocks: false`.

Campaign seed reads the train split only and does not call the network. `--verify-scenario3` checks the historical match. If it prints `Campaign seed failed`, stop and fix that before the demo.

## Reset

There is no reset button. From another PowerShell window, using the API port in `.env` (8000 below):

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/demo/reset
```

The inbox reloads the three messages. A check that was still running is dropped, including one that would otherwise finish onto the same message id. Refresh the inbox after reset.

## Scenarios

1. **Scenario 1.** Inbox, open the Capital One "account locked" text (`msg_0001`). Wait until the trail grows and the card says likely a scam. Open "How we checked", then the privacy panel. The panel shows the redacted message. Do not tap Block, Report, or Alert unless you mean to show the simulated confirmation. Nothing is sent.
2. **Scenario 2.** On that result, tap "I clicked and entered my info". Recovery should find the $900 purchase at Unknown Payee and ask "Was this you?". Answer either way. The checklist appears only after that tap. "I only opened the link" skips the bank check and goes to the checklist.
3. **Scenario 3.** Inbox, open the T-Mobile bill text (`msg_0003`). The plan is different. The bill check should say paid on 2026-11-01 with nothing due. The campaign line is a known pattern on record, not new activity in the last 24 hours.

Also, before judging: Consent can link or skip, and skip does not start a bank check. Campaigns and Accuracy open from the stage. An unknown id such as `/api/messages/msg_9999/result` is a 404. Accuracy reads `eval/metrics.json`, including the public holdout labels already published. Do not retrain or rescore.

## Trusted contact call (L16)

On the scenario 2 recovery checklist (phone demo and console), "Alert my trusted contact" calls the trusted contact. If the call isn't answered, the backend emails them instead. Nothing happens until the customer taps, and the call and email carry a content-free alert only, never the scam text, links or account data (`DATA_SPEC.md` section 10).

**Setup keys** in the repo `.env` (names in `.env.example`; never print them):
- `VOICE_ALERTS_ENABLED=true` and `DEMO_MODE=live`.
- Twilio: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (the SentinelAI number, E.164).
- Gmail sender: `ALERT_EMAIL_FROM` and `ALERT_EMAIL_APP_PASSWORD` (a Google app password, not the account password).
- The trusted contact: `TRUSTED_CONTACT_PHONE` (Lavanya's number, E.164) and `TRUSTED_CONTACT_EMAIL`. These are what get called and emailed; the contact saved in the console is display only.

**Once, before the demo:** Lavanya adds the Gmail sender address to her contacts so the fallback email lands in Primary, not Spam or Promotions.

The screen polls every 2 seconds while the call rings, and stops when the alert is done or after 120 seconds. There is a 60-second cooldown between alerts for the same message.

- **Path A, she answers.** Run scenario 2 to the checklist and tap "Alert my trusted contact". The status reads "Calling your trusted contact…", then "They picked up."
- **Path B, she declines.** Wait out the cooldown and tap again. She declines the call. The status reads "They didn’t pick up. We left a voicemail and emailed them." (or "…We emailed them." when no voicemail was left), and the email arrives in her Primary tab. If it doesn't, mark it "Not spam" or move it to Primary and repeat once.
- If nothing could be sent, the status reads "We couldn’t reach them. Here’s what to tell them:" followed by the alert text, shown as plain text.

**Replay and flag off are simulated.** With `DEMO_MODE=replay` or `VOICE_ALERTS_ENABLED=false`, no call or email goes out. After about 3 seconds the status reads "They didn’t pick up. We emailed them. (simulated)".

## Replay fallback

CLI fixtures are already on `main` and were checked with sockets blocked. They do **not** replay the app: cache keys include the message id, the classifier output, the phone-hash salt, and the model.

App-shaped recordings are on PR #69 (`codex/g2-replay-only`), not on this branch. That PR conflicts with current `main` and still needs a merge commit after a rebase. Its profile pins a local L7 v2 pickle (`data/models/classifier-v2.pkl`, gitignored). Do not retrain or pass `--evaluate`. Once that branch is current:

```powershell
cd C:\HackUTD26\frontend
$env:E2E_PYTHON = (Resolve-Path ..\backend\.venv\Scripts\python.exe).Path
$env:GATE_MODE = 'replay'
npm run test:app
```

That gate uses the real API with `USE_MOCKS=false`, allows only loopback, and fails a cache miss instead of calling out. `docs/APP_GATE.md` on that branch is the full note.

```powershell
cd C:\HackUTD26\backend
# CLI proof, no network, no keys. Expect three likely_scam results and public search unavailable.
.\.venv\Scripts\python.exe -m scripts.replay_demo replay
```

`python -m pytest tests/test_scenarios_e2e.py` is the offline check for the CLI recordings. `npm run test:e2e` is the mock-API browser smoke (scenario 1 only). Neither one is the live app walk. Re-record only if #69's fixtures are rejected: `DEMO_MODE=record`, `USE_MOCKS=false`, same `PHONE_HASH_SALT`, walk scenario 1, then "I clicked" for scenario 2, then scenario 3. Commit new files under `data/fixtures/` only after they contain no API key or raw customer payload.

## Backup video (Arnav records; not recorded yet)

One take, under 3:00, with `USE_MOCKS=false`. If the network is unreliable, use the replay walk above.

| Time | On screen |
| --- | --- |
| 0:00 | Linda gets the account-locked text. |
| 0:20 | Accuracy page: ours against the baseline, by category, false positives, public holdout. |
| 0:40 | Scenario 1: trail filling in, what the bank check found, verdict, privacy panel. |
| 1:20 | Scenario 2: "I clicked", re-plan, $900 purchase at Unknown Payee, "Was this you?", checklist. |
| 2:00 | Scenario 3: a different plan, bill paid 2026-11-01, campaign on record. Mention a public report only if L10 returned a citation. The live Gemini gate is blocked, and the recorded app profile leaves that lookup unavailable. |
| 2:40 | "Nemotron plans, Nessie checks the money, the customer decides." |

Do not say the account is fine, that money moved, or that a message was sent.
