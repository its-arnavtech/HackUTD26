"""RDAP domain registration lookup for `check_link` (A10).

Only the registered domain is sent out, never the full link or any message text.
Lookups go through `integrations/cache.py` so replay mode never touches the network.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.contracts import DemoMode
from app.integrations.cache import cached_call

log = logging.getLogger(__name__)

RDAP_BOOTSTRAP_URL = "https://rdap.org/domain/{domain}"
TIMEOUT_S = 4.0


def _fetch(domain: str, client: httpx.Client | None = None) -> dict[str, Any]:
    """Raw lookup, reduced to what we keep: `{"found": bool, "registered_at": iso or None}`.

    Network and server errors raise, so a failed lookup is never recorded as a fixture.
    """
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True)
    try:
        response = client.get(
            RDAP_BOOTSTRAP_URL.format(domain=domain),
            headers={"Accept": "application/rdap+json"},
        )
    finally:
        if own_client:
            client.close()
    if response.status_code == 404:
        return {"found": False, "registered_at": None}
    response.raise_for_status()
    events = response.json().get("events", [])
    registered = next((e.get("eventDate") for e in events if e.get("eventAction") == "registration"), None)
    return {"found": True, "registered_at": registered}


def _through_cache(request: dict[str, Any], fn: Callable[[], dict[str, Any]]) -> Optional[dict[str, Any]]:
    try:
        return cached_call("rdap", request, fn)
    except NotImplementedError:
        # TODO(L1): delete this fallback once cache.py merges; cached_call handles DEMO_MODE itself.
        if get_settings().DEMO_MODE == DemoMode.replay:
            return None
        return fn()


def lookup_registration(domain: str, client: httpx.Client | None = None) -> Optional[dict[str, Any]]:
    """`{"found", "registered_at"}` for a registered domain, or None if the lookup failed or isn't available."""
    try:
        return _through_cache({"domain": domain}, lambda: _fetch(domain, client))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("RDAP lookup failed for %s: %s", domain, type(exc).__name__)
        return None


def domain_age_days(record: Optional[dict[str, Any]], as_of: datetime) -> Optional[int]:
    """Whole days from registration to `as_of`, or None if unknown."""
    if not record or not record.get("registered_at"):
        return None
    try:
        registered = datetime.fromisoformat(record["registered_at"])
    except ValueError:
        return None
    if registered.tzinfo is None:
        registered = registered.replace(tzinfo=timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return max((as_of - registered).days, 0)
