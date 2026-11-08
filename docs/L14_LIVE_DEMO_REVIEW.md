# L13 + L14 review: live demo, agent fix, auth

**Status:** open for review, 2026-11-08. Owner: Lavanya (Claude Code). Arnav to review the parts marked *Arnav's area*.

This page explains what this PR adds, how to demo it, what we found by running it live, and what to fix next. Everything here was run on Lavanya's laptop with live NVIDIA Nemotron and Capital One Nessie calls.

## What this PR adds

| Part | What it does | Default |
| --- | --- | --- |
| **Agent fix** (`backend/app/agent/loop.py`) | Nemotron sometimes writes its tool calls as a JSON list in its text (`[{"tool_name": "check_link", "parameters": {...}}]`). The loop didn't read that format, so the agent skipped every check and then cited checks that never ran. It now runs them. Only our 6 tool names are accepted. | On |
| **System view** (`/`) | One screen that shows the real backend, live: pipeline stages, original vs. redacted message, the exact JSON sent to Nemotron, every model call (latency, tools it chose with their arguments, reasoning, final answer), every tool's real result, re-plans, and the customer outcome. | On |
| **Check any message** | Type or paste any message and run it through the live pipeline. | On |
| **Surprise me** | Picks a random message from Arnav's 320 labelled linked scenarios (template set A only, never the test split), runs it, and shows the correct answer next to SentinelAI's verdict (✓, ✗ or "not sure"). | On |
| **Scenario 2 button** | Runs scenario 1, then "she already clicked" (recovery re-plan) automatically. | On |
| **Plug into any system** (`/connect`) | Records from 6 systems (Nessie, PaySim, Sparkov, IBM AML, card-processor feed, carrier billing and SIM events) in their own format → Arnav's YAML mapping → one canonical event → the same fraud signals for every system. | On |
| **Agent transcript endpoint** | `GET /api/messages/{id}/agent`: each real Nemotron call for a message. Redacted data only, in memory, cleared on reset. | On |
| **L13 authentication** | Passkeys, Argon2id password + TOTP, ES256 JWT in HttpOnly cookies, rotating refresh tokens, CSRF, deny-by-default roles + ownership checks, rate limit, lockout, hash-chained audit log, AES-256-GCM for secrets at rest. | **Off** (`AUTH_ENABLED=false`) |
| **SMS and WhatsApp channels** | Text or WhatsApp a message to SentinelAI and get the verdict back, with CLICKED / YES / NO follow-ups. Built and tested, **not connected**: a Twilio trial can't receive texts, and WhatsApp needs a Meta app. | Off until configured |
| **New screens** | Clean modern style, full-page sign-in, `/customer`, `/patterns`, `/security`, restyled `/accuracy`. The original phone-frame demo stays at its old URLs (`/inbox`, `/result/...`). *Arnav's area.* | On |

## How to demo it (3 minutes)

Run the backend live: `USE_MOCKS=false`, `DEMO_MODE=live`, with `NVIDIA_API_KEY` set. Then open the System page.

1. **Scenario 1.** The pipeline lights up. Point at "What the AI is allowed to see" (privacy), then the Nemotron calls: it chose `check_link`, `check_sender`, `nessie_recent_activity` and `match_campaign`, then re-planned to add public reports. Each tool shows its real result (Nessie: 2 accounts, 6 items, none flagged).
2. **Scenario 2.** Recovery re-plan: Nessie flags the $900 purchase, and the customer is asked "Was this you?".
3. **Scenario 3.** A different plan (bill status instead of account activity): proof the agent decides.
4. **Surprise me.** A judge picks a scam type, and a new message runs live with the correct answer shown.
5. **Plug into any system.** Switch between the 6 systems; edit a record and remap it.

## Answers to common judge questions

**Do we use DeepSeek or Gemini to pull data from the internet?** DeepSeek only generated the training dataset, offline; it never sees a customer message. Gemini with Google Search grounding powers `public_scam_reports` (4 non-personal fields only). It's off until `GEMINI_API_KEY` and `GEMINI_MODEL` are set. Links are checked with RDAP; bank activity comes from Nessie.

**What does Nemotron see?** Only redacted data:
- the message with `<PERSON>` and `<URL_1>` tags
- the sender type, a hashed sender tag and the claimed brand
- link facts: registered domain, whether it's a shortener, brand term, whether it's the official domain
- features: deadline, threat, what it asks for
- the classifier category and score
- whether a bank is linked
- the results of the tools it chose

Never names, phone numbers, account numbers or full links.

**What has it been tested on?** 9 categories: bank impersonation, fake billing, fake delivery, account security, toll or government, prize or refund, job offer, conversation lure, and legitimate look-alikes.

| Measure | SentinelAI | Baseline |
| --- | --- | --- |
| Macro F1, held-out synthetic test (388) | **0.875** | 0.792 |
| False alarms, synthetic test | **8%** | 16% |
| Spam caught, real public SMS set (2,787) | **77%** | 19% |
| False alarms, real public SMS set | **0.1%** | 3.3% |
| Weakest category | Bank impersonation, F1 0.69 | 0.62 |
| Nemotron agent accuracy | **not measured yet** | — |

**Could it go to production in a week?** A pilot or shadow-mode integration, yes. Production for real customers, no. The biggest gaps:
1. The agent's accuracy is unmeasured, and a check takes about 8 to 14 seconds on the hosted model.
2. Demo-shaped state: messages live in memory on one server, and the customer is hard-coded ("Linda, Capital One").
3. Only Nessie (a mock bank) is wired to the agent. The 6 adapters map data but don't feed the agent's tools yet.
4. No real message intake. Carrier forwarding (7726-style) would be the production route.

Already production-quality: redaction before any AI, guardrails, about 810 tests, record and replay, auth and encryption (off by default), and the audit log.

## What the live run exposed (fix next)

A random "fake delivery" scam from Surprise me came back **"We're not sure"** when the right answer was "scam". The causes, in fix order:

1. **Classifier fallback.** Without `data/models/classifier-v2.pkl` (only on Arnav's laptop) the app uses the baseline, which said "Legitimate 0.53". Share the file or retrain it with `python -m scripts.train_public_classifier`.
2. **Missing brand data.** "We don't have UPS's official channels": `data/brands.json` lacks UPS and many other brands, so the sender check can't conclude anything.
3. **Redaction false positive** (A3, *Arnav's area*). "closes by 9 PM. Open https://…" became `<PERSON> <URL_1>`: "PM. Open" was taken for a name.
4. **Synthetic `.test` links.** RDAP finds no record for them, so the link check is weaker than on real-looking domains.
5. **Measure the agent.** Run it on a balanced sample (about 5 per category) and put agent accuracy on the Accuracy page.

## Review notes

- **Contracts.** Auth models, `MessageSource.sms`, and DATA_SPEC sections 8 and 9 are included. The auth models are also on their own branch, `sec-auth-contracts`, if you want them reviewed separately (AGENTS.md section 4).
- **Frontend redesign** (*Arnav's area*). The System view becomes `/`. The phone-frame screens are kept at their URLs and still pass their tests.
- **Nothing outside is connected by default.** Auth, SMS and WhatsApp are all off until configured. No keys are committed (`.env` stays ignored).
- **Tests.** Backend: 811 passed with auth off; the auth-on suite run (`TEST_AUTH=1`) passed before the merge of `main`. Frontend: 76 passed, build clean, Playwright walks of the System view and `/connect` had no page errors.
