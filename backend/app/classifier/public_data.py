"""Revised public SMS protocol authorized by Arnav after L7 v1.

Only partition creation hashes all source text, before a holdout exists, to keep
normalized exact duplicates together. Later loaders take selected row indices
before decoding SMS strings. No text leaves the process or enters the manifest.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.model_selection import train_test_split

from app.config import DATA_DIR
from app.contracts import Message

PARQUET = DATA_DIR / "raw" / "public_sms" / "plain_text" / "train-00000-of-00001.parquet"
SPLITS = DATA_DIR / "public_sms_splits.json"
SEED = 20261108
PROTOCOL = "public-half-grouped-v1"


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _targets(labels: list[int], size: int, seed: int) -> Counter:
    chosen, _ = train_test_split(list(range(len(labels))), train_size=size, stratify=labels, random_state=seed)
    return Counter(labels[index] for index in chosen)


def _choose(groups: list[list[int]], target: int, rng: random.Random) -> list[int]:
    """Seeded exact subset-sum: never split an equal-text group across roles."""
    groups = list(groups)
    rng.shuffle(groups)
    reachable, history = 1, []
    mask = (1 << (target+1))-1
    for group in groups:
        history.append(reachable)
        reachable = (reachable | (reachable << len(group))) & mask
    if not ((reachable >> target) & 1):
        raise ValueError("Cannot meet exact stratified count without splitting duplicate groups")
    selected, remaining = [], target
    for group, previous in reversed(list(zip(groups, history))):
        if not ((previous >> remaining) & 1):
            selected.extend(group)
            remaining -= len(group)
    assert remaining == 0
    return sorted(selected)


def create_split(parquet: Path = PARQUET, path: Path = SPLITS, *, seed: int = SEED) -> dict:
    if path.exists():
        saved = read_split(path)
        if saved["dataset_sha256"] != checksum(parquet) or saved["seed"] != seed:
            raise ValueError("Public split already exists for different data/seed")
        return saved
    table = pq.read_table(parquet, columns=["sms", "label"])
    labels = [int(value) for value in table["label"].to_pylist()]
    if set(labels) != {0, 1} or len(labels) % 2:
        raise ValueError("Need an even binary SMS set for exact 50/50 partition")
    grouped = defaultdict(list)
    for index, text in enumerate(table["sms"].to_pylist()):
        key = hashlib.sha256(" ".join(str(text).casefold().split()).encode()).hexdigest()
        grouped[key].append(index)
    if any(len({labels[index] for index in group}) != 1 for group in grouped.values()):
        raise ValueError("Duplicate SMS group has conflicting binary labels")
    rng = random.Random(seed)
    half = _targets(labels, len(labels)//2, seed)
    development = []
    for label in (0, 1):
        development.extend(_choose([group for group in grouped.values() if labels[group[0]] == label], half[label], rng))
    development = sorted(development)
    dev_set = set(development)
    holdout = sorted(set(range(len(labels)))-dev_set)
    # Reserve 20% of the authorized training half for tuning, never fitting.
    n_val = (len(development)+4)//5
    fit_targets = _targets([labels[index] for index in development], len(development)-n_val, seed+1)
    fitting = []
    for label in (0, 1):
        fitting.extend(_choose([group for group in grouped.values() if group[0] in dev_set and labels[group[0]] == label], fit_targets[label], rng))
    fitting = sorted(fitting)
    validation = sorted(dev_set-set(fitting))
    partitions = {"train": fitting, "val": validation, "test": holdout}
    payload = {"protocol": PROTOCOL, "seed": seed, "dataset": "ucirvine/sms_spam",
               "dataset_revision": "cae486f927c250fe1d4a5b55f11357964ed1646c",
               "dataset_sha256": checksum(parquet), "rows": len(labels),
               "rule": "50/50 binary-stratified development/holdout; development reserves 20% validation; normalized exact-duplicate groups stay together",
               "prior_exposure": "all rows were evaluated in L7 v1; holdout is isolated from this follow-up development, not a never-seen sample",
               "normalized_text_groups": len(grouped),
               "counts": {name: {"rows": len(indices), "spam": sum(labels[index] for index in indices),
                                  "ham": sum(not labels[index] for index in indices)} for name, indices in partitions.items()},
               **{name: [f"pub_{index:05d}" for index in indices] for name, indices in partitions.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return payload


def read_split(path: Path = SPLITS) -> dict:
    saved = json.loads(path.read_text(encoding="utf-8"))
    if saved["protocol"] != PROTOCOL:
        raise ValueError("Unknown public split protocol")
    seen = set()
    for name in ("train", "val", "test"):
        ids = saved[name]
        if not ids or len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError("Public partitions must be nonempty, unique and disjoint")
        seen.update(ids)
    if seen != {f"pub_{index:05d}" for index in range(saved["rows"])}:
        raise ValueError("Public partitions must cover the pinned dataset exactly")
    if len(saved["train"])+len(saved["val"]) != len(saved["test"]):
        raise ValueError("Public development/holdout must be 50/50")
    return saved


def load_partition(partition: str, *, parquet: Path = PARQUET, splits_path: Path = SPLITS,
                   final_scoring: bool = False) -> list[Message]:
    if partition not in {"train", "val", "test"} or (partition == "test" and not final_scoring):
        raise ValueError("Public holdout may be decoded only in the final scoring run")
    saved = read_split(splits_path)
    if checksum(parquet) != saved["dataset_sha256"]:
        raise ValueError("Public source checksum differs from saved IDs")
    indices = [int(key.removeprefix("pub_")) for key in saved[partition]]
    # Arrow take BEFORE converting SMS to Python strings; unselected text is
    # neither constructed as Message nor redacted, featurized or displayed.
    selected = pq.read_table(parquet, columns=["sms", "label"]).take(pa.array(indices))
    return [Message(message_id=key, text=str(row["sms"]).strip(), sender="<UNKNOWN_SENDER>",
                    source="public", is_scam=bool(int(row["label"])), category=None)
            for key, row in zip(saved[partition], selected.to_pylist())]


def guard_public(train: list[Message], val: list[Message], *, splits_path: Path = SPLITS) -> str:
    saved = read_split(splits_path)
    for name, rows in (("train", train), ("val", val)):
        ids = [row.message_id for row in rows]
        if len(ids) != len(set(ids)) or set(ids) != set(saved[name]):
            raise ValueError("Public fitting/validation rows must match saved roles exactly")
        if any(row.source != "public" or row.category is not None or row.is_scam is None or row.prompt_set is not None for row in rows):
            raise ValueError("Public rows supply binary labels only; never fabricated scam categories")
        if {row.is_scam for row in rows} != {False, True}:
            raise ValueError("Both public fitting and validation need both binary classes")
    return hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()
