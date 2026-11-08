# L7 local classifier

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
