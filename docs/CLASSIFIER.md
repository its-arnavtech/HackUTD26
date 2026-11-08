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
