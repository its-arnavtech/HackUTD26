"""Generate the synthetic SMS dataset with DeepSeek (A21).

DeepSeek writes messages for every category in `data/taxonomy.json` plus hard
legitimate look-alikes. Train and test come from different prompt sets
(`scripts/dataset_prompts.py`). Then the messages pass a quality filter, are
deduplicated (exact, near-duplicate, and test against train), trimmed to fixed
per-category targets, and given synthetic senders and timestamps.

DeepSeek is used only here, offline. It never sees a customer message.

Every DeepSeek call is cached under `data/generated/cache/`, keyed by a hash of
the request, so reruns are free and give the same output. With the committed
cache, `--offline` rebuilds the dataset without a key.

Run from `backend/`:
    python -m scripts.generate_dataset             # generate (calls DeepSeek on cache misses)
    python -m scripts.generate_dataset --offline   # rebuild from the cache only
    python -m scripts.generate_dataset --dry-run   # show the plan and cache hits

Outputs in `data/generated/`: `messages.jsonl` (the `Message` contract),
`meta.jsonl` (how each message was made), `quality_report.json`. The
hand-written test messages live in `handwritten.jsonl` and are only checked here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import string
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from app.config import DATA_DIR, get_settings
from app.contracts import Message, MessageSource
from scripts.dataset_prompts import (
    LEGIT_HINT,
    LEGIT_SUBTYPE_POOL,
    PROMPT_SETS,
    SCAM_HINT,
    PromptSet,
)

OUT_DIR = DATA_DIR / "generated"
CACHE_DIR = OUT_DIR / "cache"
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
MESSAGES_PATH = OUT_DIR / "messages.jsonl"
META_PATH = OUT_DIR / "meta.jsonl"
HANDWRITTEN_PATH = OUT_DIR / "handwritten.jsonl"
REPORT_PATH = OUT_DIR / "quality_report.json"

GENERATOR_VERSION = 1
SEED = 2026
BATCH_SIZE = 8
OVERGENERATE = 1.3
TEMPERATURE = 1.2
MAX_TOKENS = 6000  # deepseek-flash reasons first, and reasoning counts toward this

# Final messages per category after dedupe and trimming. train_v1 feeds the
# train and validation splits (A1 splits it 70/15 of the total), test_v1 plus
# the hand-written set is the test split (the other 15%).
TARGETS: dict[str, dict[str, int]] = {
    "train_v1": {"legit": 840, "scam_each": 171},
    "test_v1": {"legit": 130, "scam_each": 26},
}
ID_PREFIX = {"train_v1": "tr", "test_v1": "te"}

NEAR_DUP_THRESHOLD = 90  # rapidfuzz ratio on normalized text, within a prompt set
CROSS_SET_THRESHOLD = 85  # stricter: a test message this close to a train message is dropped
MIN_CHARS, MAX_CHARS = 20, 480

# Legit brand pools whose messages mirror a scam category ("hard look-alikes").
HARD_NEGATIVE_POOLS = {"bank", "carrier", "otp", "delivery", "toll", "retail", "recruiter", "personal"}
PERSONAL_POOLS = {"recruiter", "appointment", "community", "personal"}

CENTRAL = timezone(timedelta(hours=-6))
WINDOW_START = datetime(2026, 9, 1, tzinfo=CENTRAL)
WINDOW_DAYS = 67  # through 2026-11-06


class CacheMiss(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Taxonomy and job plan
# ---------------------------------------------------------------------------


def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["categories"]}


@dataclass(frozen=True)
class Job:
    job_id: str
    prompt_set: str
    category: str
    is_scam: bool
    subtype: str
    brand_pool: str
    brand: str
    persona: str
    style: str
    n: int


def category_target(prompt_set: str, category: dict[str, Any]) -> int:
    t = TARGETS[prompt_set]
    return t["scam_each"] if category["is_scam"] else t["legit"]


def plan_jobs(
    taxonomy: dict[str, dict[str, Any]],
    prompt_set: PromptSet,
    *,
    seed: int = SEED,
    overgenerate: float = OVERGENERATE,
    max_jobs_per_category: int | None = None,
) -> list[Job]:
    """Deterministic list of generation calls. Job j's choices depend only on
    (seed, set, category, j), so raising the job count keeps earlier jobs (and
    their cache entries) unchanged."""
    jobs: list[Job] = []
    for cat_id, cat in taxonomy.items():
        n_jobs = math.ceil(category_target(prompt_set.name, cat) * overgenerate / BATCH_SIZE)
        if max_jobs_per_category is not None:
            n_jobs = min(n_jobs, max_jobs_per_category)
        subtypes = cat["subtypes"]
        for j in range(n_jobs):
            rng = random.Random(f"{seed}:{prompt_set.name}:{cat_id}:{j}")
            subtype = subtypes[j % len(subtypes)]
            if cat["is_scam"]:
                pool = cat_id
                brands = prompt_set.brands[cat_id]
                personas = prompt_set.personas_scam
            else:
                pool = LEGIT_SUBTYPE_POOL[subtype]
                brands = prompt_set.legit_brands[pool]
                personas = prompt_set.personas_legit
            jobs.append(
                Job(
                    job_id=f"{prompt_set.name}:{cat_id}:{j:04d}",
                    prompt_set=prompt_set.name,
                    category=cat_id,
                    is_scam=bool(cat["is_scam"]),
                    subtype=subtype,
                    brand_pool=pool,
                    brand=rng.choice(brands),
                    persona=rng.choice(personas),
                    style=rng.choice(prompt_set.styles),
                    n=BATCH_SIZE,
                )
            )
    return jobs


def build_request(job: Job, taxonomy: dict[str, dict[str, Any]], model: str) -> dict[str, Any]:
    ps = PROMPT_SETS[job.prompt_set]
    cat = taxonomy[job.category]
    user = ps.user_template.format(
        category_label=cat["label"],
        label_kind="scam" if job.is_scam else "legitimate, not a scam",
        category_description=cat["description"],
        subtype=job.subtype,
        brand=job.brand,
        persona=job.persona,
        style=job.style,
        n=job.n,
        label_hint=SCAM_HINT if job.is_scam else LEGIT_HINT,
    )
    return {
        "model": model,
        "messages": [{"role": "system", "content": ps.system}, {"role": "user", "content": user}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }


# ---------------------------------------------------------------------------
# Cached DeepSeek calls
# ---------------------------------------------------------------------------


def request_key(request: dict[str, Any]) -> str:
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_path(request: dict[str, Any], cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"{request_key(request)}.json"


def cached_completion(
    request: dict[str, Any],
    call_api: Callable[[dict[str, Any]], str] | None,
    *,
    cache_dir: Path = CACHE_DIR,
    attempts: int = 4,
) -> str:
    """Return the cached response, or call the API, check the response parses,
    and cache it. `call_api=None` means offline: a miss raises CacheMiss."""
    path = cache_path(request, cache_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["response"]
    if call_api is None:
        raise CacheMiss(path.name)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            content = call_api(request)
            if not parse_messages(content):
                failed = cache_dir / "_failed" / f"{path.stem}.{attempt}.txt"
                failed.parent.mkdir(parents=True, exist_ok=True)
                failed.write_text(content or "<empty>", encoding="utf-8")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps({"request": request, "response": content}, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                tmp.replace(path)
                return content
            last_error = ValueError("response had no parseable messages")
        except Exception as exc:  # network, rate limit, server error
            last_error = exc
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"DeepSeek call failed after {attempts} attempts: {type(last_error).__name__}: {last_error}")


def make_deepseek_caller() -> Callable[[dict[str, Any]], str]:
    from openai import OpenAI

    settings = get_settings()
    if settings.DEEPSEEK_API_KEY is None or not settings.DEEPSEEK_API_KEY.get_secret_value():
        raise SystemExit("DEEPSEEK_API_KEY is not set in .env. Use --offline to rebuild from the cache.")
    client = OpenAI(
        api_key=settings.DEEPSEEK_API_KEY.get_secret_value(),
        base_url=settings.DEEPSEEK_BASE_URL,
        timeout=180,
        max_retries=0,
    )

    def call(request: dict[str, Any]) -> str:
        resp = client.chat.completions.create(**request)
        return resp.choices[0].message.content or ""

    return call


# ---------------------------------------------------------------------------
# Parsing, cleaning, quality
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_messages(content: str) -> list[str]:
    """Pull the list of message strings out of a model response. Never raises."""
    text = _FENCE.sub("", (content or "").strip())
    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    items: Any = None
    if isinstance(data, dict):
        items = data.get("messages")
        if items is None:
            items = next((v for v in data.values() if isinstance(v, list)), None)
    elif isinstance(data, list):
        items = data
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):  # tolerate [{"text": ...}]
            item = item.get("text") or item.get("message")
        if isinstance(item, str) and item.strip():
            out.append(" ".join(item.split()))
    return out


# 10-digit US numbers with separators, or +1 followed by 10 digits.
_PHONE_SEP = re.compile(r"(?<![\w])(\+?1[-.\s])?\(?(\d{3})\)?[-.\s](\d{3})[-.\s](\d{4})(?!\d)")
_PHONE_E164 = re.compile(r"(?<![\w+])\+1(\d{3})(\d{3})(\d{4})(?!\d)")


def _is_fictional(exchange: str, line: str) -> bool:
    return exchange == "555" and line.startswith("01")


def fictionalize_phones(text: str) -> tuple[str, int]:
    """Rewrite any phone number outside 555-01XX into that fictional range, so a
    model-invented number can never be a real one. Returns (text, count)."""
    count = 0

    def fake_line(digits: str) -> str:
        return f"01{int(hashlib.sha256(digits.encode()).hexdigest(), 16) % 100:02d}"

    def sub_sep(m: re.Match[str]) -> str:
        nonlocal count
        prefix, area, exch, line = m.group(1) or "", m.group(2), m.group(3), m.group(4)
        if _is_fictional(exch, line):
            return m.group(0)
        count += 1
        return f"{prefix}{area}-555-{fake_line(area + exch + line)}"

    def sub_e164(m: re.Match[str]) -> str:
        nonlocal count
        area, exch, line = m.group(1), m.group(2), m.group(3)
        if _is_fictional(exch, line):
            return m.group(0)
        count += 1
        return f"+1{area}555{fake_line(area + exch + line)}"

    text = _PHONE_SEP.sub(sub_sep, text)
    text = _PHONE_E164.sub(sub_e164, text)
    return text, count


_REFUSAL = re.compile(r"\b(as an ai|language model|i can(?:'|no)t (?:help|create|write)|i'm sorry, but)\b", re.I)
_PLACEHOLDER = re.compile(r"\[[A-Za-z][A-Za-z _]{1,30}\]|\{[A-Za-z_]{2,30}\}|<(?:link|url|name|number|code)>", re.I)
_LABEL_LEAK = re.compile(r"\b(scam|scammer|phishing|fraudster|smishing)\b", re.I)


def quality_issue(text: str, is_scam: bool) -> str | None:
    """Reason a message fails the quality check, or None if it passes."""
    if len(text) < MIN_CHARS:
        return "too_short"
    if len(text) > MAX_CHARS:
        return "too_long"
    if _REFUSAL.search(text):
        return "refusal"
    if _PLACEHOLDER.search(text):
        return "placeholder"
    if is_scam and _LABEL_LEAK.search(text):
        return "label_leak"  # a scam that calls itself a scam would teach the wrong cue
    return None


_URL = re.compile(r"https?://\S+|www\.\S+|\b[\w-]+\.(?:com|net|org|co|info|xyz|top|us|io|link|app|site|online)\b\S*", re.I)


def normalize(text: str) -> str:
    t = _URL.sub(" url ", text.lower())
    t = re.sub(r"\d", "0", t)
    t = re.sub(r"[^a-z0 ]+", " ", t)
    return " ".join(t.split())


def has_url(text: str) -> bool:
    return bool(_URL.search(text))


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    text: str
    job: Job
    norm: str


def dedupe(cands: list[Candidate], threshold: int = NEAR_DUP_THRESHOLD) -> tuple[list[Candidate], Counter[str]]:
    """Greedy, order-preserving: keep a message unless it exactly or nearly
    repeats one already kept (in any category, since a cross-category repeat is
    label noise)."""
    kept: list[Candidate] = []
    kept_norms: list[str] = []
    seen: set[str] = set()
    stats: Counter[str] = Counter()
    for c in cands:
        if c.norm in seen:
            stats["exact_duplicate"] += 1
            continue
        if kept_norms and process.extractOne(c.norm, kept_norms, scorer=fuzz.ratio, score_cutoff=threshold):
            stats["near_duplicate"] += 1
            continue
        seen.add(c.norm)
        kept.append(c)
        kept_norms.append(c.norm)
    return kept, stats


def drop_close_to(
    cands: list[Candidate], reference_norms: list[str], threshold: int = CROSS_SET_THRESHOLD
) -> tuple[list[Candidate], int]:
    """Drop candidates that are near-duplicates of any reference text (test vs train)."""
    if not reference_norms:
        return cands, 0
    ref_set = set(reference_norms)
    kept = [
        c
        for c in cands
        if c.norm not in ref_set
        and not process.extractOne(c.norm, reference_norms, scorer=fuzz.ratio, score_cutoff=threshold)
    ]
    return kept, len(cands) - len(kept)


# ---------------------------------------------------------------------------
# Senders and timestamps (synthetic, assigned by rule)
# ---------------------------------------------------------------------------

_EMAIL_PROVIDERS = ("gmail.com", "icloud.com", "outlook.com", "yahoo.com")


def assign_sender(message_id: str, category: str, is_scam: bool, brand_pool: str, seed: int = SEED) -> str:
    """Overlapping distributions on purpose, so the sender alone can't give the label away."""
    rng = random.Random(f"{seed}:sender:{message_id}")
    if is_scam:
        weights = {"long": 0.95, "email": 0.05, "short": 0.0} if category == "conversation_lure" else {"long": 0.65, "email": 0.15, "short": 0.20}
    elif brand_pool in PERSONAL_POOLS:
        weights = {"long": 0.75, "email": 0.0, "short": 0.25}
    else:
        weights = {"long": 0.20, "email": 0.0, "short": 0.80}
    kind = rng.choices(list(weights), weights=list(weights.values()))[0]
    if kind == "long":
        return f"+15550{rng.randint(100000, 199999)}"
    if kind == "short":
        return str(rng.randint(20000, 99999)) if rng.random() < 0.7 else str(rng.randint(200000, 999999))
    token = "".join(rng.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{token}@{rng.choice(_EMAIL_PROVIDERS)}"


def assign_received_at(message_id: str, seed: int = SEED) -> datetime:
    rng = random.Random(f"{seed}:time:{message_id}")
    day = WINDOW_START + timedelta(days=rng.randrange(WINDOW_DAYS))
    return day.replace(hour=rng.randint(7, 22), minute=rng.randrange(60))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run_jobs(
    jobs: list[Job],
    taxonomy: dict[str, dict[str, Any]],
    model: str,
    call_api: Callable[[dict[str, Any]], str] | None,
    workers: int,
) -> dict[str, list[str]]:
    """Run every job (cache first) and return job_id -> parsed messages."""

    def one(job: Job) -> tuple[str, list[str] | None, str | None]:
        try:
            content = cached_completion(build_request(job, taxonomy, model), call_api)
        except CacheMiss:
            raise
        except RuntimeError as exc:  # one bad job doesn't sink the run; it's reported
            return job.job_id, None, str(exc)
        return job.job_id, parse_messages(content), None

    done = 0
    out: dict[str, list[str]] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for job_id, msgs, error in pool.map(one, jobs):
            if msgs is None:
                failures.append(f"{job_id}: {error}")
            else:
                out[job_id] = msgs
            done += 1
            if done % 25 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} calls done, {len(failures)} failed", flush=True)
    for line in failures:
        print(f"  FAILED {line}", flush=True)
    return out


def build_set(
    prompt_set: str,
    jobs: list[Job],
    responses: dict[str, list[str]],
    taxonomy: dict[str, dict[str, Any]],
    reference_norms: list[str],
) -> tuple[list[tuple[Message, dict[str, Any]]], dict[str, Any]]:
    stats: Counter[str] = Counter()
    cands: list[Candidate] = []
    for job in jobs:  # job order is deterministic, so output is too
        if job.job_id not in responses:
            stats["failed_jobs"] += 1
        for raw in responses.get(job.job_id, []):
            stats["raw"] += 1
            text, n_phones = fictionalize_phones(raw)
            stats["phones_rewritten"] += n_phones
            issue = quality_issue(text, job.is_scam)
            if issue:
                stats[f"rejected_{issue}"] += 1
                continue
            cands.append(Candidate(text=text, job=job, norm=normalize(text)))
    stats["passed_quality"] = len(cands)

    cands, dup_stats = dedupe(cands)
    stats.update(dup_stats)
    cands, n_cross = drop_close_to(cands, reference_norms)
    stats["cross_set_duplicate"] = n_cross

    # Trim each category to its target with a seeded sample, keeping order.
    by_cat: dict[str, list[Candidate]] = {c: [] for c in taxonomy}
    for c in cands:
        by_cat[c.job.category].append(c)
    shortfall: dict[str, int] = {}
    final: list[Candidate] = []
    for cat_id, items in by_cat.items():
        target = category_target(prompt_set, taxonomy[cat_id])
        if len(items) > target:
            rng = random.Random(f"{SEED}:trim:{prompt_set}:{cat_id}")
            keep = sorted(rng.sample(range(len(items)), target))
            stats["trimmed"] += len(items) - target
            items = [items[i] for i in keep]
        elif len(items) < target:
            shortfall[cat_id] = target - len(items)
        final.extend(items)

    records: list[tuple[Message, dict[str, Any]]] = []
    for k, c in enumerate(final, start=1):
        mid = f"{ID_PREFIX[prompt_set]}_{k:05d}"
        msg = Message(
            message_id=mid,
            text=c.text,
            sender=assign_sender(mid, c.job.category, c.job.is_scam, c.job.brand_pool),
            received_at=assign_received_at(mid),
            is_scam=c.job.is_scam,
            category=c.job.category,
            source=MessageSource.generated,
            prompt_set=prompt_set,
        )
        meta = {
            "message_id": mid,
            "job_id": c.job.job_id,
            "subtype": c.job.subtype,
            "brand": c.job.brand,
            "persona": c.job.persona,
            "style": c.job.style,
            "hard_negative": (not c.job.is_scam) and c.job.brand_pool in HARD_NEGATIVE_POOLS,
        }
        records.append((msg, meta))

    report = {
        "jobs": len(jobs),
        "pipeline": dict(sorted(stats.items())),
        "shortfall": shortfall,
        **describe([m for m, _ in records], [meta for _, meta in records]),
    }
    return records, report


def describe(messages: list[Message], metas: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    n = len(messages)
    cats = Counter(m.category for m in messages)
    legit = sum(1 for m in messages if m.is_scam is False)
    lengths = sorted(len(m.text) for m in messages) or [0]
    url_rate = {
        cat: round(sum(1 for m in messages if m.category == cat and has_url(m.text)) / cnt, 3)
        for cat, cnt in sorted(cats.items())
    }
    senders = Counter(
        "email" if "@" in m.sender else "long_code" if m.sender.startswith("+") else "short_code" if m.sender.isdigit() else "other"
        for m in messages
    )
    out: dict[str, Any] = {
        "messages": n,
        "per_category": dict(sorted(cats.items())),
        "legit_share": round(legit / n, 3) if n else 0.0,
        "length_chars": {"min": lengths[0], "median": lengths[len(lengths) // 2], "max": lengths[-1]},
        "url_rate_per_category": url_rate,
        "sender_types": dict(sorted(senders.items())),
    }
    if metas is not None:
        out["hard_negatives"] = sum(1 for m in metas if m["hard_negative"])
    return out


def load_handwritten(path: Path = HANDWRITTEN_PATH) -> list[Message]:
    if not path.exists():
        return []
    return [Message.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_handwritten(messages: list[Message], taxonomy: dict[str, dict[str, Any]]) -> list[str]:
    """Problems with the hand-written set (empty list = fine)."""
    problems: list[str] = []
    ids = [m.message_id for m in messages]
    if len(ids) != len(set(ids)):
        problems.append("duplicate message_id")
    for m in messages:
        if m.source != MessageSource.handwritten or m.prompt_set != "handwritten":
            problems.append(f"{m.message_id}: source and prompt_set must be 'handwritten'")
        if m.category not in taxonomy:
            problems.append(f"{m.message_id}: unknown category {m.category!r}")
        elif m.is_scam != taxonomy[m.category]["is_scam"]:
            problems.append(f"{m.message_id}: is_scam disagrees with the taxonomy")
        if fictionalize_phones(m.text)[1]:
            problems.append(f"{m.message_id}: phone number outside 555-01XX")
    return problems


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_model(cli_model: str | None) -> str:
    if cli_model:
        return cli_model
    env_model = get_settings().DEEPSEEK_MODEL
    if env_model:
        return env_model
    if REPORT_PATH.exists():  # offline rebuild on a machine without .env
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))["model"]
    raise SystemExit("Set DEEPSEEK_MODEL in .env or pass --model.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--offline", action="store_true", help="use only cached responses; fail on a miss")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and cache hits, call nothing")
    parser.add_argument("--sets", default="train_v1,test_v1", help="comma-separated prompt sets")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default=None, help="DeepSeek model (default: DEEPSEEK_MODEL)")
    parser.add_argument("--max-jobs-per-category", type=int, default=None, help="smoke runs only; writes nothing")
    args = parser.parse_args(argv)

    taxonomy = load_taxonomy()
    model = resolve_model(args.model)
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    unknown = [s for s in sets if s not in PROMPT_SETS]
    if unknown:
        parser.error(f"unknown prompt set(s): {unknown}")
    if "test_v1" in sets and "train_v1" not in sets:
        parser.error("test_v1 is deduplicated against train_v1, so build both together")

    plans = {s: plan_jobs(taxonomy, PROMPT_SETS[s], max_jobs_per_category=args.max_jobs_per_category) for s in sets}
    for s, jobs in plans.items():
        hits = sum(1 for j in jobs if cache_path(build_request(j, taxonomy, model)).exists())
        print(f"{s}: {len(jobs)} calls planned, {hits} cached, {len(jobs) - hits} to call")
    if args.dry_run:
        return 0

    call_api = None if args.offline else make_deepseek_caller()
    responses: dict[str, dict[str, list[str]]] = {}
    for s, jobs in plans.items():
        print(f"Running {s} with {model} ...", flush=True)
        try:
            responses[s] = run_jobs(jobs, taxonomy, model, call_api, args.workers)
        except CacheMiss as miss:
            raise SystemExit(f"--offline: no cached response for {miss}. Run without --offline to generate it.")

    if args.max_jobs_per_category is not None:
        for s, jobs in plans.items():
            for job in jobs:
                print(f"\n[{job.job_id}] {job.subtype} / {job.brand}")
                for text in responses[s].get(job.job_id, ["<failed>"])[:3]:
                    print(f"  - {text}")
        print("\nSmoke run: nothing written.")
        return 0

    report: dict[str, Any] = {
        "generator_version": GENERATOR_VERSION,
        "model": model,
        "seed": SEED,
        "batch_size": BATCH_SIZE,
        "temperature": TEMPERATURE,
        "targets": TARGETS,
        "thresholds": {"near_duplicate": NEAR_DUP_THRESHOLD, "cross_set": CROSS_SET_THRESHOLD, "min_chars": MIN_CHARS, "max_chars": MAX_CHARS},
        "sets": {},
    }
    all_records: list[tuple[Message, dict[str, Any]]] = []
    train_norms: list[str] = []
    for s in sets:  # train_v1 first, so test_v1 is checked against it
        records, set_report = build_set(s, plans[s], responses[s], taxonomy, train_norms if s == "test_v1" else [])
        if s == "train_v1":
            train_norms = [normalize(m.text) for m, _ in records]
        report["sets"][s] = set_report
        all_records.extend(records)

    handwritten = load_handwritten()
    problems = check_handwritten(handwritten, taxonomy)
    report["handwritten"] = {**describe(handwritten), "problems": problems}
    all_messages = [m for m, _ in all_records]
    report["total"] = describe(all_messages + handwritten)

    write_jsonl(MESSAGES_PATH, (m.model_dump(mode="json") for m in all_messages))
    write_jsonl(META_PATH, (meta for _, meta in all_records))
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\nWrote {len(all_messages)} generated messages to {MESSAGES_PATH}")
    for s in sets:
        r = report["sets"][s]
        print(f"  {s}: {r['messages']} messages, legit share {r['legit_share']}, shortfall {r['shortfall'] or 'none'}")
    print(f"  handwritten: {len(handwritten)} messages, {len(problems)} problems")
    print(f"  total: {report['total']['messages']}, legit share {report['total']['legit_share']}")
    if problems:
        print("Hand-written problems:\n  " + "\n  ".join(problems))
    shortfalls = any(report["sets"][s]["shortfall"] for s in sets)
    return 1 if problems or shortfalls else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
