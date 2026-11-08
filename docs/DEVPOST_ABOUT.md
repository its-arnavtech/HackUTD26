## Inspiration

Most scam texts aren't clever. They just need you to panic for about thirty seconds. "Your account will be locked in 2 hours." "Your bill is overdue, pay now." The person reading it has no quick way to check if any of that is true, so they either ignore a real alert or click a fake one.

Carriers already block a lot of this at the network level. The thing is, the messages that get through land on someone who is alone and unsure. Our test user is Linda, 67. She banks with Capital One and pays her T-Mobile bill on autopay. We wanted to build something that sits with her in that moment: check the message, check the money, and tell her plainly what to do.

```
   What exists today                         The gap we built for
   ─────────────────                         ────────────────────
   network filter ──► "Scam Likely" label    message gets through
   SIM / port-out locks                        │
   forward to 7726                             ▼
                                             Linda is unsure ──► is the claim true?
                                                                  is my money safe?
                                                                  I already clicked, now what?
```

## What it does

SentinelAI takes one suspicious text and runs it through four stages. Nothing reaches a model until personal details are gone, and nothing happens to Linda's account until she taps.

```
 text arrives
     │
     ▼
 ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌──────────────────────────────┐
 │ Redaction  │──►│  Features  │──►│ Classifier │──►│  Nemotron agent (Bolt E4B)   │
 │ names,     │   │ links,     │   │ 8 scam     │   │  plan ─► call tool ─► read   │
 │ phones,    │   │ deadline,  │   │ types +    │   │   ▲                     │    │
 │ digits,    │   │ threat,    │   │ legit,     │   │   └──── re-plan ◄───────┘    │
 │ addresses  │   │ ask, $     │   │ score      │   │  guardrails ─► verdict       │
 └────────────┘   └────────────┘   └────────────┘   └──────────────┬───────────────┘
       │                                                            │ up to 6 tool calls
       ▼                                                            ▼
 privacy audit log ◄──── what each step received ──── ┌───────────────────────────────┐
                                                      │ check_link    check_sender    │
                                                      │ match_campaign                │
                                                      │ nessie_recent_activity        │
                                                      │ nessie_bill_status            │
                                                      │ public_scam_reports (Gemini)  │
                                                      └───────────────────────────────┘
                                                                    │
                                                                    ▼
                         ┌───────────────────────────────────────────────────────┐
                         │ Result card: verdict in words · how sure · one reason  │
                         │ · at most 3 actions · "How we checked" trail · privacy │
                         └───────────────────────────────────────────────────────┘
```

### Three moments from the demo

| | The text | What the agent decides to check | What Linda sees |
| --- | --- | --- | --- |
| **1. Fake bank alert** | "Capital One Alert: unusual sign-in. Your account will be locked in 2 hours. Verify now: [link]" | `check_link` → `check_sender` → `nessie_recent_activity` | Very likely a scam. The link imitates capitalone.com, the sender isn't an official channel, and we found no unusual activity in the last 7 days. |
| **2. "I clicked and entered my info"** | Same text, after Linda taps the button | Re-plans into recovery: `nessie_recent_activity` since the text arrived | "Was this you?" for a $900 payment to Unknown Payee, 17 minutes after the text. Then a recovery checklist. |
| **3. Fake T-Mobile bill** | "T-Mobile: your bill is overdue. Pay $312 now to avoid suspension: [link]" | `match_campaign` → `nessie_bill_status` (skips the account scan) | Your T-Mobile bill was paid on Nov 1, nothing due. This matches a known campaign of 28 similar messages on record. |

Same agent, three different plans. That's the point: it reads what the message claims and checks that claim, instead of running a fixed script.

Every result also has a **"How we checked" trail** that fills in live while the agent works, and a **privacy panel** that shows exactly what each model received and what it never saw.

## How we built it

### The agent

Nemotron 3.5 Bolt E4B on NVIDIA's API, native tool calling, at most 6 tool calls per message, re-planning after every result. We picked Bolt because it was the only tool-calling model on NVIDIA's free endpoints, and it's fast: about 3 seconds per step, which is what makes the live trail work.

The rules that matter live in code, not in the prompt:

| Guardrail | Enforced how |
| --- | --- |
| "Very likely" needs real evidence | At least two findings from different tools, otherwise downgraded |
| Mixed evidence is allowed | Classifier and tools disagree → verdict becomes "we're not sure" |
| No made-up actions | At most 3, chosen from a fixed list of 8 |
| No dangerous contact info | Phone numbers and links stripped from anything the model writes |
| Customer decides | Every action waits for a tap; the agent never touches money |
| Tool output is data | Text inside tool results is never followed as an instruction |
| Bad output | Schema check, one retry, then "we're not sure" with the evidence so far |

In simplified form, with $E$ the set of tools whose findings point to a scam:

$$\text{verdict} = \begin{cases} \text{very likely a scam} & |E| \geq 2 \;\wedge\; \text{classifier agrees} \\ \text{we're not sure} & \text{signals disagree} \\ \text{likely safe} & \text{otherwise} \end{cases}$$

### What Nemotron actually sees

It sees claims and facts, never identity. Here is the shape of one input (simplified):

```json
{
  "text_redacted": "Capital One Alert: unusual sign-in for <PERSON>. Your account will be locked in 2 hours. Verify now: <URL_1>",
  "sender": { "type": "long_code", "value": "<PHONE_HASH_7f3a>", "claimed_brand": "Capital One" },
  "urls": [{ "id": "URL_1", "registered_domain": "capone-verify-alert.com", "brand_term_in_domain": "capone", "is_official_brand_domain": false }],
  "features": { "urgency_deadline": "2 hours", "threat": "account_lock", "requested_action": "click_link_and_verify", "asks_for": ["login"] },
  "classifier": { "category": "bank_impersonation", "score": 0.94 },
  "customer_context": { "linked_bank": true }
}
```

Tool results come back as summaries with references, for example `{"ref": "txn_28", "amount": 900, "new_payee": true, "minutes_after_message": 17}`. The app turns `txn_28` into "Unknown Payee" only when it shows it to Linda.

| Component | Receives | Never receives |
| --- | --- | --- |
| Classifier | Redacted text + features | Names, phone numbers, account digits, addresses |
| Nemotron agent | Redacted text, features, scores, tool summaries | Raw message, names, account numbers, raw transactions |
| Nessie tools | Customer id + a time window or payee | The message |
| Gemini lookup | Brand, scam type, link domain, a generic lure phrase | Anything else from the message, any bank data |

### Money checks with Nessie

We seeded Linda's world in Capital One's Nessie API: a checking account, a credit card, a month of normal purchases, a T-Mobile bill paid on Nov 1, and the planted $900.

A purchase gets flagged when it sits far above her normal spending:

$$a \geq 10 \cdot \tilde{m}_{30}$$

where $\tilde{m}_{30}$ is her 30-day median purchase. The $900 lands at about $23\times$. We started at $3\times$, but her $5 coffees pulled the median so low that normal grocery runs got flagged.

### Data, because there wasn't any

T-Mobile didn't give us a dataset, so we built one and tried hard not to fool ourselves with it.

```
 DeepSeek (offline only)
   │  each request = category × brand × persona × style → 8 texts
   ▼
 train prompt set ("classifier training data")     test prompt set ("fraud-awareness quiz cards")
   │                                                  │   different brands train never saw
   ▼                                                  ▼
 rewrite every phone number into fake 555-01XX ─► drop refusals and placeholders ─► dedupe
   │
   ▼
 drop any test text too close to a train text (fuzzy match ≥ 85)
   │
   ▼
 + 50 hand-written test texts
   │
   ▼
 2,596 texts total ─► train 1,818 · validation 390 · test 388
```

Legitimate texts were written to look like scams on purpose: real bank alerts, carrier bills, one-time codes, delivery updates. That's how the model learns not to cry wolf.

### Campaigns

Similar texts are grouped by anonymized fingerprints (domain pattern, wording template hash, claimed brand, category) plus nemotron-3.5-embed-1b similarity. No message text is stored. The match threshold was set on validation data only.

### Stack

| Layer | What we used |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, SQLite, a background job runner, polling |
| Models | Nemotron 3.5 Bolt E4B, nemotron-3.5-embed-1b, scikit-learn classifier, DeepSeek for data, Gemini for cited search |
| Bank data | Capital One Nessie API |
| Frontend | React, TypeScript, Tailwind, phone-framed UI built for an older, stressed user |
| Reliability | Record and replay cache for every outside call, so the demo runs with Wi-Fi off |
| Quality | GitHub Actions CI, more than 500 automated tests |

### How two people shipped this in a weekend

```
             docs: plan · data contracts · 37+ GitHub issues
                                │
     ┌──────────────┬───────────┼────────────┬───────────────┐
     ▼              ▼           ▼            ▼               ▼
 Claude Code    Claude Code   Codex        Codex          Cursor
 (Arnav)        (Lavanya)     connections  design         cloud agents
 data, tests,   core infra,   Nemotron,    frontend       backend, CI,
 POCs, merges   agent, API    HF, classif. design lab     Nessie tools
     │              │           │            │               │
     └──────────────┴─── one git worktree per agent ─────────┘
                                │
                    CHANGELOG.md handoff log
          (claim → checkpoint → finish → anyone can resume)
```

## Challenges we ran into

**Grading ourselves on our own data.** Synthetic data flatters you. Our first classifier beat the baseline on our generated test set, then lost on real public texts (F1 0.53 vs 0.59). We didn't tune on the test set to hide it. We split a public SMS dataset in half, trained on one half, and didn't touch the other until the final score.

**Nessie's quirks.** Every one of these broke something before we found it:

| What happened | What we did |
| --- | --- |
| Plain `http` returned 502 | Switched to `https` |
| Empty lists came back as 404 errors | Treat "No … found" 404s as empty lists |
| Cents silently dropped, so the seed kept duplicating purchases | Whole-dollar amounts in the seed |
| No way to delete a purchase | Seeded a fresh customer instead of cleaning up |
| Transfers can't name who received the money | Modeled the $900 as a purchase at a new merchant, "Unknown Payee" |

**Gemini quotas.** We built the public report tool to return cited sources only, but the API returned rate limits and a missing model during testing. We left it off for the demo rather than show anything uncited.

**Running a local model.** We tried running Bolt on our own RTX 4060. It passed 3 of 5 tool-calling tests, so we stayed on the hosted endpoint.

**Coordinating five agents.** Two of our coding tools hit usage limits mid-build, and parallel branches kept colliding on the same files. The handoff log is the only reason the work didn't stall.

## Accomplishments that we're proud of

**Accuracy, measured honestly.** Held-out test set of 388 texts, after redaction:

| Category | Baseline F1 | SentinelAI F1 |
| --- | --- | --- |
| Bank impersonation | 0.62 | 0.69 |
| Billing scam | 0.79 | 0.89 |
| Delivery scam | 0.94 | 0.98 |
| Account security | 0.72 | 0.84 |
| Toll and government | 0.87 | 0.91 |
| Prize and refund | 0.84 | 0.92 |
| Job offer | 0.81 | 0.95 |
| "Wrong number" lure | 0.71 | 0.80 |
| Legitimate | 0.83 | 0.90 |
| **Macro F1** | **0.79** | **0.875** |
| **False alarm rate** | **16%** | **8%** |

And on 2,787 real public texts the model never trained on:

| | Baseline | SentinelAI |
| --- | --- | --- |
| Spam caught | 19% | 77% |
| False alarms | 3.3% | 0.12% |

For reference, macro F1 averages the per-category F1 scores, so small categories count as much as big ones:

$$\text{Macro F1} = \frac{1}{K}\sum_{k=1}^{K} \frac{2 P_k R_k}{P_k + R_k}$$

**Beyond the numbers:**

- The agent visibly plans differently for different messages, and re-plans when Linda says she clicked.
- Recovery mode catches the $900 inside the 17-minute window and asks before doing anything.
- Privacy you can see on screen, not just a promise in a README.
- Native tool calling passed 5 of 5 on our reliability gate.

## What we learned

A small, fast model with tight tool contracts beat our instinct to reach for a bigger one. Three-second steps are what make the live trail feel alive.

Honest evaluation is more work than building the model. The real public set caught a problem our own data hid, and fixing it properly taught us more than the first good number did.

Wording is a feature. "We found no unusual activity in the last 7 days" is true. "Your account is fine" isn't something we can know.

And AI coding agents need handoff notes just like people do.

## What's next for Scam-AI

```
 today                                   next
 ─────                                   ────
 hosted Bolt E4B          ──────────►    on-device check, text never leaves the phone
 standalone web demo      ──────────►    inside T-Life, next to Scam Shield
 Nessie only              ──────────►    PaySim, Sparkov, IBM AML, card processor, telecom
                                         billing (field maps already written)
 text-only signals        ──────────►    SIM swaps and port-outs feeding the same agent
 Gemini off (quota)       ──────────►    cited public reports back on
```

- **Run it on the phone.** Bolt E4B is small enough that the check could happen on the device.
- **Live inside T-Life,** catching the messages that get past network filters.
- **More payment systems.** Adding one is a new mapping file, not new code. The six maps exist; wiring them into the live tools is the next step.
- **Carrier signals.** A scam text followed by a SIM change should be caught as one story.
- **Cited public reports** back on once the Gemini quota is sorted.
