"""Bootstrap tests use synthetic file bytes only, never public SMS examples."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.contracts import DemoMode
from scripts import setup_huggingface as hf

REAL_CACHED_CALL = hf.cache.cached_call


def test_cli_uses_revision_and_environment_for_token(monkeypatch, tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(hf.subprocess, "run", run)
    hf._download("synthetic/repo", "immutable-sha", ["synthetic.txt"], repo_type="dataset", local_dir=tmp_path,
                 env={"HF_TOKEN": "synthetic-secret"})
    command, options = calls[0]
    assert "--token" not in command and "synthetic-secret" not in str(command)
    assert command[command.index("--revision") + 1] == "immutable-sha"
    assert command[command.index("--local-dir") + 1] == str(tmp_path)
    assert options["env"]["HF_TOKEN"] == "synthetic-secret"
    assert options["capture_output"] and options["timeout"] == 1200


def test_cli_failure_does_not_echo_diagnostics(monkeypatch):
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="synthetic-secret"))
    with pytest.raises(RuntimeError) as error:
        hf._download("synthetic/repo", "sha", [], env={})
    assert "synthetic-secret" not in str(error.value)


@pytest.fixture
def bootstrap(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, HF_TOKEN="synthetic-secret", DEMO_MODE=DemoMode.live)
    monkeypatch.setattr(hf, "get_settings", lambda: settings)
    monkeypatch.setattr(hf, "DESTINATION", tmp_path / "public_sms")
    downloads = []
    cache_keys = []
    def stub(service, request, fn, **kwargs):
        cache_keys.append((service, request))
        return fn()
    monkeypatch.setattr(hf.cache, "cached_call", stub)
    class API:
        def __init__(self, token):
            assert token == "synthetic-secret"
        def dataset_info(self, repo):
            assert repo == hf.DATASET_ID
            return SimpleNamespace(sha="dataset-pinned", card_data=SimpleNamespace(to_dict=lambda: {"license": "unknown", "dataset_info": {"splits": [{"name": "train", "num_examples": 2}]}}))
        def model_info(self, repo):
            assert repo == hf.MODEL_ID
            return SimpleNamespace(sha="model-pinned")
    monkeypatch.setattr(hf, "HfApi", API)
    model_cache = tmp_path / "models"
    def download(repo, revision, files, **kwargs):
        downloads.append((repo, revision, files, kwargs))
        target = kwargs.get("local_dir", model_cache)
        for name in files:
            p = target / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"synthetic-artifact")
    monkeypatch.setattr(hf, "_download", download)
    monkeypatch.setattr(hf, "try_to_load_from_cache", lambda repo, name, revision: str(model_cache / name))
    return settings, downloads, cache_keys


def test_downloads_have_provenance_and_no_secret_or_raw_rows(bootstrap):
    _, downloads, cache_keys = bootstrap
    manifest = hf.setup()
    assert len(downloads) == 2
    assert downloads[0][1] == "dataset-pinned" and downloads[1][1] == "model-pinned"
    assert manifest["dataset"]["license_hf_card"] == "unknown"
    assert "external evaluation only" in manifest["dataset"]["usage"]
    assert "synthetic-secret" not in str(manifest) + str(cache_keys)
    assert all("sha256" in f for artifact in manifest.values() for f in artifact["files"])
    assert (hf.DESTINATION / "manifest.json").exists()


def test_real_cache_records_then_replays_without_hub_downloads(bootstrap, monkeypatch):
    settings, downloads, _ = bootstrap
    monkeypatch.setattr(hf.cache, "cached_call", REAL_CACHED_CALL)
    monkeypatch.setattr(hf.cache, "FIXTURES_DIR", hf.DESTINATION.parent / "fixtures")
    settings.DEMO_MODE = DemoMode.record
    recorded = hf.setup()
    assert len(downloads) == 2
    settings.DEMO_MODE = DemoMode.replay
    assert hf.setup() == recorded
    assert len(downloads) == 2


def test_real_replay_miss_never_downloads(bootstrap, monkeypatch):
    settings, downloads, _ = bootstrap
    monkeypatch.setattr(hf.cache, "cached_call", REAL_CACHED_CALL)
    monkeypatch.setattr(hf.cache, "FIXTURES_DIR", hf.DESTINATION.parent / "fixtures")
    settings.DEMO_MODE = DemoMode.replay
    with pytest.raises(hf.cache.FixtureMissingError):
        hf.setup()
    assert not downloads


def test_cached_manifest_requires_intact_files(bootstrap, monkeypatch):
    manifest = hf.setup()
    original = Path(manifest["dataset"]["files"][0]["path"])
    original.write_bytes(b"x" * original.stat().st_size)
    monkeypatch.setattr(hf.cache, "cached_call", lambda *args, **kwargs: manifest)
    with pytest.raises(RuntimeError, match="missing or has changed"):
        hf.setup()


def test_file_hash_is_stable(tmp_path):
    path = tmp_path / "synthetic.txt"
    path.write_bytes(b"synthetic")
    assert hf._file_info(path)["sha256"] == hashlib.sha256(b"synthetic").hexdigest()
