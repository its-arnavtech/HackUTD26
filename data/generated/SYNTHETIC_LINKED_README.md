# Datasheet: synthetic linked scenarios

**synthetic only — not real customer data**

This page describes the files added beside the A21 message set. It does not replace `data/generated/README.md` (that file is the A21 datasheet and was left in place).

## Purpose

Public SMS sets are binary or three-class, and none of them ties a text to a click and then to account activity. These files fill that gap so a Nemotron-style checker can be scored on:

- a 9-way taxonomy label
- campaign variants of one lure
- link technique and a synthetic RDAP record
- a 30–60 day canonical baseline plus the events after the text
- carrier events (SIM, port-out, eSIM, plan, device, bill amount, autopay)

The agent-facing signals, each present in some scenarios and absent in others, are: a new payee, an amount far from the baseline, a channel never used before, a bill paid to a biller that is not on the account, a new device or SIM change near a payment, and timing within three hours of the message.

## How it was made

| | |
| --- | --- |
| Generator | `backend/scripts/gen_linked_scenarios.py` (`python -m scripts.gen_linked_scenarios` from `backend/`) |
| Seed | `20261108` |
| Model | none (deterministic seeded templates, no LLM API) |
| Prompt path requested | `scripts/gen_linked_scenarios.py`. This repo keeps Python generators in `backend/scripts/` so they run as modules. |

Rebuild is exact: the script does not call a network or a model. `tests/test_synthetic_linked.py` rebuilds the blobs and compares them to the committed files.

## Template sets

Train and validation come from template set **A**. Test comes from template set **B**. The sets do not share a template id, a template skeleton, a URL, or a sender value. Validation may reuse set A templates; it is not a third prompt set. The split inside each category is 140 train / 30 validation / 30 test (70/15/15 of 200).

Campaigns are seeded only from set A wording and from senders and domains that are not in the multiclass file, so they are not a back door into the test split. The held-out test split of `messages_multiclass.jsonl` must not be used to train, tune, build blocklists, or seed campaigns.

## Counts

| Split | Messages |
| --- | --- |
| train | 1260 |
| validation | 270 |
| test | 270 |
| template set A | 1530 |
| template set B | 270 |
| all messages | 1800 |

| Taxonomy id | Messages |
| --- | --- |
| `bank_impersonation` | 200 |
| `billing_scam` | 200 |
| `delivery_scam` | 200 |
| `account_security` | 200 |
| `toll_government` | 200 |
| `prize_refund` | 200 |
| `job_offer` | 200 |
| `conversation_lure` | 200 |
| `legit` | 200 |

Legitimate subtypes (hard look-alikes included):

| Subtype | Messages |
| --- | --- |
| `bank_posted` | 7 |
| `bank_yes_no` | 21 |
| `carrier_autopay` | 22 |
| `carrier_bill` | 30 |
| `delivery` | 28 |
| `delivery_shipped` | 21 |
| `otp` | 29 |
| `otp_warning` | 21 |
| `toll_statement` | 21 |

| Other file | Count |
| --- | --- |
| Campaigns | 32 (315 variants, 5–15 each) |
| URLs | 422 |
| Linked scenarios | 320 (192 fraud, 128 benign, benign share 0.4) |
| Telecom events | 1032 |
| Nessie exports | one JSON file per scenario under `nessie_export/` |

Telecom event types:

| event_type | Count |
| --- | --- |
| `autopay_change` | 160 |
| `bill_amount_change` | 320 |
| `device_add` | 200 |
| `esim_transfer` | 11 |
| `plan_change` | 320 |
| `port_out_request` | 11 |
| `sim_change` | 10 |

Signal coverage (`name:true/false` is the number of scenarios):

| Signal | Scenarios |
| --- | --- |
| `amount_far_from_baseline:False` | 160 |
| `amount_far_from_baseline:True` | 160 |
| `bill_nonmatching_biller:False` | 264 |
| `bill_nonmatching_biller:True` | 56 |
| `channel_never_used:False` | 192 |
| `channel_never_used:True` | 128 |
| `new_device_or_sim_near_payment:False` | 280 |
| `new_device_or_sim_near_payment:True` | 40 |
| `new_payee:False` | 140 |
| `new_payee:True` | 180 |
| `timing_near_message:False` | 78 |
| `timing_near_message:True` | 242 |

## Files

| File | What it is |
| --- | --- |
| `payment_schema.json` | JSON Schema for a canonical event |
| `schema_mappings/*.yaml` | Field maps for Nessie, PaySim, Sparkov, IBM AML, a generic card processor, and telecom billing |
| `messages_multiclass.jsonl` | One DATA_SPEC 3.1 message per line, plus `taxonomy_id`, `template_set`, `template_id`, `template_skeleton`, `split`, `subtype`, `source_url`, `is_scam` |
| `campaigns.jsonl` | One variant per line |
| `urls.jsonl` | `url`, `domain`, `label`, `technique`, `rdap` |
| `linked_scenarios.jsonl` | Message, optional click, customer, baseline events, post events, ground truth |
| `telecom_events.jsonl` | Canonical events whose type is a carrier code |
| `nessie_export/` | Customers, accounts, purchases, transfers, bills, merchants |

`source_url`, template ids, split, and `ground_truth` are supervision. They are not a Nemotron payload. Nemotron still receives only DATA_SPEC section 3. The `labels` object on an event is synthetic supervision and is never shown to a model.

## Mapping layer

`backend/app/adapters/mapping_loader.py` loads one YAML file by name (`load_mapping("paysim")`, `configure("nessie")`). A new source system is a new file, not a code change.

The brief's mapping table did not include a generic card processor. `generic_card_processor.yaml` is a card-auth layout (token, MCC, amount in cents, entry mode) so that column of the deliverable still has a file.

| canonical | Nessie | PaySim | Sparkov | IBM AML | telecom billing | generic card processor |
| --- | --- | --- | --- | --- | --- | --- |
| event_type | object type | type | purchase | Payment Format | event code | txn type |
| timestamp | purchase_date / transaction_date / payment_date | step hour offset | trans_date_trans_time | Timestamp | event_time | authorization_time |
| account_id | payer_id / account id | nameOrig | cc_num | Account | msisdn / account_no | card token |
| counterparty | merchant_id / payee_id | nameDest | merchant | Account.1 | biller / dealer | merchant id |
| amount_minor | amount × 100 | amount × 100 | amt × 100 | Amount Paid × 100 | charge × 100 | amount_cents |
| currency | USD default | null → USD | USD | Payment Currency | bill currency | currency code |
| merchant_category | merchant.category | null | category | null | "carrier" | MCC |
| bill.status | bill.status | — | — | — | bill status | — |
| balance_after | account.balance × 100 | newbalanceOrig × 100 | — | — | — | — |
| device | — | — | — | — | imei / sim_iccid | — |
| labels.is_fraud | seeded | isFraud | is_fraud | Is Laundering | seeded | is_fraud |

## Signal definitions

Computed in the generator and stored on `ground_truth.signals`:

- `new_payee`: a post-message debit whose counterparty is first seen, or a `payee_added` event
- `amount_far_from_baseline`: a post-message debit at least 3× the median baseline debit
- `channel_never_used`: a post-message debit whose channel is absent from baseline debits
- `bill_nonmatching_biller`: a `bill_payment` whose payee is not Northline Mobile (the only biller on these customers)
- `new_device_or_sim_near_payment`: `sim_change`, `esim_transfer`, `port_out_request`, or `device_add` with `new_device` true, at most 60 minutes before a post-message debit
- `timing_near_message`: a post-message debit within 180 minutes after the text

Baseline debits use `card_present`, `bill_pay`, and `atm` only, so card-not-present, wire, ACH, and gift card are new channels when they appear after the text.

## Nessie export

Objects use the field names in DATA_SPEC section 6. Purchases are whole dollars because live Nessie drops cents (`amount_minor // 100`). Dates are `YYYY-MM-DD`. The exact UTC time is `manifest.purchase_times` / `manifest.transfer_times`, matching how `data/nessie_seed.json` keeps times. `manifest.links` joins each object back to `event_id`. Applying `schema_mappings/nessie.yaml` recovers the event type, the truncated amount, and the calendar date.

`carrier_account` is exported as Nessie type `Checking` with nickname "Mobile Account". Nessie has no carrier account type.

## RDAP stub

`urls.jsonl` `rdap` is `{found, registered_at, registrar}`. `found` and `registered_at` match what `app.integrations.rdap.lookup_registration` stores. `registrar` is extra and is not sent anywhere. Phishing dates are recent except for the synthetic shortener, which is old. Legitimate `.example` domains are dated 2014. Eight `missing-N.test` rows use `found: false`, the same shape as a 404 fixture.

## How this complements public sets

See `docs/PUBLIC_DATASETS.md`.

| Public set | What it already covers | What these files add |
| --- | --- | --- |
| UCI SMS Spam (`ucirvine/sms_spam`) | Real binary spam/ham | 9-way labels and hard legitimate look-alikes (bills, OTPs, delivery) |
| Mendeley SMS Phishing | Ham/spam/smishing plus URL flags | Taxonomy ids and a click joined to account events |
| PhiUSIIL / phishing-url | Phishing vs legit URLs | Lookalikes only on `.test`, with technique and an RDAP stub |
| PaySim / Sparkov / IBM AML | Payment rows in their own columns | A canonical event plus a YAML map, and a message that precedes the payment |

## Conflicts and choices

- Datasheet file name is `SYNTHETIC_LINKED_README.md` so the A21 `README.md` stays intact.
- `event_type` includes `esim_transfer`, `plan_change`, and `bill_amount_change`. The brief's enum table omitted them and the telecom deliverable requires them.
- Message `received_at` uses the Central offset from DATA_SPEC 3.1. Canonical events use UTC `Z` as the schema asks.
- Classifier scores are fixed placeholders so the 3.1 shape is populated. They are not the output of Nemotron, DeepSeek, or the trained classifier.
- Phone numbers are the reserved range 555-0100 through 555-0199 (E.164 `+155555501xx`). Long-code senders are stored as `<PHONE_HASH_…>` from a seeded SHA-256, never as the raw number. Short codes in the 56000–58499 and 57000+ bands are fictional and are not the Capital One codes in `data/brands.json`.
- Domains are `.test` or `.example` only. `lookalike_of` names the real site being imitated (for example `t-mobile.com`). That string is a label, not a link in the message.
- Some bank texts contain the word "fraud" because real fraud alerts do. The word "scam" is not used.
- Every customer is named from a five-surname toy list (Sample, Example, North, Demo, Placeholder). There is no real person in this set.
- Bill-pay to **Unknown Payee** is a `bill_payment` in the canonical events and a Nessie bill plus merchant, not a Nessie transfer. DATA_SPEC section 6 notes that live transfers cannot name a receiver and that the demo's planted $900 is a purchase at Unknown Payee. The canonical event still says bill payment, which is the story under test. The export does not pretend the live API stored a payee on a transfer.

## Known biases

- One author, one seed, English only. Test set B uses different sentences, brands, domains, and senders, but the same generator.
- Amounts, merchants, and city are a handful of slots. A model can memorize "Demo Grocery" as safe.
- The 70/15/15 split is balanced on purpose. Real inboxes are not 8/9 scam.
- Baseline spending is the same shape for every customer, so "far from baseline" is easy if the amount is $250 or more and hard to miss.
- Carrier events are scripted next to the payment in takeover scenarios. A real SIM swap is rarer and messier.
- `labels.is_fraud` on an event is the answer key. Training or prompting on it would leak the label.

## Privacy

synthetic only — not real customer data

No customer of any bank or carrier is described here. Names, numbers, and domains are reserved or invented. Nothing in this folder was retrieved from Nessie, RDAP, or a model.
