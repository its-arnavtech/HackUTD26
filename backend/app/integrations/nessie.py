"""Capital One Nessie client (A2, gate P4).

Every call goes through `integrations/cache.py`. Field names were checked against
the live API on 2026-11-07 (DATA_SPEC.md section 6, differences in CHANGELOG
Decisions) and are normalized here, not in the tools:

- Some objects come back with `id` instead of `_id`; both become `_id`.
- A list GET with nothing in it answers 404 "No ... found"; that becomes `[]`.
  Any other 404 still raises.
- Transfers listed under an account carry no `payer_id` or `payee_id`, and dates
  have no time of day. Both are filled in from `data/nessie_seed.json`, which the
  seed script writes, so the tools see the DATA_SPEC fields plus `at`.
- Creating a transfer accepts only `transaction_date`, `status`, `amount` and
  `description`; there is no way to name the receiving account.
- Purchases have no time of day either; `at` comes from the manifest's
  `purchase_times` (the planted $900 purchase), otherwise None.
- There is no DELETE for purchases.

The API key is sent as a query parameter and never appears in cache keys, logs
or error messages.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import DATA_DIR, get_settings
from app.contracts import DemoMode
from app.integrations.cache import FixtureMissingError, cached_call

log = logging.getLogger(__name__)

SEED_PATH = DATA_DIR / "nessie_seed.json"
TIMEOUT_S = 15.0

# Plain http on this host answers 502 (checked 2026-11-07); https works.
_INSECURE_HOST = "http://api.nessieisreal.com"

# An empty list comes back as 404 "No transfers found for this account" (checked 2026-11-07).
_EMPTY_LIST = re.compile(r"\bNo \w[\w ]* found\b", re.IGNORECASE)


class NessieError(RuntimeError):
    pass


class NessieReplayMiss(NessieError):
    """Replay mode asked for a Nessie response that was never recorded."""


def _normalize(obj: dict[str, Any]) -> dict[str, Any]:
    if "_id" not in obj and "id" in obj:
        obj = {"_id": obj["id"], **{k: v for k, v in obj.items() if k != "id"}}
    return obj


def load_seed(path: Path = SEED_PATH) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class NessieClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        http: httpx.Client | None = None,
        transfer_details: dict[str, dict[str, Any]] | None = None,
        purchase_times: dict[str, str] | None = None,
        mode: DemoMode | str | None = None,
    ) -> None:
        """`mode` overrides `DEMO_MODE` for this client's calls (tests, scripts).
        `purchase_times` maps a purchase id to its exact ISO time from the seed manifest."""
        self._api_key = api_key
        self.mode = mode
        if base_url.startswith(_INSECURE_HOST):
            base_url = "https://" + base_url[len("http://") :]
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=TIMEOUT_S)
        self.transfer_details = dict(transfer_details or {})
        self.purchase_times = dict(purchase_times or {})

    # -- transport ---------------------------------------------------------

    def _send(self, method: str, path: str, body: dict[str, Any] | None, *, is_list: bool = False) -> Any:
        try:
            response = self._http.request(method, self.base_url + path, params={"key": self._api_key}, json=body)
        except httpx.HTTPError as exc:
            raise NessieError(f"{method} {path}: {type(exc).__name__}") from None
        if is_list and response.status_code == 404 and _EMPTY_LIST.search(response.text):
            return []
        if response.status_code >= 400:
            raise NessieError(f"{method} {path}: HTTP {response.status_code} {response.text[:200]}")
        return response.json() if response.content else None

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, is_list: bool = False) -> Any:
        request = {"method": method, "path": path, "body": body}
        try:
            return cached_call("nessie", request, lambda: self._send(method, path, body, is_list=is_list), mode=self.mode)
        except FixtureMissingError:
            raise NessieReplayMiss(f"no recorded Nessie response for {method} {path}") from None

    def _get_list(self, path: str) -> list[dict[str, Any]]:
        data = self._request("GET", path, is_list=True)
        return [_normalize(item) for item in data or []]

    def _create(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request("POST", path, body) or {}
        created = data.get("objectCreated", data) if isinstance(data, dict) else {}
        return _normalize(created)

    # -- customers and accounts ---------------------------------------------

    def get_customers(self) -> list[dict[str, Any]]:
        return self._get_list("/customers")

    def create_customer(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._create("/customers", body)

    def get_accounts(self, customer_id: str) -> list[dict[str, Any]]:
        return self._get_list(f"/customers/{customer_id}/accounts")

    def create_account(self, customer_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._create(f"/customers/{customer_id}/accounts", body)

    # -- activity ----------------------------------------------------------

    def get_purchases(self, account_id: str) -> list[dict[str, Any]]:
        """Purchases, each with `at`: its exact time from the seed manifest, or None (Nessie keeps only the date)."""
        return [{**p, "at": self.purchase_times.get(p.get("_id", ""))} for p in self._get_list(f"/accounts/{account_id}/purchases")]

    def create_purchase(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._create(f"/accounts/{account_id}/purchases", body)

    # Live Nessie has no DELETE for purchases (403 "Missing Authentication Token", checked 2026-11-07).

    def get_transfers(self, account_id: str) -> list[dict[str, Any]]:
        return [self._with_transfer_details(t, account_id) for t in self._get_list(f"/accounts/{account_id}/transfers")]

    def create_transfer(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._with_transfer_details(self._create(f"/accounts/{account_id}/transfers", body), account_id, body)

    def _with_transfer_details(
        self, transfer: dict[str, Any], account_id: str, sent: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        known = self.transfer_details.get(transfer.get("_id", ""), {})
        out = dict(transfer)
        out["payer_id"] = out.get("payer_id") or known.get("payer_id") or (account_id if sent else None)
        out["payee_id"] = out.get("payee_id") or known.get("payee_id") or (sent or {}).get("payee_id")
        out["at"] = known.get("at")
        return out

    def get_bills(self, account_id: str) -> list[dict[str, Any]]:
        return self._get_list(f"/accounts/{account_id}/bills")

    def create_bill(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._create(f"/accounts/{account_id}/bills", body)

    # -- merchants ---------------------------------------------------------

    def get_merchants(self) -> list[dict[str, Any]]:
        return self._get_list("/merchants")

    def get_merchant(self, merchant_id: str) -> dict[str, Any]:
        return _normalize(self._request("GET", f"/merchants/{merchant_id}") or {})

    def create_merchant(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._create("/merchants", body)


def transfer_details_from_seed(seed: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`transfer_id -> {payer_id, payee_id, at}` from the seed manifest."""
    if not seed:
        return {}
    return {t["id"]: {k: t.get(k) for k in ("payer_id", "payee_id", "at")} for t in seed.get("transfers", {}).values()}


def purchase_times_from_seed(seed: Optional[dict[str, Any]]) -> dict[str, str]:
    """`purchase_id -> ISO time` from the seed manifest (the planted purchase)."""
    return dict((seed or {}).get("purchase_times", {}))


def client_from_settings(seed_path: Path = SEED_PATH) -> NessieClient:
    settings = get_settings()
    key = settings.NESSIE_API_KEY.get_secret_value() if settings.NESSIE_API_KEY else ""
    if not key and settings.DEMO_MODE != DemoMode.replay:
        raise NessieError("NESSIE_API_KEY is not set in .env")
    seed = load_seed(seed_path)
    return NessieClient(
        key,
        settings.NESSIE_BASE_URL,
        transfer_details=transfer_details_from_seed(seed),
        purchase_times=purchase_times_from_seed(seed),
    )
