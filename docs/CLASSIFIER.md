# L7 public-data follow-up (v2)

The current pipeline loader expects the local v2 artifact. From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.train_public_classifier --prepare-split
.\.venv\Scripts\python.exe -m scripts.train_public_classifier
```

The saved split is immutable; `--prepare-split` verifies it instead of choosing
new IDs. Only synthetic train plus saved public fitting rows fit the binary
head and TF-IDF. The category head receives synthetic scam labels only;
public spam never receives fabricated category labels. Synthetic/public
validation select representation, C and legitimate bias. The report is
`eval/classifier_validation.json`; the ignored artifact is
`data/models/classifier-v2.pkl` (trusted local pickle, version checked).

`app.classifier.predict.predict(text_redacted, features)` keeps its existing
`ClassifierOutput` contract, and `model.predict(messages)` supports A13.
Restart the process after retraining. G1 explicitly labels its baseline
fallback when the local artifact is missing. L9 owns API pipeline wiring.

After committing the frozen selection, the explicit final step is
`python -m scripts.train_public_classifier --evaluate`. It opens the public
holdout only after writing a freeze marker. V2 scores synthetic test/public
holdout once; v1 and the baseline score the same public half for comparison.
The final marker blocks repeated evaluations. No new raw-text scoring pass is
run, so v2 `redaction_cost` is null; historical v1 cost stays archived.

See [public datasheet](../data/PUBLIC_SMS_DATASHEET.md) for the saved protocol,
prior exposure, sample sizes and limitations. V1 reports are preserved in
`eval/classifier_v1/`. The old full-public and new half-public results must be
labeled separately. Do not tune against the final held-out scores.

## Frozen follow-up result

V2 was selected on validation only and then scored once. No post-score tuning.

| Evaluation (redacted) | V1 | V2 | Original A1 baseline |
| --- | ---: | ---: | ---: |
| Synthetic category macro F1 (388) | 0.8781 | 0.8751 | 0.7915 |
| Synthetic legitimate FPR (388) | 0.1133 | 0.0800 | 0.1600 |
| Public binary macro F1 (same 2787 held-out rows) | 0.5193 | 0.9257 | 0.5980 |
| Public spam recall (same heldout) | 0.0751 | 0.7748 | 0.1903 |
| Public legitimate FPR (same heldout) | 0.0282 | 0.0012 | 0.0327 |

Synthetic F1 is 0.0030 lower than v1, with fewer false alarms; v2 still beats
the original raw-text baseline target of 0.807 F1 / 0.127 FPR. Public v2 has
289 true spam detections, 84 missed spam, 3 false alarms and 2,411 true ham.

For historical context only, v1 on the **entire 5,574-row public set** scored
binary F1 0.5299, spam recall 0.0897 and FPR 0.0292. That is a different sample
from the new holdout; do not use it as the matched old/new comparison. The
same-half table above is the direct comparison, and v2 learned from the other
half. This is an in-distribution held-out result under the revised protocol,
not a new independent external or zero-shot evaluation.

Reports: `eval/classifier_v2_final.json`, current `eval/metrics.json` and
`metrics_details.json`; historical reports in `eval/classifier_v1/`. The final
report records frozen parameters, model hash, saved split digest and exposure.

---

## Historical v1 documentation and result

The following documents the completed PR #58 experiment. Its evaluation-only
public-data restriction was superseded for the saved development half by
Arnav's explicit follow-up request. Its artifact and metrics remain archived.

# L7 local classifier (v1)

Run from `C:\HackUTD26-codex\backend` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.train_classifier
```

This uses A1's saved `load_split()` train and validation IDs, redacts those
messages, fits TF-IDF word/character vocabularies and logistic regressions on
train only, and selects representation weights, regularization and legitimate
bias on validation only. A9 message features and A1's fixed keyword features
are included. Sender, source, IDs and labels never enter feature vectors.
There are no external calls or new model downloads.

The local artifact is `data/models/classifier-v1.pkl` (ignored by git); the
aggregate selection report is `eval/classifier_validation.json`. Reproduce the
artifact locally rather than loading a pickle from an untrusted source. Its
scikit-learn version must match the environment. Restart after training, or
clear `app.classifier.predict.get_model.cache_clear()`.

Pipeline interface (redact and run A9 before calling):

```python
from app.classifier.predict import predict
result = predict(text_redacted, features)
```

It returns `ClassifierOutput`: category, relative model score, top three and
the baseline's score for the selected category. Scores after the validation
bias are not calibrated scam probabilities. The API pipeline is owned by L9;
this issue supplies the inference interface without editing that pipeline.
G1 uses the trained model when the local artifact exists; otherwise it explicitly
labels its existing baseline fallback and shows the train command.
The trained object's `predict(list[Message]) -> list[str]` supports A13. A13's
factory interface is `app.classifier.train:make_model`.

## Held-out protocol

After selecting and freezing the production artifact, the explicit final step
is `python -m scripts.train_classifier --evaluate`. It uses A13's `evaluate()`
for the redacted test/public scores and a raw-text redaction-cost control. The
raw control uses the production representation and C, selecting its legitimate
bias on raw validation before any held-out scoring. The production artifact
is unchanged. Both models are frozen before test/public scoring; no result is
used to retune either model.

The command writes `eval/metrics.json`, `eval/metrics_details.json` and
`eval/classifier_final.json`. The final report prevents accidental repeated
evaluation. Do not rerun held-out evaluation to pick another configuration.
Public labels are binary, so its macro F1 is binary; it cannot supply our
nine-category macro F1. A13's existing public spam recall and FPR remain in
the standard API metrics contract; binary F1 is in the detail/final reports.

The synthetic target is macro F1 > 0.807 with FPR <= 0.127. Compare public
binary F1 and FPR with the baseline on that same public set. If either gate
fails, document the failure/pivot and keep these sets held out.

## Frozen result and pivot

The one final A13 run used 388 synthetic test messages and all 5,574 public SMS
messages. The production model was selected before either was scored.

| Redacted input | L7 | Same-condition baseline |
| --- | ---: | ---: |
| Synthetic nine-category macro F1 | 0.8781 | 0.7915 |
| Synthetic legitimate FPR | 0.1133 | 0.1600 |
| Public binary macro F1 | 0.5299 | 0.5878 |
| Public spam recall | 0.0897 | 0.1767 |
| Public legitimate FPR | 0.0292 | 0.0342 |

The synthetic result also exceeds A1's original raw-text target of 0.807 F1
and improves on its 0.127 FPR. L7 improves F1 in every synthetic category.
The raw-text cost control scores 0.8962 macro F1, versus 0.8781 redacted.

**The cross-dataset acceptance target failed.** Fewer public false alarms came
with worse public spam recall and binary F1. L7 must not be presented as a
universal improvement over the baseline. The acceptance-criteria pivot is to
show the synthetic gains, public stress-test failure and redaction cost side
by side, while keeping the classifier as one signal for the verification
agent. A new generalization experiment would need separate development data
and a fresh untouched evaluation set; do not tune on this public/test result.
No embeddings or transformer were attempted after seeing these final scores.

Reports contain aggregate scores only. The final marker records the model
artifact hash and selection. Scoring used the pre-existing local NumPy 2.5.4
venv with scikit-learn 1.9.1; the project pin remains NumPy 2.4.6 for Python
3.11 support. Post-score compatibility checks use the project pin without
repeating held-out scoring.
