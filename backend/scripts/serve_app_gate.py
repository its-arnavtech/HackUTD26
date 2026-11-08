"""Serve the real app for the authored G2 record/replay browser gate.

Uses the locally produced, frozen L7 v2 artifact. No evaluation is run. Campaign
fingerprints start from the training split for each run; public search is an
explicitly unavailable optional check. Replay permits loopback sockets only.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.agent import registry
from app.agent.registry import ToolCall
from app.classifier.hybrid import MODEL_PATH
from app.config import DATA_DIR, get_settings
from app.tools import campaign
from app.tools.campaign_store import CampaignStore
from app.integrations import cache

FIXTURES = DATA_DIR / "fixtures" / "app_gate"
PROFILE = "authored-app-l7-v2-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["record", "replay"])
    parser.add_argument("--port", type=int, default=8022)
    args = parser.parse_args()
    if not MODEL_PATH.exists():
        raise SystemExit("Missing local L7 v2 artifact. Reproduce it with python -m scripts.train_public_classifier; do not run evaluation.")
    model_hash = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    profile_path = FIXTURES / "profile.json"
    if args.mode == "replay":
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if profile["profile"] != PROFILE or profile["model_sha256"] != model_hash:
            raise SystemExit("Replay profile/model mismatch. Use the same frozen local artifact as the recording.")
    else:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps({"profile": PROFILE, "model_sha256": model_hash,
            "classifier": "frozen local L7 v2", "public_search": "explicitly unavailable",
            "messages": ["msg_0001", "msg_0003", "msg_0101"], "acceptance": "see eval/app_gate_record.json and app_gate_replay.json"}, indent=2)+"\n", encoding="utf-8")

    original_call = registry.call_tool
    def call(name, tool_args, agent_input, **kwargs):
        if name == "public_scam_reports":
            return ToolCall(name=name, args=tool_args, ok=False,
                            error={"type": "unavailable", "message": "Public search is not part of this app gate."})
        return original_call(name, tool_args, agent_input, **kwargs)

    def local(host):
        if host is None or host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    original_connect, original_resolve = socket.socket.connect, socket.getaddrinfo
    def connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            raise AssertionError("App replay blocked an outbound network connection")
        return original_connect(sock, address)
    def resolve(host, *a, **kw):
        if not local(host):
            raise AssertionError("App replay blocked outbound DNS resolution")
        return original_resolve(host, *a, **kw)

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "DEMO_MODE": args.mode, "USE_MOCKS": "false", "MOCK_ROUTES": "", "LIVE_ROUTES": "",
            "PHONE_HASH_SALT": "g2-authored-synthetic-demo", "GEMINI_API_KEY": "", "GEMINI_MODEL": "",
            "NEMOTRON_MODEL": "nvidia/nemotron-3.5-bolt-e4b", "NEMOTRON_PROTOCOL": "native",
            "NEMOTRON_BASE_URL": "https://integrate.api.nvidia.com/v1", "NEMOTRON_MAX_TOKENS": "2048",
            "NESSIE_BASE_URL": "https://api.nessieisreal.com", "LOG_LEVEL": "WARNING",
        }))
        get_settings.cache_clear()
        temporary = stack.enter_context(TemporaryDirectory(prefix="sentinel-app-gate-"))
        store = CampaignStore(Path(temporary) / "campaigns.sqlite")
        stack.callback(store.close)
        train, validation = campaign.load_training_validation(DATA_DIR / "generated", splits_path=campaign.SPLITS_PATH)
        campaign.calibrate_threshold(train, validation, store=store, splits_path=campaign.SPLITS_PATH)
        campaign.seed_campaigns(train, store=store, splits_path=campaign.SPLITS_PATH)
        stack.enter_context(patch.object(campaign, "default_store", return_value=store))
        stack.enter_context(patch.object(cache, "FIXTURES_DIR", FIXTURES))
        stack.enter_context(patch.object(registry, "call_tool", side_effect=call))
        if args.mode == "replay":
            stack.enter_context(patch.object(socket.socket, "connect", connect))
            stack.enter_context(patch.object(socket, "getaddrinfo", side_effect=resolve))
        from app.main import app
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
