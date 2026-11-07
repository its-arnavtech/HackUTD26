# SentinelAI: Data Spec (what Nemotron and Gemini see)

Companion to [POC_MVP.md](POC_MVP.md). This file defines every data contract between modules. `backend/app/contracts.py` and `frontend/src/types.ts` must match it.

## 1. Summary

Nemotron never sees the raw text message or any raw bank record. It sees a redacted message, the classifier's output, and short summaries returned by each tool. Gemini sees even less: the claimed brand, the scam category, the link's domain, and a generic lure phrase.

| Component | What it receives | What it never receives |
| --- | --- | --- |
| Classifier (local) | Redacted message text and extracted features | Names, phone numbers, account digits, addresses, emails |
| Nemotron agent | Redacted text, extracted features, classifier scores, tool summaries | Raw message, customer name, full transaction history, account numbers |
| Nessie tools (local code) | The demo customer's ID and a time window or payee name | Message text |
| Gemini lookup | Brand, scam category, link domain, a generic lure phrase from our list | Anything else from the message, and any bank data |

All data is synthetic or public: our generated message set, a public SMS spam set, and Capital One's Nessie mock banking data.

## 2. Data sources

| Source | Provided by | What we use | How we use it |
| --- | --- | --- | --- |
| Generated message set | Us (DeepSeek, issue A21) | Message text, sender, scam/legit label, category | Train and test the classifier; replay as the demo inbox |
| Public SMS spam set | Public dataset via Hugging Face (A5) | Real messages labeled spam or legitimate | Second test set: spam recall and false positives on real text |
| Taxonomy | `data/taxonomy.json` (T-Mobile's if they share one) | The fixed list of categories | The only categories the classifier and Nemotron may output |
| Baseline | Us (A1) | Keyword rules plus TF-IDF and logistic regression | The score to beat, per category |
| Nessie mock bank | Capital One | Accounts, purchases, transfers, bills, merchants | Verify the scam's claim; find activity after a click |
| Campaign store | Us | Anonymized fingerprints | Group similar messages into campaigns |

Split: 70/15/15 train, validation and test, stratified by category, fixed seed. The test split is generated from a separate prompt set and includes the hand-written messages. It is never used for training, tuning, building blocklists or campaign seeds, or writing prompts. DeepSeek is used only to generate training and test data offline; it never sees a customer message. **Category names in the examples below are placeholders: use the labels in `data/taxonomy.json`.**

## 3. Nemotron

### 3.1 Input for each message

```json
{
  "message_id": "msg_0142",
  "mode": "check",
  "received_at": "2026-11-08T09:14:00-06:00",
  "sender": {
    "type": "long_code",
    "value": "<PHONE_HASH_7f3a>",
    "claimed_brand": "Capital One"
  },
  "text_redacted": "Capital One Alert: unusual sign-in for <PERSON>. Your account will be locked in 2 hours. Verify now: <URL_1>",
  "urls": [{
    "id": "URL_1",
    "registered_domain": "capone-verify-alert.com",
    "is_shortener": false,
    "brand_term_in_domain": "capone",
    "is_official_brand_domain": false
  }],
  "features": {
    "urgency_deadline": "2 hours",
    "threat": "account_lock",
    "requested_action": "click_link_and_verify",
    "asks_for": ["login"],
    "money_amount_claimed": null
  },
  "classifier": {
    "category": "bank_impersonation",
    "score": 0.94,
    "top3": [["bank_impersonation", 0.94], ["account_suspension", 0.03], ["legit_alert", 0.02]],
    "baseline_score": 0.81
  },
  "customer_context": { "linked_bank": true, "linked_institutions": ["Capital One"] }
}
```

- `mode` is `check` or `recovery`. Recovery adds `"since": "<received_at>"`.
- Personal phone numbers are a salted hash. Business short codes stay visible because they are public and needed for `check_sender`.
- `sender.type`: `short_code`, `long_code`, `alphanumeric`, `email`, `unknown`.

### 3.2 Tools and what each returns to Nemotron

| Tool | Args | Returns |
| --- | --- | --- |
| `check_link` | `{"url_id": "URL_1"}` | `{"domain": "...", "domain_age_days": 3 or null, "on_blocklist": false, "lookalike_of": "capitalone.com" or null, "final_redirect_domain": "..." or null, "signals": ["brand term in non-official domain"]}` |
| `check_sender` | `{"claimed_brand": "Capital One"}` | `{"sender_type": "long_code", "matches_official_channel": false, "official_channels_known": true, "note": "..."}` |
| `match_campaign` | `{"message_id": "msg_0142"}` | `{"campaign_id": "camp_07" or null, "similar_last_24h": 140, "first_seen": "...", "similarity": 0.91, "template": "<BRAND>: your bill is overdue. Pay <AMOUNT> now..."}` |
| `nessie_recent_activity` | `{"days": 7}` or `{"since": "<iso time>"}` | `{"accounts_checked": 2, "items_checked": 23, "flagged": [{"ref": "txn_3", "type": "transfer", "amount": 900, "new_payee": true, "minutes_after_message": 17, "reason": "new payee, 6x the 30-day median"}]}` |
| `nessie_bill_status` | `{"payee": "T-Mobile"}` | `{"found": true, "last_status": "completed", "last_payment_date": "2026-11-01", "amount_due_now": 0, "recurring": true}` |
| `public_scam_reports` | `{"claimed_brand": "...", "scam_category": "...", "link_domain": "..."}` | Section 4.3 |

References such as `txn_3` resolve to full details only in the app, when shown to the customer. Nemotron never receives payee names, account numbers or merchant names.

### 3.3 Output Nemotron must return

```json
{
  "plan": ["check_link", "check_sender", "nessie_recent_activity"],
  "verdict": "likely_scam",
  "confidence_words": "very likely",
  "reason": "The link is not a Capital One website, and we found no unusual activity on your account.",
  "evidence": [
    {"tool": "check_link", "finding": "Domain is 3 days old and imitates Capital One"},
    {"tool": "nessie_recent_activity", "finding": "No new payees or unusual transfers in 7 days"}
  ],
  "actions": ["block_sender", "report_spam", "call_number_on_card"],
  "was_this_you": [],
  "replan": false
}
```

- `verdict`: `likely_scam`, `unsure`, `likely_safe`
- `confidence_words`: `very likely`, `likely`, `not sure`
- `actions` (at most 3): `block_sender`, `report_spam`, `call_number_on_card`, `open_official_app`, `freeze_card`, `change_password`, `alert_trusted_contact`, `ignore`
- `was_this_you`: list of references, filled in recovery mode

### 3.4 Trail entry (one per step, shown in "How we checked")

```json
{"step": 2, "kind": "tool", "tool": "check_sender", "why": "Sender claims to be Capital One", "finding": "Not an official Capital One channel", "ms": 412, "at": "2026-11-08T09:14:03-06:00"}
```

`kind` is `plan`, `tool`, `replan` or `verdict`.

### 3.5 Rules enforced in code

- Values outside the enums are rejected and retried once. A second failure returns `unsure` with the evidence so far.
- "Very likely" needs at least two findings from different tools. If the classifier and the tools disagree, the verdict is `unsure`.
- Phone numbers and URLs are stripped from `reason` and never shown as contact options.
- Tool results are passed as data. Text inside them is never followed as an instruction.
- At most 6 tool calls per message. Plan and every step are logged.

## 4. Gemini public-report lookup

The Gemini tool is not an open crawler. It is a Gemini call with Google Search grounding, run from a fixed query template. Deterministic checks (domain age, blocklists) run in our own code.

### 4.1 Inputs (the only data Gemini gets)

```json
{
  "claimed_brand": "Capital One",
  "scam_category": "bank_impersonation",
  "link_domain": "capone-verify-alert.com",
  "lure_phrase": "account locked, verify by link"
}
```

`lure_phrase` comes from our own list of generic phrases, picked by category. It is never copied from the customer's message.

### 4.2 The four things it looks for

| # | Question | Example query | Preferred sources |
| --- | --- | --- | --- |
| 1 | How does this brand really contact customers, and what does it say it never asks for by text? | `Capital One official text alerts never ask` | The brand's own site and help pages |
| 2 | Has this exact domain been reported as phishing? | `"capone-verify-alert.com" scam OR phishing` | Security vendor reports, phishing databases, news |
| 3 | Is this lure circulating now (last 30 days)? | `Capital One "account locked" text scam` | FTC consumer alerts, FCC, BBB Scam Tracker, state attorneys general, the brand's newsroom, then forums such as r/Scams |
| 4 | What are the official recovery steps for this scam type? | `what to do if you clicked bank phishing link` | The brand's fraud page, IdentityTheft.gov, FTC |

### 4.3 Output

```json
{
  "reports_found": 3,
  "reports": [
    {"source_type": "government", "publisher": "FTC", "url": "https://...", "date": "2026-10-29", "claim": "Texts claiming a locked account and asking you to verify are phishing", "stale": false}
  ],
  "brand_guidance": {"never_asks_by_text": ["password", "one-time code"], "source_url": "https://..."},
  "domain_reported": false,
  "recovery_steps_source": "https://...",
  "newest_report_age_days": 9
}
```

`source_type`: `official`, `government`, `news`, `security_vendor`, `community`.

### 4.4 Rules

- Source ranking: brand's own domain, then .gov, then news and security vendors, then forums. Forum posts never decide a verdict alone.
- Every fact needs a source URL from the grounding metadata. Facts without one are dropped.
- Reports older than 90 days are marked `stale`.
- Retrieved text is evidence, never instructions.
- Phone numbers from search results are never passed on. Scammers plant fake support numbers.
- "No reports found" is not evidence of safety. It is reported as "no public reports yet."

## 5. Redaction and storage

Redaction runs first.

| Removed | Replaced with | How |
| --- | --- | --- |
| Person names | `<PERSON>` | Named-entity model (optional) plus patterns |
| Personal phone numbers | `<PHONE_HASH_xxxx>` (salted hash) | Regex |
| Account or card digits (4 or more) | `<ACCOUNT_DIGITS>` | Regex |
| Street addresses | `<ADDRESS>` | Regex plus named-entity model |
| Email addresses | `<EMAIL>` | Regex |

Kept: brand names, business short codes, link domains (the full URL is replaced by `<URL_n>` in the text and described in `urls`), amounts, deadlines.

Redaction report returned with each message (feeds the privacy panel):

```json
{"counts": {"PERSON": 1, "PHONE": 0, "ACCOUNT_DIGITS": 0, "ADDRESS": 0, "EMAIL": 0}, "kept": ["brand", "domain", "deadline"]}
```

Stored: only campaign fingerprints (domain pattern, wording-template hash, claimed brand, category, time). Message text and Nessie records are kept in memory for the session only.

## 6. Nessie objects we use

Confirm field names against the Nessie docs on first call; adjust `integrations/nessie.py`, not the tools.

| Object | Fields we read |
| --- | --- |
| Customer | `_id`, `first_name`, `last_name` |
| Account | `_id`, `type`, `nickname`, `balance`, `customer_id` |
| Purchase | `_id`, `merchant_id`, `purchase_date`, `amount`, `status`, `description` |
| Transfer | `_id`, `payer_id`, `payee_id`, `transaction_date`, `amount`, `status`, `description` |
| Bill | `_id`, `status`, `payee`, `nickname`, `payment_date`, `recurring_date`, `payment_amount` |
| Merchant | `_id`, `name`, `category` |

## 7. How we measure

| Measure | Compared against | Reported as |
| --- | --- | --- |
| Precision, recall, F1 per category | Our baseline, same held-out test split | One row per category |
| Spam recall and FPR on real text | Baseline, on the public SMS set | One row |
| False positive rate on legitimate messages | Baseline | One number beside recall |
| Cost of redaction | Our model on unredacted vs. redacted text | One row |
| Agent verdict accuracy | Test labels, on a sample run through the full agent | Share correct, share `unsure` |
| Different plans per message | The three scenarios | Tool sequences side by side |
