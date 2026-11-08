# Datasheet: SentinelAI synthetic SMS dataset (A21)

T-Mobile provided no message set, so we generated one. This page says exactly how, so anyone can judge the numbers we report on it.

## What's here

| File | What it is |
| --- | --- |
| `messages.jsonl` | Every generated message, one `Message` (contracts.py) per line: `message_id`, `text`, `sender`, `received_at`, `is_scam`, `category`, `source` (`generated`), `prompt_set` (`train_v1` or `test_v1`) |
| `handwritten.jsonl` | Hand-written test messages, same format, `source` and `prompt_set` = `handwritten` |
| `meta.jsonl` | How each generated message was made: `job_id`, `subtype`, `brand`, `persona`, `style`, `hard_negative` |
| `quality_report.json` | Counts at every pipeline step, per category, per set, plus the settings used |
| `cache/` | Every DeepSeek response, keyed by a SHA-256 of the request. Rebuilds are free and exact |

Categories are the ids in `data/taxonomy.json` (v1).

## How to rebuild

From `backend/`:

```powershell
..\.venv\Scripts\python -m scripts.generate_dataset --offline   # from the committed cache, no key needed
..\.venv\Scripts\python -m scripts.generate_dataset --dry-run   # plan and cache hits
..\.venv\Scripts\python -m scripts.generate_dataset             # calls DeepSeek only on cache misses
```

`tests/test_generate_dataset.py` checks that the offline rebuild reproduces `messages.jsonl` line for line.

## How it was made

1. **Taxonomy.** T-Mobile shared none, so we wrote ours from common US smishing types: 8 scam categories plus `legit`. Each category has subtypes that steer generation; `legit` subtypes mirror every scam category (real bank alerts, carrier bills, one-time codes, delivery updates, toll statements, store promos, recruiters, personal texts) so the hard look-alikes are covered.
2. **Generator.** DeepSeek (`deepseek-flash`, OpenAI-compatible API), temperature 1.2, JSON output, 8 messages per call. Each call is a job: category, subtype, brand, persona, style, chosen with a seeded RNG (seed 2026) that depends only on the job's index, so the plan is deterministic.
3. **Two prompt sets that share nothing but the taxonomy** (`backend/scripts/dataset_prompts.py`):
   - `train_v1` (feeds train and validation): "write training data for a scam classifier"; varies the *writer* (fraud ring copying templates, hurried spammer, non-native English, ...); its own style list and brands.
   - `test_v1` (feeds test only): "quiz cards for a fraud-awareness class"; varies the *recipient* (retiree, student, nurse, ...); its own tone list; adds brands train never saw (for example Truist, Spectrum, OnTrac, Coinbase, FasTrak).
4. **Safety rewrite.** Any phone number outside the fictional 555-01XX range is rewritten into it, so no model-invented number can be real. Senders are assigned by code, not the model.
5. **Quality filter.** Drops messages under 20 or over 480 characters, refusals, template placeholders (`[Name]`, `{link}`), and scam messages that name themselves (`scam`, `phishing`, `smishing`, `fraudster`).
6. **Dedupe.** Text is normalized (lowercase, URLs to `url`, digits to `0`, punctuation removed). Exact repeats are dropped, then near-duplicates (rapidfuzz ratio ≥ 90) across all categories in a set. Then every `test_v1` message within ratio 85 of any `train_v1` message is dropped, so test never contains a paraphrase of train.
7. **Trim.** Each category is cut to a fixed target with a seeded sample, so class balance doesn't depend on how many duplicates a batch had.
8. **Senders and times.** Synthetic, assigned by rule from the message id. Long codes are `+155501xxxxx`, short codes are random 5–6 digits, emails are random 12-character tokens. The scam and legit distributions overlap on purpose (scam: about 65% long code, 20% short code, 15% email; brand legit: 80% short code, 20% long code; personal legit: 75% long code, 25% short code), but they're still a rule we made up. **Don't read anything into sender-type features scored on this set.** Times are spread over 2026-09-01 to 2026-11-06, 7 AM to 10 PM Central.
9. **Hand-written set.** 50 test-only messages written outside the generator, drafted by Claude Code (not DeepSeek) and approved by Arnav on 2026-11-07: shorter and messier than DeepSeek's output, with deliberate look-alike pairs (a real Chase YES/NO fraud check vs. a fake Zelle "reply Y or N"; a real "new number" text from a coworker vs. a fake "Mom, new number").

## Splits (for A1)

DATA_SPEC section 2 calls for 70/15/15, stratified by category, fixed seed, with test from a separate prompt set.

- **Train + validation** = `prompt_set == "train_v1"`. A1 splits it about 82/18 stratified by category, which is 70/15 of the whole.
- **Test** = `prompt_set == "test_v1"` plus `handwritten.jsonl`. Never used for training, tuning, blocklists, campaign seeds or prompts.

A1 saved the split as message ids in `splits.json` (train 1,818, val 390, test 388; seed 42). Load it with `app.classifier.baseline.load_split()` so everyone scores on the same test set.

## Counts

Full numbers are in `quality_report.json`. Summary:

| | `train_v1` (train + val) | `test_v1` (test) | Hand-written (test) | Total |
| --- | --- | --- | --- | --- |
| DeepSeek calls | 361 | 62 | | 423 |
| Raw messages | 2,889 | 496 | | |
| Failed quality | 4 (3 placeholder, 1 label leak) | 0 | | |
| Exact / near duplicates | 57 / 2 | 0 / 0 | | |
| Test too close to train | | 0 | | |
| Trimmed to target | 618 | 158 | | |
| **Final** | **2,208** | **338** | **50** | **2,596** |
| Per scam category | 171 each | 26 each | 3–4 each | 200–201 each |
| `legit` | 840 (38%) | 130 (38.5%) | 20 (40%) | 990 (38.1%) |
| Hard legit look-alikes | 705 | 111 | not tagged | |
| Median length (chars) | 139 | 163 | 119 | 141 |

The test split is 388 messages (338 + 50), 15% of the total. No phone number needed rewriting: DeepSeek kept to 555-01XX every time.

The 57 exact duplicates mostly come from 7 jobs whose seeded choices happened to match another job's (same subtype, brand, persona and style). Identical requests share one cache entry, so they returned identical batches, which dedupe removed. The targets were still met.

## Known limits

- **Everything is synthetic.** Scores here say how well a model separates DeepSeek's idea of scams from DeepSeek's idea of real texts. That's why A13 also scores the public real SMS set (A5).
- **One generator.** The test prompt set changes framing, personas, tone and brands, but it's the same model. The hand-written set is the only test data from outside it.
- **Labels come from the prompt, not a human.** The quality filter catches broken output, not mislabeled output. Some scam messages are deliberately subtle (a callback number and nothing else), and a few legit look-alikes may read as suspicious. We spot-checked samples by hand; we didn't label-audit every row.
- **Senders and timestamps are made up by rule** (step 8).
- **US English only**, brands mostly US.

## Privacy

All synthetic. No real person's data: names are invented, phone numbers are in the fictional 555-01XX range, emails are random tokens, and addresses are generic. DeepSeek was used only offline to write this data. It never saw a customer message.


## L7 follow-up: separate public SMS extension

The synthetic files, counts and A1 split above are unchanged. Arnav later
authorized binary classifier development on a saved 50% half of the cached
public SMS dataset, with an internal validation slice. The other 50% is held
out from that follow-up. Public data is not added to these generated files
and supplies no synthetic scam-category labels. See
[the public extension datasheet](../PUBLIC_SMS_DATASHEET.md) and
`data/public_sms_splits.json` for exact IDs, seed, counts, duplicate grouping,
prior v1 evaluation exposure and the final comparison protocol.


Frozen L7 follow-up: synthetic macro F1/FPR **0.8751/0.0800** (v1
0.8781/0.1133). Same saved public holdout: binary F1 **0.9257** (v1 0.5193),
spam recall **0.7748** (v1 0.0751), FPR **0.0012** (v1 0.0282). These public
numbers use 2,787 held-out rows after developing on the other half; they are
not the historical 5,574-row full-public external test. The public dataset
had prior v1 evaluation exposure. See the extension datasheet for limitations.
