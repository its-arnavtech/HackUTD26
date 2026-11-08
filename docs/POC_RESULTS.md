# POC results: gates P1 to P5

Issue A8 (#14). Gates and pivots are defined in [POC_MVP.md](POC_MVP.md) section 3. Rerun by Claude Code on 2026-11-07 at about 20:25 Central, on branch `arnav-shared`.

| Gate | Question | Status | Result | Pivot |
| --- | --- | --- | --- | --- |
| P1 | Usable dataset and a baseline score? | **Pass** | Dataset QC passes; baseline test macro F1 **0.807**, FPR **0.127** | None (macro F1 < 0.97) |
| P2 | Does Nemotron call our tools reliably? | **Pass** | **5/5** native tool calls with schema-valid answers; median step 2,635 ms, worst 4,161 ms | None (native protocol) |
| P3 | Does Gemini grounded search return cited sources? | **Pending** | Not run: the Gemini key arrives Sunday morning (L4, Lavanya) | If it fails: Gemini becomes cut item 2 |
| P4 | Can we seed and read Nessie? | **Pending** | A2 is in review ([PR #44](https://github.com/its-arnavtech/HackUTD26/pull/44)). The live seed and its idempotency rerun haven't run, because Cursor's cloud agent has no Nessie key | If it fails: local fixture mirroring Nessie's schema, served through the replay cache |
| P5 | Does redaction work? | **Pass** | **20/20** hand-written gate strings; 50/50 redaction tests | None |

**POC exit:** three of five gates pass (P1, P2, P5). P3 and P4 are pending on keys, not on code, and each has its pivot ready. Nothing failed, so no pivot has been taken.

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

## P4: Nessie seed and read (A2): pending

Cursor built the client and the idempotent seed in [PR #44](https://github.com/its-arnavtech/HackUTD26/pull/44), in review. The live part of the gate hasn't run, because Cursor's cloud agent has no `NESSIE_API_KEY`. It needs to create Linda, her accounts and purchases, the paid T-Mobile bill, and the unknown payee with the $900 transfer. It then reads them back and reruns to confirm nothing new is created. **To run it** with the key in `.env`, on PR #44's branch:

```powershell
cd backend
..\.venv\Scripts\python -m scripts.seed_nessie   # first run creates; the second must create nothing
..\.venv\Scripts\python -m scripts.seed_nessie
```

**If it fails:** use a local fixture that mirrors Nessie's schema (DATA_SPEC section 6), served through the replay cache.

## P5: redaction (A3)

`app/privacy/redact.py` (Codex) passes all **20** hand-written gate strings, which cover names, phone numbers, account digits, addresses and emails. All 50 redaction tests pass. **Known limits:**
- Names and addresses are matched by regex heuristics, not a named-entity model.
- It over-redacts some brand and place names as `<PERSON>`. That costs 0.016 macro F1 (P1 above) but never leaks personal data.

```powershell
cd backend
..\.venv\Scripts\python -m pytest -q tests/test_redact.py
```
