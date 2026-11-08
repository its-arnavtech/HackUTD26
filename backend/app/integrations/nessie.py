"""Capital One Nessie client. Filled in by A2 (gate P4).

Confirm field names against the Nessie docs on first call (DATA_SPEC.md
section 6) and adjust here, not in the tools. Every call goes through
`integrations/cache.py`.
"""

from __future__ import annotations

from typing import Any


class NessieClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def get_customers(self) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie customers")

    def create_customer(self, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create customer")

    def get_accounts(self, customer_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie accounts")

    def create_account(self, customer_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create account")

    def get_purchases(self, account_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie purchases")

    def create_purchase(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create purchase")

    def get_transfers(self, account_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie transfers")

    def create_transfer(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create transfer")

    def get_bills(self, account_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie bills")

    def create_bill(self, account_id: str, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create bill")

    def get_merchants(self) -> list[dict[str, Any]]:
        raise NotImplementedError("A2: Nessie merchants")

    def create_merchant(self, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("A2: create merchant")
