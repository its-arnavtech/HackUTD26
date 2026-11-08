"""L7 tests use synthetic fixtures, never real held-out/public evaluations."""
from __future__ import annotations

import json
import pickle
import socket

import numpy as np
import pytest

from app.classifier import train as t
from app.classifier.predict import predict
from app.contracts import Features, Message
from app.features.extract import extract_features
from scripts import train_classifier as cli

TEXTS = {
    "billing_scam": ["T-Mobile bill overdue pay $30 now <URL_1>", "Your service will be suspended pay your bill <URL_1>", "Billing alert pay overdue balance now <URL_1>"],
    "delivery_scam": ["USPS parcel held pay redelivery fee <URL_1>", "Package customs payment required now <URL_1>", "Delivery failed update address at <URL_1>"],
    "legit": ["See you at dinner bring the salad", "Your bill was paid thanks no action needed", "Package delivered to your front door"],
}


def message(mid, text, category, **kwargs):
    return Message(message_id=mid, text=text, sender="+15550100000", source="generated",
                   prompt_set="train_v1", category=category, is_scam=category != "legit", **kwargs)


@pytest.fixture
def corpus(tmp_path):
    train, val = [], []
    for category, texts in TEXTS.items():
        for index, text in enumerate(texts):
            train.append(message(f"tr_{category}_{index}", text, category))
            val.append(message(f"va_{category}_{index}", text+" please", category))
    path=tmp_path / "splits.json"
    path.write_text(json.dumps({"train": [m.message_id for m in train], "val": [m.message_id for m in val], "test": ["heldout"]}))
    return train, val, path


@pytest.fixture
def model(corpus):
    train, val, path = corpus
    return t.train(train, val, splits_path=path, configs=(t.Config(),))


def test_fit_vocabulary_is_train_only_and_report_contains_no_text(corpus):
    train, val, path = corpus
    val = [m.model_copy(update={"text": m.text+" validationuniqueword"}) for m in val]
    model = t.train(train, val, splits_path=path, configs=(t.Config(),))
    assert "validationuniqueword" not in model.encoder.word.vocabulary_
    report = json.dumps(model.report)
    assert train[0].text not in report and train[0].message_id not in report
    assert model.report["train_rows"] == len(train) and model.report["validation_rows"] == len(val)
    assert len(model.report["trials"]) == 5
    assert model.report["selected"] in model.report["trials"]


@pytest.mark.parametrize("partition", ["train", "val"])
@pytest.mark.parametrize("bad", ["wrong_id", "test_prompt", "public", "missing_category", "wrong_label", "duplicate"])
def test_invalid_partitions_rejected_before_encoder(corpus, monkeypatch, partition, bad):
    train, val, path = corpus
    rows = list(train if partition == "train" else val)
    updates = {"wrong_id": {"message_id": "heldout"}, "test_prompt": {"prompt_set": "test_v1"},
               "public": {"source": "public"}, "missing_category": {"category": None},
               "wrong_label": {"is_scam": False}, "duplicate": {"message_id": rows[1].message_id}}
    rows[0] = rows[0].model_copy(update=updates[bad])
    monkeypatch.setattr(t.Encoder, "transform", lambda *a, **kw: pytest.fail("Invalid rows reached encoder"))
    with pytest.raises(ValueError):
        t.train(rows if partition == "train" else train, rows if partition == "val" else val, splits_path=path)


def test_swapped_partitions_and_overlap_rejected(corpus):
    train, val, path = corpus
    with pytest.raises(ValueError, match="split"):
        t.train(val, train, splits_path=path)
    data = json.loads(path.read_text()); data["test"].append(train[0].message_id); path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="disjoint"):
        t.train(train, val, splits_path=path)


def test_prediction_ignores_labels_sender_source_and_ids(model, corpus):
    train, _, _ = corpus
    changed = [m.model_copy(update={"category": "legit", "is_scam": False, "sender": "different", "message_id": "x", "source": "public"}) for m in train]
    assert model.predict(changed) == model.predict(train)
    assert model.predict([]) == []


def test_pipeline_and_batch_agree_with_a9_features(model, corpus):
    for row in corpus[0]:
        output = predict(row.text, extract_features(row.text), model=model)
        assert output.category == model.predict([row])[0]
        assert output.category == output.top3[0][0]
        assert output.score == output.top3[0][1]
        assert len(output.top3) == 3
        assert all(0 <= score <= 1 for _, score in output.top3)
        assert 0 <= output.baseline_score <= 1


def test_placeholder_hashes_and_occurrence_ids_do_not_learn_private_values(model):
    first = "pay bill <URL_1> call <PHONE_HASH_abcdef123>"
    second = "pay bill <URL_99> call <PHONE_HASH_different>"
    assert t.normalize(first) == t.normalize(second)
    np.testing.assert_allclose(model.predict_proba_texts([first]), model.predict_proba_texts([second]))


def test_a9_supplied_features_are_used(model):
    values = t.feature_dict("redacted text", Features(requested_action="make_payment", money_amount_claimed=500, asks_for=["payment"]))
    assert values["action"] == "make_payment" and values["amount_log"] > 0 and values["asks=payment"] == 1
    assert "money_amount_claimed" not in values


def test_local_artifact_round_trip_and_version_rejection(model, corpus, tmp_path):
    path=tmp_path / "model.pkl"
    t.save_model(model, path)
    restored=t.load_model(path)
    assert restored.predict(corpus[0]) == model.predict(corpus[0])
    with path.open("wb") as stream:
        pickle.dump({"algorithm": "old", "sklearn_version": "old", "model": model}, stream)
    with pytest.raises(ValueError, match="version"):
        t.load_model(path)


def test_model_runs_with_network_blocked(model, corpus, monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Classifier called network"))
    assert len(model.predict(corpus[0])) == len(corpus[0])


def test_training_cli_never_passes_test_to_training(corpus, model, tmp_path, monkeypatch):
    from app.classifier.baseline import Split
    train,val,_ = corpus
    monkeypatch.setattr(cli, "load_split", lambda: Split(train, val, [object()]))
    monkeypatch.setattr(cli, "ensure_redaction_salt", lambda: None)
    monkeypatch.setattr(cli, "redact_messages", lambda rows: rows)
    def fake_train(actual_train, actual_val):
        assert actual_train is train and actual_val is val
        return model
    monkeypatch.setattr(cli, "train", fake_train)
    path=tmp_path / "model.pkl"; report=tmp_path / "report.json"
    assert cli.main(["--model", str(path), "--report", str(report)]) == 0
    assert path.exists() and json.loads(report.read_text())["algorithm"] == t.ALGORITHM


def test_empty_or_invalid_candidates_fail(corpus):
    train,val,path=corpus
    with pytest.raises(ValueError, match="candidates"):
        t.train(train,val,splits_path=path,configs=())
    with pytest.raises(ValueError, match="positive"):
        t.train(train,val,splits_path=path,configs=(t.Config(c=float("nan")),))



def test_binary_public_macro_f1_is_correct():
    # 8 true spam, 2 missed spam, 1 false alarm, 19 true ham.
    row={"spam": 10, "ham": 20, "spam_recall": 0.8, "false_positive_rate": 0.05}
    assert cli.binary_macro_f1(row) == pytest.approx((16/19+38/41)/2)


def test_final_evaluation_refuses_a_second_run(tmp_path, monkeypatch):
    marker=tmp_path / "final.json"; marker.write_text('{"status":"complete"}')
    monkeypatch.setattr(cli, "load_split", lambda: pytest.fail("Repeated evaluation loaded test data"))
    with pytest.raises(FileExistsError, match="already"):
        cli.final_evaluation(tmp_path / "model.pkl", marker, tmp_path / "metrics.json")


def test_final_a13_run_uses_frozen_models_and_writes_both_metrics(corpus, model, tmp_path, monkeypatch):
    from app.classifier.baseline import Split
    from types import SimpleNamespace
    train,val,_=corpus
    path=tmp_path / "model.pkl"; t.save_model(model,path)
    split=Split(train,val,[object()])
    monkeypatch.setattr(cli,"load_split",lambda:split)
    monkeypatch.setattr(cli,"ensure_redaction_salt",lambda:None)
    monkeypatch.setattr(cli,"redact_messages",lambda rows:rows)
    events=[]
    def raw_fit(train_rows,val_rows,*,configs):
        assert train_rows is train and val_rows is val and configs==(model.config,)
        events.append("frozen")
        return model
    monkeypatch.setattr(cli,"train",raw_fit)
    def public_loader():
        assert events==["frozen"]
        return [object()]
    monkeypatch.setattr(cli.evaluation,"load_public_set",public_loader)
    def evaluate(factory,*,split,public):
        assert events==["frozen"]
        assert factory(train,val).predict(train)==model.predict(train)
        with pytest.raises(ValueError,match="condition"):
            factory([],[])
        scores={"public":{"spam":10,"ham":20,"spam_recall":0.8,"false_positive_rate":0.05},
                "test":{"macro_f1":0.9,"false_positive_rate":0.1}}
        return SimpleNamespace(model_dump_json=lambda **kw:'{}'),{"conditions":{"redacted":{"ours":scores,"baseline":scores}}}
    monkeypatch.setattr(cli.evaluation,"evaluate",evaluate)
    final=tmp_path / "final.json"; metrics=tmp_path / "metrics.json"
    report=cli.final_evaluation(path,final,metrics)
    assert report["status"]=="complete" and report["synthetic_strict_target_met"]
    assert final.exists() and metrics.exists() and metrics.with_name("metrics_details.json").exists()
