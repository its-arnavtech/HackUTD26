"""Build `data/blocklist.json` from scam-labeled domains in A1's train split only.

Run from `backend/`: `python -m scripts.build_blocklist`
The split is `data/generated/splits.json`, read through `classifier.baseline.load_split()`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.tools.blocklist import BLOCKLIST_PATH, build_blocklist, write_blocklist


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=BLOCKLIST_PATH)
    args = parser.parse_args(argv)

    blocklist = build_blocklist()
    write_blocklist(blocklist, args.out)
    print(f"{len(blocklist['domains'])} domains from {blocklist['messages_read']} train messages -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
