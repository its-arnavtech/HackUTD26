"""Download held-out public SMS and cache a small English base model.

From backend: python -m scripts.setup_huggingface
Login yourself first with .venv\\Scripts\\hf.exe auth login; set HF_TOKEN in
repo .env. Credentials are passed via environment, never command arguments.
No public message text is printed, committed, or submitted to a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, try_to_load_from_cache

from app.config import DATA_DIR, get_settings
from app.integrations import cache

DATASET_ID = "ucirvine/sms_spam"
MODEL_ID = "distilbert/distilbert-base-uncased"
DATASET_FILES = ["README.md", "plain_text/train-00000-of-00001.parquet"]
MODEL_FILES = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "README.md", "LICENSE"]
DESTINATION = DATA_DIR / "raw" / "public_sms"


def _download(repo: str, revision: str, files: list[str], *, repo_type: str = "model",
              local_dir: Path | None = None, env: dict[str, str]) -> None:
    hf = Path(sys.executable).parent / ("hf.exe" if os.name == "nt" else "hf")
    command = [str(hf), "download", repo, *files, "--repo-type", repo_type, "--revision", revision]
    if local_dir is not None:
        command.extend(["--local-dir", str(local_dir)])
    completed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
    if completed.returncode:
        # CLI/provider diagnostics may contain auth context. Don't echo them.
        raise RuntimeError(f"hf download failed for {repo}; exit={completed.returncode}")


def _file_info(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def setup() -> dict[str, Any]:
    settings = get_settings()
    env = dict(os.environ)
    if settings.HF_TOKEN and settings.HF_TOKEN.get_secret_value():
        env["HF_TOKEN"] = settings.HF_TOKEN.get_secret_value()
    # HF auth login is performed by the human. Existing CLI login is also valid.
    request = {"operation": "setup", "dataset": DATASET_ID, "model": MODEL_ID,
               "dataset_files": DATASET_FILES, "model_files": MODEL_FILES}

    def invoke() -> dict[str, Any]:
        api = HfApi(token=env.get("HF_TOKEN"))
        dataset = api.dataset_info(DATASET_ID)
        model = api.model_info(MODEL_ID)
        if not dataset.sha or not model.sha:
            raise RuntimeError("Hub did not return immutable revisions")
        print("Downloading public SMS for external evaluation only (no rows printed).", flush=True)
        _download(DATASET_ID, dataset.sha, DATASET_FILES, repo_type="dataset", local_dir=DESTINATION, env=env)
        print("Caching DistilBERT weights, config and tokenizer.", flush=True)
        _download(MODEL_ID, model.sha, MODEL_FILES, env=env)
        model_paths = []
        for name in MODEL_FILES:
            cached = try_to_load_from_cache(MODEL_ID, name, revision=model.sha)
            if not isinstance(cached, str):
                raise RuntimeError(f"Missing cached model file: {name}")
            model_paths.append(_file_info(Path(cached)))
        card = dataset.card_data.to_dict() if dataset.card_data else {}
        return {
            "dataset": {"id": DATASET_ID, "revision": dataset.sha,
                        "license_hf_card": card.get("license", "unknown"),
                        "license_upstream": "CC BY 4.0", "upstream_url": "https://archive.ics.uci.edu/dataset/228/sms+spam+collection",
                        "dataset_info": card.get("dataset_info", {}),
                        "usage": "external evaluation only; never train, tune, prompt, seed campaigns or blocklists",
                        "files": [_file_info(DESTINATION / name) for name in DATASET_FILES]},
            "model": {"id": MODEL_ID, "revision": model.sha, "license": "Apache-2.0",
                      "parameters_approx": 67_000_000,
                      "reason": "Small English general-purpose encoder with no SMS-spam fine-tuning; L7 can add a classification head using synthetic training data only.",
                      "files": model_paths},
        }

    result = cache.cached_call("huggingface", request, invoke, mode=settings.DEMO_MODE)
    # Replay of a metadata fixture is insufficient if the artifact is absent.
    for artifact in (result["dataset"], result["model"]):
        for info in artifact["files"]:
            path = Path(info["path"])
            if not path.is_file() or path.stat().st_size != info["bytes"] or _file_info(path)["sha256"] != info["sha256"]:
                raise RuntimeError("Cached HF artifact is missing or has changed; download in live mode")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    (DESTINATION / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    try:
        result = setup()
        # Aggregate provenance only, never raw rows or auth data.
        for kind, artifact in result.items():
            print(json.dumps({"artifact": kind, "id": artifact["id"], "revision": artifact["revision"],
                              "bytes": sum(file["bytes"] for file in artifact["files"])}))
        print(f"Manifest: {DESTINATION / 'manifest.json'}")
        return 0
    except Exception as exc:
        print(f"HF setup failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
