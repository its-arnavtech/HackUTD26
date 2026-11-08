"""Create or rotate the L13 keys in the repo-root `.env`. Never prints a key.

    python -m scripts.auth_keys            # add JWT_PRIVATE_KEY and DATA_ENCRYPTION_KEYS if missing
    python -m scripts.auth_keys --rotate   # new signing key (signs everyone out) and a new
                                           # encryption key in front; old encryption keys stay
                                           # so existing rows still decrypt

Run from `backend/`. `.env` is gitignored; keep it that way.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from app.auth.tokens import generate_private_key_b64
from app.config import REPO_ROOT
from app.crypto import KeyRing, generate_key

ENV_PATH = REPO_ROOT / ".env"


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _get(lines: list[str], name: str) -> str:
    for line in lines:
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def _set(lines: list[str], name: str, value: str) -> list[str]:
    out, done = [], False
    for line in lines:
        if line.startswith(f"{name}="):
            out.append(f"{name}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{name}={value}")
    return out


def main(argv: list[str] | None = None, env_path: Path = ENV_PATH) -> str:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rotate", action="store_true", help="replace the signing key and add a new encryption key")
    args = parser.parse_args(argv)
    lines = _read(env_path)
    changed = []

    kid = _get(lines, "JWT_KEY_ID") or "k1"
    if args.rotate or not _get(lines, "JWT_PRIVATE_KEY"):
        if args.rotate and _get(lines, "JWT_PRIVATE_KEY"):
            n = int(m.group(1)) + 1 if (m := re.fullmatch(r"k(\d+)", kid)) else 2
            kid = f"k{n}"
            lines = _set(lines, "JWT_KEY_ID", kid)
        lines = _set(lines, "JWT_PRIVATE_KEY", generate_private_key_b64())
        changed.append(f"JWT_PRIVATE_KEY (key id {kid})")

    current = _get(lines, "DATA_ENCRYPTION_KEYS")
    if not current:
        lines = _set(lines, "DATA_ENCRYPTION_KEYS", f"k1:{generate_key()}")
        changed.append("DATA_ENCRYPTION_KEYS (k1)")
    elif args.rotate:
        ring = KeyRing.parse(current)
        used = [kid_ for kid_, _ in ring.keys]
        n = max((int(m.group(1)) for k in used if (m := re.fullmatch(r"k(\d+)", k))), default=0) + 1
        lines = _set(lines, "DATA_ENCRYPTION_KEYS", f"k{n}:{generate_key()},{current}")
        changed.append(f"DATA_ENCRYPTION_KEYS (new current key k{n}; {len(used)} older key(s) kept for reading)")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = "Updated " + ", ".join(changed) + f" in {env_path}." if changed else f"Keys already set in {env_path}; nothing changed."
    print(summary)  # names only, never values
    return summary


if __name__ == "__main__":
    main()
