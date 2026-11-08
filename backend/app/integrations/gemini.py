"""Gemini client with Google Search grounding. Filled in by L4 (gate P3).

Receives only the DATA_SPEC.md section 4.1 payload. Every call goes through
`integrations/cache.py`.
"""

from __future__ import annotations

from app.contracts import GeminiInput, GeminiOutput


def grounded_search(query: GeminiInput) -> GeminiOutput:
    """Run the grounded query and return cited sources in our JSON shape. (L4)"""
    raise NotImplementedError("L4: Gemini grounded search")
