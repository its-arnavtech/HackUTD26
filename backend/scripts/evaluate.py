"""Score any model with a predict() interface on the test split and the public SMS set, and write eval/metrics.json. A sample mode scores the full agent.

Stub. Filled in by A13. Run from `backend/`: `python -m scripts.evaluate`
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("A13: evaluate")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
