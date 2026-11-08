# Public SMS classifier extension (L7 follow-up)

This source is separate from the synthetic dataset in `data/generated/`.
Arnav authorized its development use after v1 failed the public comparison.

- Source: `ucirvine/sms_spam`, revision `cae486f927c250fe1d4a5b55f11357964ed1646c`; the A5 cached parquet has SHA-256 `6e5518e4a49cb2de8af9c89a38b742825cdddbb55942701fc2237d4364288abd`.
- A5 recorded upstream UCI's CC BY 4.0 license; the Hugging Face card did not specify a license. [UCI source](https://archive.ics.uci.edu/dataset/228/sms+spam+collection).
- Labels are binary ham/spam. They do not annotate SentinelAI's eight scam categories. Public spam trains only a binary head; the category head uses synthetic scam rows only.
- Raw public SMS remains ignored under `data/raw/public_sms/`; no real message text is committed, printed, or put into tests. Models see locally redacted text.

## Saved protocol

`data/public_sms_splits.json` records row IDs, class counts, source checksum,
seed **20261108** and the partition rule. It is immutable after selection.

| Role | Rows | Spam | Ham |
| --- | ---: | ---: | ---: |
| Authorized development half | 2787 | 374 | 2413 |
| Fitting within development | 2229 | 299 | 1930 |
| Validation within development | 558 | 75 | 483 |
| Held-out half | 2787 | 373 | 2414 |

Before assigning any holdout roles, partition creation uses ephemeral hashes
of case-folded, whitespace-normalized SMS to keep exact duplicate groups
together. There are 5,159 such groups across 5,574 rows. A fixed-seed grouped
subset selection meets exact binary-stratified 50/50 row counts; development
then reserves 20% for validation with the same group boundary. No duplicate
group spans fitting, validation or holdout. Similar templates and redaction
variants can still span roles; this is not a near-duplicate-free benchmark.
After roles are saved, loaders select row indices before constructing message
strings. The holdout loader is unavailable during development.

Binary fitting adds 2,229 public rows to A1's 1,818 synthetic train rows
(4,047 total). Category fitting uses 1,127 synthetic scams only. TF-IDF
vocabulary, IDF, feature dictionary and classifier weights fit only those
training observations. Selection maximizes the mean of synthetic category
and public binary validation macro F1 under separate validation FPR limits.
Neither synthetic test nor public holdout selects parameters.

## Prior exposure and comparability

The full public dataset and synthetic test were evaluated in v1. The new half
is held out from this follow-up's fitting/selection; it is **not a previously
unseen external sample**. The old aggregate public result motivated this
user-authorized protocol revision. Do not present the new score as the old
full-set stress test or a clean independent prospective validation.

The final run compares v1, v2 and the original synthetic-only A1 baseline on
the **same saved public holdout** once. Preserve the original full-set v1
numbers separately, with the different sample size labeled. Synthetic v1
results are reused from the archive; v2 synthetic test predictions run once.
No post-test tuning. There is no new v2 raw-text test pass: the current API
redaction-cost field is null, and the historical v1 cost stays archived.

These public IDs never enter campaign seeds, blocklists, model prompts or
outside services. The explicitly authorized public-development exception
applies only to this local classifier and its saved roles.
