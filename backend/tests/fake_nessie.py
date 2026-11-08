"""In-memory Nessie behind an httpx MockTransport, shaped like the live API (checked 2026-11-07).

Like the real service, POSTs answer `{"code", "message", "objectCreated"}`, IDs are
UUIDs, transfer listings carry `id` but no `payer_id` or `payee_id`, an empty
transfer list answers 404 "No transfers found for this account", and purchase
amounts are stored as whole dollars (49.30 reads back as 49).
"""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from typing import Any

import httpx

API_KEY = "test-key-not-real"


class FakeNessie:
    def __init__(self, *, truncate_purchase_amounts: bool = True, empty_transfers_404: bool = True) -> None:
        self.truncate_purchase_amounts = truncate_purchase_amounts
        self.empty_transfers_404 = empty_transfers_404
        self.customers: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.merchants: dict[str, dict[str, Any]] = {}
        self.children: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        self.posts: list[str] = []
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def _created(self, kind: str, obj: dict[str, Any]) -> httpx.Response:
        return httpx.Response(201, json={"code": 201, "message": f"Created {kind}", "objectCreated": obj})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.params.get("key") != API_KEY:
            return httpx.Response(401, json={"code": 401, "message": "unauthorized"})
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if method == "POST":
            self.posts.append(path)

        if path == "/customers":
            if method == "GET":
                return httpx.Response(200, json=list(self.customers.values()))
            obj = {"_id": str(uuid.uuid4()), **body, "account_ids": []}
            self.customers[obj["_id"]] = obj
            return self._created("customer", obj)

        if m := re.fullmatch(r"/customers/([^/]+)/accounts", path):
            customer_id = m.group(1)
            if customer_id not in self.customers:
                return httpx.Response(404, json={"code": 404, "message": "Customer not found"})
            if method == "GET":
                return httpx.Response(200, json=[a for a in self.accounts.values() if a["customer_id"] == customer_id])
            obj = {"_id": str(uuid.uuid4()), **body, "account_number": "4" * 16, "customer_id": customer_id}
            self.accounts[obj["_id"]] = obj
            return self._created("account", obj)

        if m := re.fullmatch(r"/accounts/([^/]+)/(purchases|transfers|bills)", path):
            account_id, kind = m.groups()
            if account_id not in self.accounts:
                return httpx.Response(404, json={"code": 404, "message": "Account not found"})
            items = self.children[account_id][kind]
            if method == "GET":
                if kind == "transfers" and not items and self.empty_transfers_404:
                    return httpx.Response(404, json={"code": 404, "message": "No transfers found for this account"})
                if kind == "transfers":
                    keep = ("amount", "description", "status", "transaction_date")
                    return httpx.Response(200, json=[{"id": t["_id"], **{k: t.get(k) for k in keep}} for t in items])
                return httpx.Response(200, json=items)
            obj = {"_id": str(uuid.uuid4()), **body}
            if kind == "purchases":
                obj |= {"type": "merchant", "payer_id": account_id}
                if self.truncate_purchase_amounts and "amount" in obj:
                    obj["amount"] = int(obj["amount"])
            if kind == "transfers":
                obj |= {"type": "p2p", "payer_id": account_id}
            if kind == "bills":
                obj |= {"account_id": account_id, "creation_date": "2026-11-07"}
            items.append(obj)
            return self._created(kind[:-1], obj)

        if m := re.fullmatch(r"/purchases/([^/]+)", path):
            for kinds in self.children.values():
                for purchase in kinds["purchases"]:
                    if purchase["_id"] == m.group(1) and method == "DELETE":
                        kinds["purchases"].remove(purchase)
                        return httpx.Response(202, json={"code": 202, "message": "Purchase deleted."})
            return httpx.Response(404, json={"code": 404, "message": "Purchase not found"})

        if path == "/merchants":
            if method == "GET":
                return httpx.Response(200, json=list(self.merchants.values()))
            obj = {"_id": str(uuid.uuid4()), **body}
            self.merchants[obj["_id"]] = obj
            return self._created("merchant", obj)

        if m := re.fullmatch(r"/merchants/([^/]+)", path):
            merchant = self.merchants.get(m.group(1))
            return httpx.Response(200, json=merchant) if merchant else httpx.Response(404, json={"message": "not found"})

        return httpx.Response(404, json={"code": 404, "message": f"no route {method} {path}"})
