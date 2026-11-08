"""Synthetic-only fixtures for public roles, mixed-label training and final freeze."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.classifier import hybrid as h, public_data as d
from app.classifier.baseline import Split, score, taxonomy_ids
from app.classifier.predict import predict
from app.classifier.train import Config, Encoder
from app.contracts import Message, Metrics
from app.features.extract import extract_features
from scripts import evaluate as ev, train_public_classifier as cli


@pytest.fixture
def public(tmp_path):
    path=tmp_path / "public.parquet"; split=tmp_path / "public.json"
    texts=[f"see you for lunch tomorrow token{index}" for index in range(30)]+[f"win a prize claim your reward now token{index}" for index in range(30,40)]
    texts[1]=texts[0]  # Duplicates must share a role; fixture is synthetic only.
    pd.DataFrame({"sms":texts,"label":[0]*30+[1]*10}).to_parquet(path)
    manifest=d.create_split(path,split,seed=17)
    train=d.load_partition("train",parquet=path,splits_path=split)
    val=d.load_partition("val",parquet=path,splits_path=split)
    return path,split,manifest,train,val,texts


@pytest.fixture
def synthetic(tmp_path):
    train,val=[],[]
    for category,text in (("billing_scam","bill overdue pay now"),("prize_refund","win prize claim reward now"),("legit","see you tomorrow thanks")):
        for index in range(3):
            for role,rows in (("train",train),("val",val)):
                rows.append(Message(message_id=f"{role}_{category}_{index}",text=text+f" item{index}",sender="<UNKNOWN_SENDER>",
                    source="generated",prompt_set="train_v1",category=category,is_scam=category!="legit"))
    path=tmp_path / "synthetic.json"
    path.write_text(json.dumps({"train":[r.message_id for r in train],"val":[r.message_id for r in val],"test":["syn-heldout"]}))
    return train,val,path


@pytest.fixture
def model(public,synthetic):
    return h.train_hybrid(synthetic[0],synthetic[1],public[3],public[4],synthetic_splits=synthetic[2],public_splits=public[1],configs=(Config(),))


def test_split_is_exact_stratified_deterministic_and_grouped(public,tmp_path):
    path,split,saved,train,val,texts=public
    again=d.create_split(path,tmp_path/"second.json",seed=17)
    assert saved==again and len(saved["test"])==len(train)+len(val)==20
    assert len(val)==4 and saved["counts"]["test"]["spam"]==5
    sets=[set(saved[name]) for name in ("train","val","test")]
    assert not any(sets[i]&sets[j] for i in range(3) for j in range(i))
    assert any({"pub_00000","pub_00001"}<=ids for ids in sets)
    assert not any(text in split.read_text() for text in texts)
    assert d.create_split(path,split,seed=17)==saved
    with pytest.raises(ValueError,match="different"):
        d.create_split(path,split,seed=18)


def test_holdout_loader_is_closed_until_final_scoring(public,monkeypatch):
    monkeypatch.setattr(d.pq,"read_table",lambda *a,**kw:pytest.fail("Holdout decoded before final gate"))
    with pytest.raises(ValueError,match="final"):
        d.load_partition("test",parquet=public[0],splits_path=public[1])


def test_selected_loader_only_constructs_saved_rows(public):
    path,split,saved,train,val,_=public
    assert {r.message_id for r in train}==set(saved["train"])
    assert {r.message_id for r in val}==set(saved["val"])
    assert all(row.category is None and row.source=="public" for row in train+val)
    held=d.load_partition("test",parquet=path,splits_path=split,final_scoring=True)
    assert {r.message_id for r in held}==set(saved["test"])


def test_source_checksum_change_fails_before_text_loading(public,monkeypatch):
    path,split,*_=public
    path.write_bytes(path.read_bytes()+b"changed")
    monkeypatch.setattr(d.pq,"read_table",lambda *a,**kw:pytest.fail("Changed source decoded"))
    with pytest.raises(ValueError,match="checksum"):
        d.load_partition("train",parquet=path,splits_path=split)


def test_overlap_and_incomplete_manifest_fail(public):
    saved=public[2].copy(); saved["test"]=list(saved["test"])+[saved["train"][0]]
    public[1].write_text(json.dumps(saved))
    with pytest.raises(ValueError,match="disjoint"):
        d.read_split(public[1])


@pytest.mark.parametrize("bad",["heldout_id","category","source","label","prompt","duplicate"])
def test_public_invalid_rows_never_reach_encoder(public,synthetic,monkeypatch,bad):
    rows=list(public[3]); changed={"heldout_id":{"message_id":public[2]["test"][0]},"category":{"category":"billing_scam"},
        "source":{"source":"generated"},"label":{"is_scam":None},"prompt":{"prompt_set":"test_v1"},
        "duplicate":{"message_id":rows[1].message_id}}
    rows[0]=rows[0].model_copy(update=changed[bad])
    monkeypatch.setattr(Encoder,"transform",lambda *a,**kw:pytest.fail("Bad roles reached encoder"))
    with pytest.raises(ValueError):
        h.train_hybrid(synthetic[0],synthetic[1],rows,public[4],synthetic_splits=synthetic[2],public_splits=public[1])


def test_public_val_and_holdout_cannot_enter_fit_vocabulary(public,model):
    saved=public[2]
    forbidden=set(saved["val"]+saved["test"])
    for key in forbidden:
        index=int(key.removeprefix("pub_"))
        # A duplicate's token may legitimately exist in same-role rows only.
        token=f"token{index}"
        assert token not in model.encoder.word.vocabulary_


def test_binary_head_uses_all_fit_rows_category_head_only_synthetic(public,synthetic,model):
    assert set(model.binary.classes_)=={False,True}
    assert set(model.category_head.classes_)=={"billing_scam","prize_refund"}
    assert model.report["counts"]["binary_fit"]==len(public[3])+len(synthetic[0])
    assert model.report["counts"]["category_fit"]==6
    assert len(model.report["trials"])==len(h.BIASES)
    assert all(row.category is None for row in public[3])


def test_pipeline_and_batch_agree_and_ignore_metadata(public,model):
    rows=public[3]
    changed=[row.model_copy(update={"category":"made_up","is_scam":not row.is_scam,"message_id":"x","source":"authored"}) for row in rows]
    assert model.predict(rows)==model.predict(changed)
    for row in rows[:3]:
        out=predict(row.text,extract_features(row.text),model=model)
        assert out.category==model.predict([row])[0] and out.category==out.top3[0][0]
        assert 0<=out.score<=1 and 0<=out.baseline_score<=1
    assert model.predict([])==[]


def test_artifact_and_no_network(public,model,tmp_path,monkeypatch):
    path=tmp_path/"v2.pkl"; h.save_hybrid(model,path); restored=h.load_hybrid(path)
    monkeypatch.setattr(socket.socket,"connect",lambda *a,**kw:pytest.fail("Network used"))
    assert restored.predict(public[3])==model.predict(public[3])


def test_development_loader_never_requests_holdout(public,synthetic,monkeypatch):
    monkeypatch.setattr(cli,"load_split",lambda:Split(synthetic[0],synthetic[1],[object()]))
    monkeypatch.setattr(ev,"ensure_redaction_salt",lambda:None)
    monkeypatch.setattr(ev,"redact_messages",lambda rows:rows)
    calls=[]
    def loader(name):
        calls.append(name)
        return {"train":public[3],"val":public[4]}[name]
    monkeypatch.setattr(d,"load_partition",loader)
    _,partitions=cli.development()
    assert calls==["train","val"] and partitions[2] is public[3]


def test_final_marker_prevents_any_development_or_holdout_reads(tmp_path,monkeypatch):
    marker=tmp_path/"final.json"; marker.write_text('{"status":"complete"}')
    monkeypatch.setattr(cli,"development",lambda:pytest.fail("Repeat final evaluation read data"))
    with pytest.raises(FileExistsError,match="already"):
        cli.evaluate_once(final_path=marker)


def test_exact_a13_binary_scores():
    rows=[Message(message_id=str(i),text="synthetic",sender="unknown",is_scam=i<2,source="public") for i in range(6)]
    values=ev.score_public(rows,["billing_scam","legit","legit","legit","legit","job_offer"])
    assert values["confusion"]=={"tp":1,"fp":1,"fn":1,"tn":3}
    assert values["binary_macro_f1"]==pytest.approx((0.5+0.75)/2)



def test_final_scoring_freezes_before_decode_and_predicts_each_set_once(public,synthetic,model,tmp_path,monkeypatch):
    test=[synthetic[0][index].model_copy(update={"message_id":f"held{index}","prompt_set":"test_v1"}) for index in (0,3,6)]
    test[-1]=test[-1].model_copy(update={"source":"handwritten","prompt_set":"handwritten"})
    split=Split(synthetic[0],synthetic[1],test)
    partitions=(synthetic[0],synthetic[1],public[3],public[4])
    monkeypatch.setattr(cli,"development",lambda:(split,partitions))
    model_path=tmp_path/"model.pkl"; h.save_hybrid(model,model_path)
    final=tmp_path/"final.json"
    original_read=d.read_split; original_loader=d.load_partition; original_guard=d.guard_public
    monkeypatch.setattr(d,"read_split",lambda *a,**kw:original_read(public[1]))
    monkeypatch.setattr(d,"guard_public",lambda tr,va:original_guard(tr,va,splits_path=public[1]))
    def load_holdout(name,*,final_scoring):
        assert final.exists() and json.loads(final.read_text())["status"]=="started"
        assert name=="test" and final_scoring
        return original_loader(name,parquet=public[0],splits_path=public[1],final_scoring=True)
    monkeypatch.setattr(d,"load_partition",load_holdout)
    monkeypatch.setattr(ev,"redact_messages",lambda rows:rows)
    calls=[]
    predict_original=h.HybridModel.predict
    def predict_once(self,rows):
        calls.append(tuple(row.message_id for row in rows))
        return predict_original(self,rows)
    monkeypatch.setattr(h.HybridModel,"predict",predict_once)
    class Prior:
        def predict(self,rows): return ["legit"]*len(rows)
    monkeypatch.setattr(cli,"frozen_v1",lambda *a:Prior())
    archive=tmp_path/"archive"; archive.mkdir()
    scores=score([row.category for row in test],["legit"]*len(test),taxonomy_ids())
    (archive/"metrics.json").write_text(json.dumps({"public_set":{"n":40}}))
    condition={"test":scores,"public":{"spam_recall":0.1,"false_positive_rate":0.05}}
    (archive/"metrics_details.json").write_text(json.dumps({"conditions":{"redacted":{"ours":condition,"baseline":condition},"raw":{"baseline":{"test":scores}}}}))
    (archive/"classifier_final.json").write_text(json.dumps({"public_binary_macro_f1":{"ours":0.5}}))
    monkeypatch.setattr(cli,"ARCHIVE",archive)
    metrics_path=tmp_path/"metrics.json"
    result=cli.evaluate_once(model_path,final,metrics_path)
    assert len(calls)==2 and set(calls[0])=={row.message_id for row in test} and set(calls[1])==set(public[2]["test"])
    assert result["status"]=="complete" and result["comparison"]["public_same_holdout"]["n"]==20
    api=Metrics.model_validate_json(metrics_path.read_text())
    assert api.redaction_cost is None and api.public_set.n==20
    assert "50% holdout" in api.public_set.dataset
    with pytest.raises(FileExistsError): cli.evaluate_once(model_path,final,metrics_path)
