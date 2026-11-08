# SentinelAI — public dataset findings (checked 2026-11-08, HTTP 200 unless noted)

Sizes/licenses are from dataset cards as I know them; re-check the card before you cite one to judges.

The synthetic files under `data/generated/` (`messages_multiclass.jsonl`, `campaigns.jsonl`, `urls.jsonl`, `linked_scenarios.jsonl`, `telecom_events.jsonl`, `payment_schema.json`, `schema_mappings/`) are the stand-in for gaps 1–6 below. They are not a substitute for the public sets, and they are not real customer data. The datasheet is `data/generated/SYNTHETIC_LINKED_README.md`. Gap 7 (Gemini `public_scam_reports` fixtures) is still a recording task, not a data-generation task.

## Ranked top picks

| # | Dataset | URL | Size / labels | License | Feeds |
|---|---|---|---|---|---|
|1|UCI SMS Spam Collection (HF mirror ucirvine/sms_spam)|https://huggingface.co/datasets/ucirvine/sms_spam · https://archive.ics.uci.edu/dataset/228/sms+spam+collection|5,574 SMS; spam/ham|CC BY 4.0|Real-world classifier test (binary: scam vs legit). This is what `scripts.setup_huggingface` restores|
|2|Mendeley SMS Phishing Dataset (Mishra & Soni)|https://data.mendeley.com/datasets/f45bkkt8pr/1|~5,971 SMS; ham/spam/smishing, plus URL/email/phone flags|CC BY 4.0|Real smishing test set; flags help with link/sender checks|
|3|ScamBench|https://huggingface.co/datasets/Shouninger/ScamBench|Scam conversations, multiple scam types|see card|The closest public match to multi-class taxonomy labels; map its types to taxonomy ids|
|4|PhiUSIIL Phishing URL (UCI)|https://archive.ics.uci.edu/dataset/967/phiusiil+phishing+url+dataset|~235k URLs; phishing/legit + features|CC BY 4.0|check_link eval set|
|5|OpenPhish feed / PhishTank / URLhaus API|https://openphish.com/feed.txt · https://data.phishtank.com/ · https://urlhaus.abuse.ch/api/|Live phishing/malware URLs|Free for non-commercial use (PhishTank needs a key)|check_link blocklist snapshot (record as fixture)|
|6|pirocheto/phishing-url|https://huggingface.co/datasets/pirocheto/phishing-url|~11k URLs, 87 features, phishing/legit|CC BY-SA 4.0|check_link quick eval|
|7|Sparkov synthetic credit card (kartik2112)|https://www.kaggle.com/datasets/kartik2112/fraud-detection|~1.85M txns: cc_num, merchant, category, amt, timestamps, geo, is_fraud|CC0|nessie_recent_activity anomaly baseline; has a merchant category → payment schema|
|8|PaySim|https://www.kaggle.com/datasets/ealaxi/paysim1 · https://huggingface.co/datasets/theman10/paysim|~6.36M mobile-money txns: step,type(PAYMENT/TRANSFER/CASH_OUT/DEBIT/CASH_IN),amount,nameOrig/Dest,balances,isFraud|CC BY-SA 4.0|Transfer/drain patterns; account-takeover cash-out shape|
|9|IBM Transactions for AML|https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml|Multiple sizes (millions of rows): from/to bank+account, amount, currency, payment format, is_laundering|Community Data License (see card)|Configurable schema (currency, payment format, multi-bank)|
|10|BankSim|https://www.kaggle.com/datasets/ealaxi/banksim1|~594k txns: customer, age, gender, merchant, category, amount, fraud|CC BY-NC-SA 4.0|Merchant-category baselines|
|11|IEEE-CIS Fraud Detection|https://www.kaggle.com/c/ieee-fraud-detection|~590k train txns; 400+ columns incl. device/identity features|Competition rules only, no redistribution|Device/session fields for the schema (research use only)|
|12|ULB Credit Card Fraud|https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud|284,807 txns, PCA V1–V28, Amount, Class|ODbL|Weak fit because of the anonymised features. Use only as a benchmark|

Also worth knowing: MOZNLP/MOZ-Smishing (Portuguese, Mozambique), bengali/korean smishing sets, CloveAI/india-spam-sms, Ridham115/indian-scam-sms-synthetic-audited, alusci/sms-otp-spam-dataset (OTP lures, relevant to account_security). Non-English and region-specific sets are useful only for robustness checks. J.P. Morgan synthetic AML/fraud data needs a request form. IBM AMLSim (github.com/IBM/AMLSim) is a generator, but GitHub returned 504 and I could not verify it.

## Uncovered gaps

1. No public SMS set carries labels for the 9 taxonomy categories (real sets are binary or 3-class).
2. No telecom/carrier billing-scam or SIM-swap dataset with events (port-out, eSIM transfer, carrier bill changes). Only papers and FTC aggregate stats exist (FTC Consumer Sentinel data book: aggregate counts, not records).
3. No public dataset links a scam message to a click and then to account activity. None exists.
4. No bill-object data (biller, due date, status, autopay) in the fraud sets. Nessie bills are the only source.
5. No campaign clusters (variants of one scam template) for campaign matching.
6. No system-agnostic payment event schema. Each dataset uses its own.
7. Gemini public_scam_reports fixtures are missing (record them; data cannot fill this).
