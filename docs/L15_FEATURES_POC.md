# L15 features: POC and design

**Status:** building, 2026-11-08. Owner: Lavanya (Claude Code). Branch `l15-agent-eval-and-alerts`, off `main` after the editorial redesign (#78).

Four features, each with a real use for a bank or carrier. A fifth idea ("Is this really them?" contact check) is parked.

Design rule for all four: **no new visual design.** New screens use the existing console frame (`Shell`) and its `.cx` tokens, which the editorial redesign already restyled (warm paper, deep ink, one ink-blue accent, amber only for a scam warning, square corners). No new colours, fonts or components beyond what `console.css` already defines.

---

## 1. Agent accuracy run and dashboard

**Problem.** We measure the classifier (macro F1 0.875) but not the Nemotron agent, the part that makes the final call. Judges, and any bank evaluating us, will ask how often the agent is right.

**Who uses it.** Fraud and model-risk teams before rollout; judges during the demo.

**What it does.**
- `python -m scripts.evaluate_agent --per-category 5` runs the real pipeline on a balanced sample from the **held-out test split** of Arnav's multiclass set (`messages_multiclass.jsonl`, `split == "test"`, template set B). That's evaluation, which is what the test split is for: nothing here trains, tunes or seeds anything. Each message goes through our own classifier, then the live Nemotron agent with its tools.
- It writes `eval/agent_metrics.json`:
  - overall accuracy and accuracy per category
  - "not sure" rate
  - scams caught (recall)
  - false alarms on real messages
  - average and worst time
  - average number of tool calls, and how often each tool was chosen
- It records the model name, the date and the sample size, so the claim is honest.
- `GET /api/agent-metrics` serves it, and an **Agent accuracy** page shows it.

**Scoring.**
- A scam is right when the verdict is "likely scam". A real message is right when the verdict is "likely safe".
- "Not sure" is counted separately; it is never treated as right or wrong.

**Out of scope.** Re-running in CI (it costs live model calls), and tuning the agent on the test split.

**Test.** Pure scoring functions get unit tests. The runner is tested with a fake agent. The real run is live.

---

## 2. Connect the adapters to the agent

**Problem.** "Plug into any system" today only *previews* the mapping. The agent's bank tool still reads only Nessie, so the configurability claim isn't real yet.

**Who uses it.** An integration engineer at a bank or carrier.

**What it does.**
- On the Plug into any system page, **"Use this system for the agent"** makes the chosen system's records (as mapped by its YAML file) the agent's account-activity source. It's in memory, for this server only.
- `nessie_recent_activity` then reads canonical events from that source instead of Nessie:
  - Events are shifted so the sample's "text arrived" time lines up with the message being checked.
  - Items are flagged with the same signals as the preview: new payee, amount far above the usual, new channel, SIM or device change before a payment, soon after the text.
  - The result is the existing `NessieRecentActivityResult` shape, so the agent, guardrails, UI and "Was this you?" all work unchanged.
- **"Back to Nessie"** restores the default. The System view's tool card shows which system answered.

**API.**
- `POST /api/connect/active` with `{source, records?}`, `DELETE /api/connect/active`, and `GET /api/connect/active`.

**Privacy.**
- Flagged items carry references (`evt_3`), never payee names, as the contract already requires. Names appear only in the customer's "Was this you?" card.

**Test.**
- Each system as the active source produces flagged items.
- Recovery resolves an `evt_` reference.
- Resetting falls back to Nessie.

---

## 3. Trusted-contact alert

**Problem.** Older adults, the main victims, often freeze. A second person who can call them right away is one of the most effective interventions, and banks already offer "trusted contact" for accounts.

**Who uses it.** The customer (tap to alert) and the trusted contact (receives the alert).

**What it does.**
- The customer saves one trusted contact (name and phone). The phone is shown masked (`•••• 4471`), held in memory and never sent to a model.
- On a scam verdict, or after "No, I don't recognise it" in recovery, the customer sees **"Tell Maya"**. Tapping it builds the alert:

  > SentinelAI: Linda may be in a conversation with a scammer right now. Please call her. We have not moved any money. (No message content is included.)

  The alert is **simulated for the demo**: it shows the exact text and the masked number, and logs the action. Nothing is sent, which matches every other action today.
- It never fires without the customer's tap (AGENTS.md section 7), and it never includes message text, links or amounts.

**API.**
- `PUT /api/trusted-contact` with `{name, phone}`, `GET /api/trusted-contact` (masked), and `DELETE`.
- `POST /api/actions` with `alert_trusted_contact` returns the preview in `note`.

**Test.**
- No contact set gives a clear "add a trusted contact first".
- The alert text never contains the message, a link or an amount.
- The phone is masked in every response.

---

## 4. Scam-wave early warning

**Problem.** Scams arrive in waves: the same template sent to thousands within hours. Catching a wave early lets a carrier or bank warn customers *before* the text reaches them.

**Who uses it.** A carrier or bank fraud-operations desk, and indirectly every customer.

**What it does.**
- Every message SentinelAI sees is reduced to a **template fingerprint**:
  - lowercase, digits become `0`, links become `url`, punctuation removed, plus the claimed brand and link domain pattern
  - the text is **not** stored
- A rolling window counts fingerprints. A **wave** is 5 or more in 60 minutes, or 3 times the previous hour.
- The **Scam waves** page lists active waves: brand, category, count in the last hour, first seen, a redacted example and the trend.
  - **"Warn customers"** previews a simulated broadcast ("A fake T-Mobile overdue-bill text is going around. T-Mobile won't ask you to pay by link.") and logs it.
- **"Simulate a wave"** replays one of Arnav's 32 seeded campaigns (5 to 15 variants each, set A wording) through the fingerprinting only (no model calls), so the demo can show a wave forming in seconds.
- An active wave also shows as a one-line notice on the System view.

**API.**
- `GET /api/waves`, `POST /api/waves/simulate` with `{campaign_id?}`, and `POST /api/waves/{id}/warn`.

**Privacy.** Only fingerprints and counts are kept; examples are already redacted.

**Test.**
- Fingerprints are stable across numbers, links and case.
- The threshold and growth rules are tested.
- Simulate creates a wave, and the warning text contains no link.

---

## Parked: "Is this really them?" contact check

The idea: give customers the official contact route for a brand, only from our verified list. It's useful once `data/brands.json` is complete, which it isn't yet (no UPS, for example). Revisit after the brand list is filled.

## Demo flow with the new features

1. **Agent accuracy:** "Here's how often the agent itself is right, on held-out messages, by category."
2. **Plug into any system:** pick "Carrier billing and SIM events", choose "Use this system for the agent", run Scenario 1. The agent's bank check now reports the SIM change and port-out.
3. **Trusted contact:** after "No, I don't recognise it", tap "Tell Maya" and show the exact alert.
4. **Scam waves:** "Simulate a wave". The wave appears, then "Warn customers".

---

## Results (built and run live, 2026-11-08)

### 1. Agent accuracy: the first real measurement

`python -m scripts.evaluate_agent --per-category 5`: 45 held-out test messages, live `nvidia/nemotron-3.5-bolt-e4b`. Committed as `eval/agent_metrics.json`.

| Measure | Result |
| --- | --- |
| Right | **33%** |
| Not sure | **67%** |
| Wrong (scam called safe, or real called scam) | **0%** |
| False alarms on real messages | **0%** |
| Average / worst time | 11.9 s / 21.9 s |
| Tools per check | 3.7 on average (campaign 93%, link 91%, sender 89%, public reports 80%, bank activity 13%) |

| Category | Right | Not sure |
| --- | --- | --- |
| Fake delivery | 100% | 0% |
| Toll or government | 80% | 20% |
| Account security | 60% | 40% |
| Prize or refund | 40% | 60% |
| Bank impersonation | 20% | 80% |
| Fake billing, job offer, conversation lure | 0% | 100% |
| Legitimate | 0% | 100% |

**What it means.** The agent never gave a wrong answer, but it is far too cautious: it says "not sure" on two thirds of messages, including every real one. The tool trails point to why:
- **Missing brand data.** For brands outside `data/brands.json`, the sender check returns "official channels unknown", and public reports fail with "Unknown claimed brand".
- **Gemini is off.** Public reports can't add evidence.
- **Synthetic `.test` links.** RDAP finds no record, so the link check stays inconclusive.
- **Strict guardrails by design.** "Very likely" needs two independent findings, and a classifier/tool disagreement means "not sure".
- **Weaker classifier.** The baseline classifier stands in for `classifier-v2.pkl`, which isn't on this laptop.

**Next steps.** Make these changes on the **validation** split, never the test split:
1. fill the brand list
2. turn on Gemini
3. use `classifier-v2.pkl`
4. revisit the "not sure" rules

Then re-run this script on the same held-out sample and compare.

### 2. Any payment system as the agent's bank source

This works live. With PaySim switched in on the Plug into any system page, Scenario 2's recovery check flagged `evt_3`: "new payee; $1,850.00 is 34x the usual $54.20". The customer was asked "Was this you? $1,850.00 transfer to C9988", and the System view's tool card names PaySim as the source. The same works for Sparkov, IBM AML, the card-processor feed and Nessie's own records.

Carrier events (SIM change, port-out) stay preview-only, as planned.

### 3. Trusted contact

This works live. After the recovery verdict, the customer saved "Maya", the phone showed as `•••• 4471`, and tapping "Tell Maya" returned the exact simulated text, with no message content, link or amount.

### 4. Scam waves

This works. "Simulate a wave" replays a 15-variant Walmart campaign (rotating wording and look-alike domains, one with a Cyrillic letter), and it shows as one wave: 15 in the last hour. "Warn customers" returns a broadcast with no link. Real checks feed the detector too.

**Fingerprint change from the plan.** Grouping by exact wording missed the wave, because real campaigns rotate wording. A wave is now keyed by brand plus scam type, falling back to the wording skeleton when there's no brand.

## Live demo content: real companies and financial institutions only

**Surprise me and Simulate a wave** only impersonate real companies and financial institutions (`DEMO_BRANDS` in `app/connect.py`):
- carriers: T-Mobile, Verizon
- banks and payments: Capital One, Chase, Wells Fargo, PayPal
- major consumer companies: Amazon, Apple, Google, Microsoft, Netflix, Walmart, Target, UPS, FedEx, LinkedIn, Indeed

**Left out of the live demo:** Arnav's made-up brands (Northline Mobile, Harbor Mutual, Hearthside Hire and others), government senders (IRS, USPS, toll agencies) and unbranded "wrong number" texts. As a result, the scam-type picker no longer offers "conversation lure" or "toll or government".

**Real messages.** The linked scenarios only had legitimate messages from made-up carriers, so "real message" draws come from five hand-written, synthetic Capital One and T-Mobile messages. Capital One's use its official short codes from `data/brands.json`, so the sender check can confirm them. T-Mobile doesn't publish its sending short codes, so a real T-Mobile message can't be confirmed by sender.

**Unchanged:** the agent accuracy run still uses the full held-out test split (all 9 categories, as labelled), because it is a measurement, not demo content.

"Simulate a wave" now picks a random allowed campaign each time, so every judge sees a different company's wave.

## L15b: added in a short follow-up

- **Privacy Control Center** (`/privacy-center`):
  - a table of exactly what is processed and what never is, matching what the code does
  - what's kept for this customer right now
  - a working **Delete my data** button (`DELETE /api/my-data`): it clears the customer's messages, scam memory, trusted contact and agent transcripts on this server; only anonymous wave counts remain
- **Before you act** (scam interruption, on the System view after a scam verdict):
  - why the message is suspicious, including its deadline pressure
  - how to reach the real company yourself: only from `data/brands.json` (verified on the brand's own pages, `GET /api/official-contact`), never from the message
  - what not to do, based on what the message asks for
  - what to do if money already moved
- **Personal scam memory** (opt-in, `PUT /api/memory/consent`, `POST /api/memory/{id}`):
  - keeps only brand, scam type, link domain and a wording hash per checked message
  - flags repeats ("the same link domain as a message you checked at…")
  - turning it off deletes what was kept

Tests: `tests/test_protection.py`. Backend 839 passed, frontend 82 passed.

## L15d: stays in the console, correct answers for typed scams, two more features

**No more jumps to the main site.** The console's "Accuracy" now opens the classifier accuracy screen inside the console (`/model-accuracy`), and the "Desk" link is gone. A browser walk across every tab stayed inside the console.

**Typed scam messages.** `python -m scripts.typed_check` runs 9 realistic typed messages (7 scams impersonating real companies with real-looking links, 2 genuine) through the live pipeline. Before: PayPal was missed and the Wells Fargo scam was explained as "not an official Capital One channel". After: **6 of 7 scams caught, none called safe.** The remaining one, a Wells Fargo "reply with the code" text with no link, is honestly "not sure", because no tool can verify a code request. The fixes:
1. **More real companies** in `data/brands_extra.json` (Verizon, Chase, Wells Fargo, PayPal, Amazon, Apple, Google, Microsoft, Netflix, Walmart, Target, UPS, FedEx, USPS, LinkedIn, Indeed). Official websites only; sending short codes are left empty because they weren't verified.
   - It's kept separate from `brands.json` on purpose: the campaign matcher (A12) and its calibration, and the recorded demo replays (A19), still use the original registry only. `core_only` / `core_brands_only` flags make sure of that, and all replay tests pass unchanged.
2. **Redaction keeps brand names.** "Wells Fargo" was being hidden as `<PERSON>`, so the agent never knew the claimed brand.
3. **Brand terms match at a domain-label boundary,** so "chase" no longer fires inside "purchase" and "ups" no longer fires inside "groups" (`features/extract.py`, `tools/link.py`, *Arnav's area*).
4. **Symmetric disagreement guardrail.** A weak "legit" score (below 0.7) no longer forces "not sure" over verified tool evidence; a confident one still does. The "very likely" rule (two independent findings) is unchanged.

**New features.**
- **Link and sender safety** panel: the link's domain, look-alike brand, blocklist status, age and signals, or "could not be checked". The link is shown as plain text and is never clickable. The sender is shown as official, not official, or "could not confirm", always with "caller ID and sender numbers can be faked".
- **Simulated incoming text:** a phone-style notification ("Potential scam detected …") for a random real-company message, run through the same live pipeline. It's labelled as a simulation; "See why and what to do" scrolls to the result.

Tests: backend 840 passed, frontend 87 passed (new `alert.test.tsx`), plus the live browser walk.

## L15e: demo examples and Safety Center

**Try an example** (under "Check any message"): six one-click synthetic examples from the demo plan, each run live through the real pipeline, with the correct answer shown where there is one.

| Example | Live answer |
| --- | --- |
| Bank account suspension (Chase) | Likely a scam ✓ |
| Fake delivery fee (UPS) | Likely a scam ✓ |
| Guaranteed investment (Wells Fargo) | Likely a scam ✓ |
| One-time-code theft (Amazon, "reply with the code", no link) | Not sure |
| Genuine Capital One alert (official short code) | Not sure (not called a scam) |
| Ambiguous appointment reminder | Not sure ✓ (the honest answer) |

**Known gap.** Texts that ask you to *reply with a code* and contain no link are "not sure", because no tool checks what a message asks for. **Next step:** a small `asks_for_code` content check that turns "share a one-time code" into verified evidence.

**Safety center** (`/safety`): six common scams (bank impersonation, one-time-code theft, fake delivery, investment, job, family emergency). Each has how it works, the warning signs, a synthetic example, how to protect yourself and what to do if you already fell for it. Quizzes are not built.

Tests: frontend 90 passed (new `examples.test.tsx`).

## L15f: code-theft texts fixed

**New tool `check_request`.** It's local and reads only the redacted text. It flags requests to reply with, send, share or read back a one-time code, PIN or password, and ignores negated wording ("never share this code") and normal sign-in wording ("enter this code"). Nemotron is offered it **only when a message asks for something**, so ordinary messages keep exactly the same tool list and system prompt, and all recorded replays still pass.

**Rule.** If `check_request` verifies a code or password request and the answer would be "not sure", it becomes "likely scam" with the reason "real companies never ask for one". "Very likely" still needs two independent findings.

**Live result** (`scripts/typed_check.py`, 11 messages): **8 of 8 scams caught**, including both code-theft texts. The 3 genuine messages (a Capital One code, a Capital One purchase alert, a T-Mobile bill) are "not sure" and none is called a scam.

**Also fixed.** WhatsApp sends "Checking this now" before starting the check, so it can't arrive after the verdict.

**Contracts:** `ToolName.check_request`, `CheckRequestArgs` and `CheckRequestResult` were added (mirrored in `types.ts`). Tests: backend 852 passed, frontend 90 passed.
