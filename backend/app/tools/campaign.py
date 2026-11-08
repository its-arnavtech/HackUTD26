"""A12 campaign fingerprints, validation calibration and read-only lookup.

The SQLite store persists fingerprints only. UI previews come from fixed public
category descriptions; they are explicitly pattern previews, not message quotes.
Calibration uses brand/category family agreement as a proxy because this corpus
has no campaign labels. Its F1 is not a measurement of true campaign accuracy.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR
from app.contracts import (AgentInput, Campaign, MatchCampaignArgs, MatchCampaignResult, Message,
                           MessageSource)
from app.features.extract import detect_claimed_brand, extract_features, extract_urls
from app.privacy.redact import redact
from app.tools.campaign_store import ALGORITHM, DEFAULT_FILENAME, CampaignStore, Fingerprint, Member, stamp, utc

SPLITS_PATH = DATA_DIR / "generated" / "splits.json"
EMPTY_TEMPLATE = hashlib.sha256(b"").hexdigest()
SEMANTIC_WEIGHTS = (0.0, 0.25, 0.5, 0.75)
THRESHOLDS = tuple(round(value / 100, 2) for value in range(55, 101, 5))
_PREVIEWS = {
    "bank_impersonation": "<BRAND>: account-security claim; verify using <URL>.",
    "billing_scam": "<BRAND>: bill or payment demand; pay <AMOUNT> using <URL>.",
    "delivery_scam": "Delivery claim; update an address or pay a fee using <URL>.",
    "account_security": "<BRAND>: account-security claim; provide access details or a code.",
    "toll_government": "Toll or government claim; pay <AMOUNT> using <URL>.",
    "prize_refund": "Prize, reward or refund claim; respond using <URL>.",
    "job_offer": "Job or income offer; continue through a link or another channel.",
    "conversation_lure": "Personal conversation or family claim; respond or send money.",
    "legit": "Message pattern.",
}


@lru_cache(maxsize=1)
def _taxonomy() -> dict[str, bool]:
    rows = json.loads((DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"))["categories"]
    return {row["id"]: row["is_scam"] for row in rows}


@lru_cache(maxsize=1)
def default_store() -> CampaignStore:
    return CampaignStore(DATA_DIR / DEFAULT_FILENAME)


def _event_hash(message_id: str) -> str:
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()


def _domain_pattern(agent_input: AgentInput) -> str:
    patterns = set()
    for url in agent_input.urls:
        if url.is_official_brand_domain:
            patterns.add("<OFFICIAL_DOMAIN>")
        elif url.is_shortener:
            patterns.add("<SHORTENER>")
        else:
            domain = url.registered_domain.casefold()
            lure = next((label for label, terms in (
                ("billing", ("bill", "pay", "payment")), ("verification", ("verify", "login", "account", "secure")),
                ("delivery", ("deliver", "parcel", "package")), ("reward", ("reward", "prize", "refund")),
                ("toll", ("toll", "tax", "dmv"))) if any(term in domain for term in terms)), "link")
            root = "<BRAND>" if url.brand_term_in_domain else "<DOMAIN>"
            patterns.add(f"{root}-{lure}.<TLD>")
    return " | ".join(sorted(patterns))


def _wording(text: str, brand: str) -> tuple[str, list[str]]:
    # Every normalized string exists only on the stack, never in SQLite/report.
    text = re.sub(r"<PHONE_HASH_[^>]+>", "<PHONE>", text)
    text = re.sub(r"<URL_\d+>", "<URL>", text)
    if brand:
        words = re.findall(r"[^\W_]+", brand)
        text = re.sub(r"(?<!\w)" + r"[\s_-]*".join(re.escape(word) for word in words) + r"(?!\w)", "<BRAND>", text, flags=re.I)
    text = re.sub(r"[$£€]\s*\d[\d,.]*|\b\d[\d,.]*\s*(?:USD|GBP|EUR)\b", "<AMOUNT>", text, flags=re.I)
    text = re.sub(r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty-four)\s*(?:seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b", "<TIME>", text, flags=re.I)
    text = re.sub(r"\d+(?:[.,]\d+)*", "<NUMBER>", text)
    tokens = re.findall(r"<[^>]+>|[^\W\d_]+(?:['’][^\W\d_]+)*", text.casefold())
    canonical = " ".join(tokens)
    meaningful = [token for token in tokens if not token.startswith("<")]
    return canonical if meaningful else "", meaningful


def _simhash(tokens: list[str]) -> str:
    if not tokens:
        return "0" * 16
    grams = Counter(tokens + [left + " " + right for left, right in zip(tokens, tokens[1:])])
    votes = [0] * 64
    for token, weight in grams.items():
        hashed = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8, person=b"sentinel-a12-v1").digest(), "big")
        for bit in range(64):
            votes[bit] += weight if hashed & (1 << bit) else -weight
    return f"{sum(1 << bit for bit, vote in enumerate(votes) if vote > 0):016x}"


# Fixed intent/context bits are part of the wording fingerprint, not stored
# feature text. Intent overlap tolerates messages that omit optional details.
_INTENT_MASK = (1 << 8)-1


def _semantic_signature(agent_input: AgentInput) -> str:
    feature = agent_input.features
    asks = set(feature.asks_for)
    action = feature.requested_action
    bits = set()
    if action in {"click_link_and_pay", "make_payment"} or "payment" in asks:
        bits.add(0)
    if action in {"click_link_and_verify", "verify_account", "share_credentials"} or asks.intersection({"login", "password", "card_details", "account_details", "personal_information"}):
        bits.add(1)
    if action == "reply_with_code" or "one_time_code" in asks:
        bits.add(2)
    for value, bit in (("download_app", 3), ("click_link", 4), ("reply", 5), ("call_number", 6), ("open_official_app", 7)):
        if action == value:
            bits.add(bit)
    if feature.threat in {"account_lock", "service_suspension", "account_deletion"}:
        bits.add(8)
    if feature.threat == "payment_penalty":
        bits.add(9)
    if feature.threat == "legal_action":
        bits.add(10)
    if feature.money_amount_claimed is not None:
        bits.add(11)
    if feature.urgency_deadline is not None:
        bits.add(12)
    if agent_input.urls:
        bits.add(13)
    return f"{sum(1 << bit for bit in bits):016x}"


def fingerprint(agent_input: AgentInput) -> dict[str, str]:
    """Hash a redacted message; discard all wording after constructing the hashes."""
    category = agent_input.classifier.category
    if category not in _taxonomy():
        raise ValueError("Unknown campaign category")
    # Only registry brand names can enter persistent metadata, never arbitrary
    # sender/model-provided free text.
    brand = (detect_claimed_brand(agent_input.sender.claimed_brand or "", core_only=True)
             or detect_claimed_brand(agent_input.text_redacted, core_only=True) or "")
    canonical, tokens = _wording(agent_input.text_redacted, brand)
    return asdict(Fingerprint(_event_hash(agent_input.message_id), _domain_pattern(agent_input),
                             hashlib.sha256(canonical.encode("utf-8")).hexdigest(), _simhash(tokens) + _semantic_signature(agent_input), brand,
                             category, stamp(agent_input.received_at)))


def _fp(agent_input: AgentInput) -> Fingerprint:
    return Fingerprint(**fingerprint(agent_input))


def similarity(left: Fingerprint, right: Fingerprint, *, semantic_weight: float = 0.0) -> float:
    if EMPTY_TEMPLATE in (left.template_hash, right.template_hash):
        return 0.0
    if left.claimed_brand and right.claimed_brand and left.claimed_brand != right.claimed_brand:
        return 0.0
    words = 1.0 if left.template_hash == right.template_hash else 1 - (int(left.wording_simhash[:16], 16) ^ int(right.wording_simhash[:16], 16)).bit_count() / 64
    left_semantic, right_semantic = int(left.wording_simhash[16:], 16), int(right.wording_simhash[16:], 16)
    overlap = left_semantic & right_semantic
    comparable = bool(overlap & _INTENT_MASK) and overlap.bit_count() >= 2
    semantic = overlap.bit_count() / min(left_semantic.bit_count(), right_semantic.bit_count()) if comparable else words
    wording = (1-semantic_weight) * words + semantic_weight * semantic
    return (0.75 * wording + 0.10 * (left.domain_pattern == right.domain_pattern)
            + 0.10 * (left.claimed_brand == right.claimed_brand) + 0.05 * (left.category == right.category))


def _score(store: CampaignStore):
    weight = store.semantic_weight
    return lambda left, right: similarity(left, right, semantic_weight=weight)


def _manifest(path: Path) -> dict[str, list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seen = set()
    for name in ("train", "val", "test"):
        ids = data[name]
        if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids) or len(ids) != len(set(ids)) or seen.intersection(ids):
            raise ValueError("Saved campaign split must have unique, disjoint IDs")
        seen.update(ids)
    return data


def _guard(messages: list[Message], partition: str, saved: dict) -> None:
    ids = [message.message_id for message in messages]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate campaign observation IDs")
    allowed = set(saved[partition])
    for message in messages:
        if (message.message_id not in allowed or message.source != MessageSource.generated
                or message.prompt_set != "train_v1"):
            raise ValueError("Campaign seeds/calibration must use the designated train/validation IDs only")
        if message.category not in _taxonomy() or message.is_scam is None or message.is_scam != _taxonomy()[message.category]:
            raise ValueError("Campaign source labels must match the project taxonomy")
        if message.received_at is None:
            raise ValueError("Campaign source observations need original timestamps")
        utc(message.received_at)


def load_training_validation(generated_dir: Path = DATA_DIR / "generated", *, splits_path: Path = SPLITS_PATH) -> tuple[list[Message], list[Message]]:
    """Filter by saved IDs BEFORE validating/using text; never open handwritten test.

    The JSONL contains several splits. Unselected rows are discarded immediately
    and never redacted, fingerprinted, displayed, or used by calibration.
    """
    saved = _manifest(splits_path)
    memberships = {key: partition for partition in ("train", "val") for key in saved[partition]}
    groups: dict[str, list[Message]] = {"train": [], "val": []}
    with (generated_dir / "messages.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            data = json.loads(line)
            partition = memberships.get(data.get("message_id"))
            if partition:
                groups[partition].append(Message.model_validate(data))
    for partition, messages in groups.items():
        if {message.message_id for message in messages} != set(saved[partition]):
            raise ValueError("Saved train/validation observations are missing")
        _guard(messages, partition, saved)
    return groups["train"], groups["val"]


def message_input(message: Message) -> AgentInput:
    """Local bootstrap adapter; known dataset labels are metadata, not predictions."""
    if message.received_at is None or message.category not in _taxonomy():
        raise ValueError("Campaign input needs a timestamp and known category")
    redacted = redact(message.text, core_brands_only=True)  # calibrated on the core brand registry
    brand = detect_claimed_brand(redacted.text_redacted, core_only=True)
    return AgentInput(message_id=message.message_id, mode="check", received_at=message.received_at,
                      sender={"type": "unknown", "value": "<UNKNOWN_SENDER>", "claimed_brand": brand},
                      text_redacted=redacted.text_redacted, urls=extract_urls(redacted), features=extract_features(redacted.text_redacted),
                      classifier={"category": message.category, "score": 1.0, "top3": []},
                      customer_context={"linked_bank": False, "linked_institutions": []})


def calibrate_threshold(train_set: list[Message], validation_set: list[Message], *, store: CampaignStore | None = None,
                        splits_path: Path = SPLITS_PATH) -> dict:
    """Select semantic blend/threshold on validation family-proxy F1 only.

    Ties favor a higher threshold and then a smaller semantic contribution.

    Labels are brand/category family proxies, not campaign annotations. Held-out
    validation fingerprints are discarded and never inserted into the store.
    """
    saved = _manifest(splits_path)
    _guard(train_set, "train", saved); _guard(validation_set, "val", saved)
    training = [_fp(message_input(message)) for message in train_set if message.is_scam]
    if not training or not any(message.is_scam for message in validation_set) or not any(not message.is_scam for message in validation_set):
        raise ValueError("Calibration needs training scams and both validation classes")
    queries = [(_fp(message_input(message)), bool(message.is_scam)) for message in validation_set]
    reports = []
    for weight in SEMANTIC_WEIGHTS:
        trials = []
        for query, scam in queries:
            scored = sorted(((similarity(query, candidate, semantic_weight=weight), candidate) for candidate in training),
                            key=lambda pair: (-pair[0], pair[1].event_hash))
            score, candidate = scored[0]
            correct_family = candidate.category == query.category and candidate.claimed_brand == query.claimed_brand
            trials.append((score, scam, correct_family))
        for threshold in THRESHOLDS:
            tp = sum(score >= threshold and scam and correct for score, scam, correct in trials)
            fp = sum(score >= threshold and not (scam and correct) for score, scam, correct in trials)
            fn = sum(scam and not (score >= threshold and correct) for score, scam, correct in trials)
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            reports.append({"threshold": threshold, "semantic_weight": weight, "true_positive": tp, "false_positive": fp,
                            "false_negative": fn, "precision": precision, "recall": recall, "f1": f1})
    selected = max(reports, key=lambda report: (report["f1"], report["threshold"], -report["semantic_weight"]))
    digest = hashlib.sha256(json.dumps({name: sorted(saved[name]) for name in ("train", "val")}, sort_keys=True).encode()).hexdigest()
    report = {"algorithm": ALGORITHM, "split_digest": digest, "training_fingerprints": len(training),
              "validation_rows": len(validation_set), "validation_positive": sum(bool(message.is_scam) for message in validation_set), **selected}
    (store if store is not None else default_store()).set_calibration(report)
    return report


def seed_campaigns(train_set: list[Message], *, store: CampaignStore | None = None, splits_path: Path = SPLITS_PATH) -> int:
    """Insert new training-scam fingerprints only; repeated seeds insert zero."""
    _guard(train_set, "train", _manifest(splits_path))
    fingerprints = [_fp(message_input(message)) for message in train_set if message.is_scam]
    active = store if store is not None else default_store()
    return active.add(fingerprints, _score(active))


def record_message(agent_input: AgentInput, *, store: CampaignStore | None = None) -> int:
    """L9 hook: explicitly observe a non-legit incoming message once. No text kept."""
    fp = _fp(agent_input)
    if not _taxonomy()[fp.category] or fp.template_hash == EMPTY_TEMPLATE:
        return 0
    active = store if store is not None else default_store()
    return active.add([fp], _score(active), link=(fp.event_hash, agent_input.message_id))


def _preview(fp: Fingerprint) -> str:
    return _PREVIEWS.get(fp.category, "Message pattern.").replace("<BRAND>", fp.claimed_brand or "<BRAND>")


def list_campaigns(*, store: CampaignStore | None = None, as_of: datetime | None = None) -> list[Campaign]:
    """Contract-ready campaign cards; previews are controlled patterns, not quotes."""
    store = store if store is not None else default_store()
    now = utc(as_of or datetime.now(timezone.utc))
    groups: dict[str, list[Member]] = defaultdict(list)
    for member in store.members(as_of=now):
        groups[member.campaign_id].append(member)
    result = []
    for campaign_id, members in groups.items():
        fp = members[0].fingerprint
        times = [datetime.fromisoformat(member.fingerprint.observed_at) for member in members]
        template = _preview(fp)
        result.append(Campaign(campaign_id=campaign_id, claimed_brand=fp.claimed_brand or None, category=fp.category,
                               domain_pattern=fp.domain_pattern or None, count_total=len(members),
                               count_last_24h=sum(now-timedelta(hours=24) <= time <= now for time in times),
                               first_seen=min(times), last_seen=max(times), template=template,
                               redacted_example="Pattern preview: " + template,
                               linked_message_ids=store.links(member.fingerprint.event_hash for member in members)))
    return sorted(result, key=lambda item: (-item.count_total, item.campaign_id))


def match_campaign(args: MatchCampaignArgs, agent_input: AgentInput, *, store: CampaignStore | None = None) -> MatchCampaignResult:
    """Pure lookup. Exclude self/future observations; never increment counts here."""
    if args.message_id != agent_input.message_id:
        raise ValueError("Campaign tool message_id does not match its input")
    query = _fp(agent_input)
    store = store if store is not None else default_store()
    now = utc(agent_input.received_at)
    members = store.members(as_of=now, exclude=query.event_hash)
    if not members or query.template_hash == EMPTY_TEMPLATE:
        return MatchCampaignResult()
    score_fn = _score(store)
    scored = sorted(((score_fn(query, member.fingerprint), member) for member in members),
                    key=lambda pair: (-pair[0], pair[1].fingerprint.event_hash))
    score, closest = scored[0]
    if score < store.threshold:
        return MatchCampaignResult()
    cohort = [member for member in members if member.campaign_id == closest.campaign_id]
    times = [datetime.fromisoformat(member.fingerprint.observed_at) for member in cohort]
    return MatchCampaignResult(campaign_id=closest.campaign_id, similar_last_24h=sum(now-timedelta(hours=24) <= time <= now for time in times),
                               first_seen=min(times), similarity=score, template=_preview(cohort[0].fingerprint))
