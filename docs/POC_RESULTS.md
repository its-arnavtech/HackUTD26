# POC results: gates P1 to P5

Issue A8 (#14). Gates and pivots are defined in [POC_MVP.md](POC_MVP.md) section 3. Rerun by Claude Code on 2026-11-07 at about 20:25 Central, on branch `arnav-shared`.

| Gate | Question | Status | Result | Pivot |
| --- | --- | --- | --- | --- |
| P1 | Usable dataset and a baseline score? | **Pass** | Dataset QC passes; baseline test macro F1 **0.807**, FPR **0.127** | None (macro F1 < 0.97) |
| P2 | Does Nemotron call our tools reliably? | **Pass** | **5/5** native tool calls with schema-valid answers; median step 2,635 ms, worst 4,161 ms | None (native protocol) |
| P3 | Does Gemini grounded search return cited sources? | **Pending** | Not run: the Gemini key arrives Sunday morning (L4, Lavanya) | If it fails: Gemini becomes cut item 2 |
| P4 | Can we seed and read Nessie? | **Pass** | 3rd live run at about 21:40: seed `Created 33`, then `Created 0`, and everything reads back. Scenario 2 finds the planted $900 17 minutes after the message; scenario 3 finds the bill paid 2026-11-01 | Partial: live transfers can't name a payee, so the planted $900 is a purchase at merchant "Unknown Payee" (fallback chosen by Arnav) |
| P5 | Does redaction work? | **Pass** | **20/20** hand-written gate strings; 50/50 redaction tests | None |

**G1 (2026-11-07, about 23:20):** scenario 1 runs end to end in the CLI with L8's real agent against live Nemotron and Nessie: pass. Scenario 2 flags the $900 but doesn't return it as "Was this you?" yet (L11). Details in the G1 section at the end.

**POC exit:** four of five gates pass (P1, P2, P4, P5). P3 is pending on the Gemini key. P4 passed on its third live run, with one partial pivot: live Nessie transfers can't name a payee, so the planted $900 is a purchase at merchant "Unknown Payee". No pivot has been taken.

## P1: dataset and baseline (A21, A1)

- **Dataset** (`data/generated/`, datasheet in its `README.md`): 2,596 synthetic messages. Train and validation come from prompt set `train_v1` (2,208). Test is the separate prompt set `test_v1` (338) plus 50 hand-written messages Arnav approved. 38% are legit, with hard look-alikes. `python -m scripts.generate_dataset --offline` rebuilds it from the committed DeepSeek cache with 0 shortfall and 0 hand-written problems.
- **Saved split** (`data/generated/splits.json`, seed 42): train 1,818 / validation 390 / test 388.
- **Baseline** (keyword rules + TF-IDF + logistic regression, fit on train only, no tuning), scored once on test (`eval/baseline_metrics.json`):

| Category | F1 |
| --- | --- |
| `bank_impersonation` | 0.64 |
| `billing_scam` | 0.77 |
| `delivery_scam` | 0.95 |
| `account_security` | 0.75 |
| `toll_government` | 0.90 |
| `prize_refund` | 0.88 |
| `job_offer` | 0.82 |
| `conversation_lure` | 0.70 |
| `legit` | 0.85 |
| **Macro F1** | **0.807** |
| **FPR** (legit flagged as scam) | **0.127** |

Validation scores 0.898 / 0.054, so the separate test prompt set is clearly harder. That's the point: test doesn't share the generator's training style.

**Also from A13** (`eval/metrics.json`, the accuracy page's data):
- **On redacted text**, which the classifier sees in production, the baseline scores macro F1 0.791, FPR 0.160. Redaction costs 0.016 macro F1, mostly because brand names get tagged as `<PERSON>` (CHANGELOG Decisions 20:20).
- **On the public real SMS set** (`ucirvine/sms_spam`, 5,574 messages), it catches 17.7% of spam at an FPR of 3.4%. That set is mostly 2012 UK premium-rate spam, outside our US smishing taxonomy.

```powershell
cd backend
..\.venv\Scripts\python -m scripts.generate_dataset --offline
..\.venv\Scripts\python -m scripts.run_baseline
```

## P2: Nemotron tool calling (A4)

`nvidia/nemotron-3.5-bolt-e4b` on the hosted NVIDIA endpoint, native protocol. It handles five fixed, already-redacted synthetic inputs with two dummy tools. It passed **5/5**: every case made native tool calls and returned a final answer that validates against `AgentResult`. Median model step 2,635 ms, worst 4,161 ms. A4's own run at 19:07 also scored 5/5 native (median 3,082 ms). The JSON-action fallback scored 5/5 too and stays available through `NEMOTRON_PROTOCOL`.

```powershell
cd backend
..\.venv\Scripts\python -m scripts.smoke_nemotron --protocol native
```

## P3: Gemini grounded search (L4): pending

The Gemini key arrives Sunday morning, and L4 (Lavanya) runs the demo query then. **Pass test:** at least one source URL in the grounding metadata, in our JSON shape (DATA_SPEC section 4.3). **If it fails:** Gemini becomes the second item in the cut order (POC_MVP section 11). The `public_scam_reports` step then drops out of scenario 3's plan, and the result card says public reports weren't checked.

## P4: Nessie seed and read (A2): pass, third live run

**Result, 2026-11-07 at about 21:40.** Claude Code finished A2's live parts on Cursor's branches, at Arnav's request.
- **Transfer probe**, on a throwaway customer "Probe Throwaway" with two accounts, not Linda:
  - `POST /accounts/{id}/transfers` requires exactly `transaction_date`, `status`, `amount` and `description`;
  - all 18 receiver field names tried were rejected ("extra fields not permitted");
  - `/transfers` routes don't exist.
  - **So a transfer can't name a receiving account.** It took 1 minute of the 20-minute timebox.
- **Fallback taken.** The planted $900 is a purchase at a new merchant "Unknown Payee" on Linda's checking, 17 minutes after scenario 2's message, with its exact time kept in the manifest (DATA_SPEC section 6).
- **Duplicates:** Nessie has no DELETE for purchases, so the seed creates a fresh "Linda Sentinel" at 802 Demo Way. The customer at 800 Demo Way keeps the duplicates and is abandoned.
- **Seed** (PR #44, `02aae13`): run 1 `Created 33, already present 5`; run 2 `Created 0, already present 38`. `data/nessie_seed.json` is committed on PR #44's branch.
- **Read back with A11's tools** (PR #45, `649f690`), against live Nessie and that manifest:

| Scenario | Tool | Live result |
| --- | --- | --- |
| 1, check, 7 days | `nessie_recent_activity` | 2 accounts, 6 items, nothing flagged |
| 2, recovery | `nessie_recent_activity` | 1 item: `txn_28`, $900 purchase, 17 minutes after, "first purchase at this merchant, 23.1x the 30-day median"; app resolves it to "Unknown Payee" |
| 3 | `nessie_bill_status` (T-Mobile) | found, completed, paid 2026-11-01, $0 due |

- **Tests:** PR #44's branch 338 passed; PR #45's branch 351 passed. The fake Nessie now rejects extra transfer fields (400) and DELETE (403), like live.

### History: the first two live runs

Cursor built the client and the idempotent seed in [PR #44](https://github.com/its-arnavtech/HackUTD26/pull/44), in review. Claude Code ran it live on 2026-11-07 at about 20:25, using Arnav's key, from a temporary checkout of PR #44's branch (`9b69d5b`). It ran the dry run plus read-only inventory scripts only, so it created nothing and deleted nothing.

**What Nessie already holds**, from at least one earlier run:
- both customers (Linda and Unknown Payee), all 3 accounts, all 5 merchants, and the completed T-Mobile bill all read back correctly;
- **no transfers**, so the planted $900 transfer is missing;
- **48 purchases where 24 are planned**: every planned purchase exists exactly twice.

**The two bugs, both in A2's code:**
1. **Empty lists come back as 404.** Nessie answers `GET /accounts/{id}/transfers` with HTTP 404 `"No transfers found for this account"` when there are none. `NessieClient._get_list` raises on it, so the seed (and the dry run) stops at the first transfer lookup. Fix: treat a 404 whose body says "No … found" on a list GET as `[]`.
2. **Nessie stores purchase amounts as whole dollars.** For example, $49.30 is stored as `49`. The seed matches existing purchases on `(description, date, amount)` with cents, so it never finds them and creates them again on every run. Fix: use whole-dollar amounts in `purchase_plan()` (the transfers already are), or match on `int(amount)`. Then delete the 24 duplicate purchases (`DELETE /purchases/{id}`).

**Second live run, 2026-11-07 at about 20:43**, on PR #44 at `f07cf08`, which fixes both bugs above and adds `--dedupe`. Steps:
- **Preview** (`--dry-run --dedupe`): works now. It found 35 objects already present (2 customers, 3 accounts, 5 merchants, 24 purchases, 1 bill), 24 duplicate purchases to delete, and only the 4 transfers to create. That's exactly as expected.
- **Live run** (`--dedupe`): stopped at the first write. `DELETE /purchases/{id}` answered **HTTP 403 `{"message":"Missing Authentication Token"}`**. That's Amazon's API gateway reply for a route that doesn't exist, so purchases probably can't be deleted at that path.
- **Plain seed:** stopped at the first transfer. `POST /accounts/{id}/transfers` answered **HTTP 400**: `medium` and `payee_id` are "extra fields not permitted". The live transfer schema isn't the one A2 sends, and without a payee field the planted $900 transfer can't name the unknown account.

A final `--dry-run --dedupe` listed exactly the same 24 and 4, so **nothing in Nessie changed**, and no `data/nessie_seed.json` was written. Nessie's API description isn't public (`/openapi.json` returns 403), so the right transfer fields need Nessie's docs or a careful probe. That's handed back to Cursor on PR #44.

**To rerun**, with the key in `.env`, on PR #44's branch:

```powershell
cd backend
..\.venv\Scripts\python -m scripts.seed_nessie --dry-run  # after the live seed: "Would create 0"
..\.venv\Scripts\python -m scripts.seed_nessie            # must print "Created 0"
```

## P5: redaction (A3)

`app/privacy/redact.py` (Codex) passes all **20** hand-written gate strings, which cover names, phone numbers, account digits, addresses and emails. All 50 redaction tests pass. **Known limits:**
- Names and addresses are matched by regex heuristics, not a named-entity model.
- It over-redacts some brand and place names as `<PERSON>`. That costs 0.016 macro F1 (P1 above) but never leaks personal data.

```powershell
cd backend
..\.venv\Scripts\python -m pytest -q tests/test_redact.py
```

## G1: scenarios end to end with the real agent (L8)

**Result, 2026-11-07 at about 23:20 Central**, Claude Code on branch `g1-gate`. `scripts/run_scenario.py` now runs L8's `run_agent` (`AGENT = run_agent`). All three scenarios ran with `DEMO_MODE=live` against hosted Nemotron (`nvidia/nemotron-3.5-bolt-e4b`, native protocol) and live Nessie. Redaction, sender redaction, URL features, message features and claimed brand are real; the classifier is still A1's baseline (L7 not merged). Scenario 2 was run three times with the same plan and result each time.

| Scenario | Plan (Nemotron's) | Key findings | Verdict | Actions | "Was this you?" |
| --- | --- | --- | --- | --- | --- |
| 1, check | check_link, check_sender, nessie_recent_activity, match_campaign | link imitates an official site; sender not an official channel; nothing flagged in 6 items; no campaign match | **likely scam**, likely | block_sender, report_spam | none (check mode) |
| 2, recovery | check_sender, check_link, nessie_recent_activity, then re-plan: match_campaign, public_scam_reports | `nessie_recent_activity` flags `txn_28`: the planted **$900 purchase at "Unknown Payee"**, 17 minutes after the message, "first purchase at this merchant, 23.1x the 30-day median"; public_scam_reports "not available yet" (L10) | **likely scam**, likely | block_sender, report_spam, ignore | **none: `txn_28` is not returned** |
| 3, check | check_sender, check_link, nessie_bill_status | link imitates an official site; T-Mobile's channels aren't known; **bill paid 2026-11-01, $0 due now** | **likely scam**, very likely | block_sender, report_spam, ignore | none (check mode) |

**What the gate checks:**
- **G1 acceptance (scenario 1 in the CLI with a schema-valid verdict, baseline classifier): pass.**
- **Plans differ between scenarios: pass.** Nemotron chose each plan itself; none matches the scenario file's `expected_plan` exactly (it adds checks, for example `match_campaign` in scenario 1).
- **Scenario 1 says "likely scam": pass.**
- **Scenario 3 finds the paid bill: pass**, and the reason uses it ("the customer's bill status shows no amount due").
- **Scenario 2 flags the $900 at Unknown Payee: partial.** The tool finds it and the trail shows it, and the reason mentions it, but the result's `was_this_you` is empty, so the app shows no "Was this you?" card. L8 leaves recovery refs to L11 ("refs come only from recovery (L11)"), and L11's acceptance criteria cover exactly this.

**Gaps for L8 and L11 (not changed here):**
- **Recovery result (L11):** in recovery mode, put the refs that `nessie_recent_activity` flagged into `was_this_you` in code, not from the model, and use recovery actions (freeze card, call the number on the card, change password) instead of block, report and ignore.
- **Actions (L8 guardrails):** scenarios 2 and 3 return `ignore` next to `block_sender` and `report_spam` for a likely scam. A guardrail could drop `ignore` when the verdict is `likely_scam`.

**Tests:** `tests/test_run_scenario.py` now pins the stand-in agent, so the suite never calls Nemotron (545 passed, 30 skipped). A18's synthetic-world scenario tests skip once the agent is real, as designed; they return in the recorded world after A19 records fixtures.

```powershell
cd backend
..\.venv\Scripts\python -m scripts.run_scenario 1
..\.venv\Scripts\python -m scripts.run_scenario 2
..\.venv\Scripts\python -m scripts.run_scenario 3
```
