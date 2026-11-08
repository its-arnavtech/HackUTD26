"""Build `data/blocklist.json` from scam-labeled domains in the train split only.

Run from `backend/`: `python -m scripts.build_blocklist [--train PATH]`
Uses A1's saved train split when it exists, otherwise the provisional one in `data/provisional/`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.tools.blocklist import BLOCKLIST_PATH, build_blocklist, default_train_split, write_blocklist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train", type=Path, default=None, help="train split JSONL (default: A1's, else provisional)")
    parser.add_argument("--out", type=Path, default=BLOCKLIST_PATH)
    args = parser.parse_args(argv)

    train = args.train or default_train_split()
    blocklist = build_blocklist(train)
    write_blocklist(blocklist, args.out)
    label = "provisional " if blocklist["provisional"] else ""
    print(f"{len(blocklist['domains'])} domains from {blocklist['messages_read']} {label}train messages -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
