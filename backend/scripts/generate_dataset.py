"""Generate the synthetic message dataset with DeepSeek: messages per category in data/taxonomy.json plus hard legitimate look-alikes, separate prompt sets for train and test, dedupe and a quality check. Writes data/generated/ and its datasheet. DeepSeek never sees a customer message.

Stub. Filled in by A21. Run from `backend/`: `python -m scripts.generate_dataset`
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("A21: generate_dataset")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
