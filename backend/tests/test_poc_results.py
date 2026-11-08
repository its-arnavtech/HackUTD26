"""A8: docs/POC_RESULTS.md covers every gate and its P1 numbers match the committed metrics."""

from __future__ import annotations

import re

from app.config import EVAL_DIR, REPO_ROOT
from app.contracts import BaselineMetrics

DOC = REPO_ROOT / "docs" / "POC_RESULTS.md"


def _gate_rows() -> dict[str, str]:
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (P[1-5]) \|[^|]*\| \*\*(Pass|Fail|Pending|Blocked)\*\* \|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_every_gate_has_a_status():
    assert set(_gate_rows()) == {"P1", "P2", "P3", "P4", "P5"}


def test_p1_numbers_match_baseline_metrics():
    text = DOC.read_text(encoding="utf-8")
    metrics = BaselineMetrics.model_validate_json((EVAL_DIR / "baseline_metrics.json").read_text(encoding="utf-8"))
    assert f"**{metrics.macro_f1:.3f}**" in text
    assert f"**{metrics.false_positive_rate:.3f}**" in text
    for cat in metrics.categories:
        assert f"| `{cat.category}` | {cat.f1:.2f} |" in text


def test_p1_pivot_rule_is_applied_correctly():
    metrics = BaselineMetrics.model_validate_json((EVAL_DIR / "baseline_metrics.json").read_text(encoding="utf-8"))
    row = next(line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("| P1 |"))
    expected_pivot = metrics.macro_f1 >= 0.97
    assert ("None" in row.split("|")[-2]) is (not expected_pivot)
