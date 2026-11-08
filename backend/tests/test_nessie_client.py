from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.integrations import cache
from app.integrations.nessie import (
    NessieClient,
    NessieError,
    NessieReplayMiss,
    client_from_settings,
    purchase_times_from_seed,
    transfer_details_from_seed,
)
from tests.fake_nessie import API_KEY, FakeNessie


@pytest.fixture
def demo_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "FIXTURES_DIR", tmp_path / "fixtures")

    def set_mode(mode: str) -> None:
        monkeypatch.setenv("DEMO_MODE", mode)
        get_settings.cache_clear()

    set_mode("live")
    yield set_mode
    get_settings.cache_clear()


@pytest.fixture
def fake() -> FakeNessie:
    return FakeNessie()


def make_client(fake: FakeNessie, **kwargs) -> NessieClient:
    return NessieClient(API_KEY, "https://api.nessieisreal.com", http=fake.client(), **kwargs)


def test_create_unwraps_object_created_and_reads_back(demo_mode, fake):
    client = make_client(fake)
    linda = client.create_customer({"first_name": "Linda", "last_name": "Sentinel", "address": {}})
    assert linda["first_name"] == "Linda" and linda["_id"]
    account = client.create_account(linda["_id"], {"type": "Checking", "nickname": "c", "rewards": 0, "balance": 1})
    assert client.get_accounts(linda["_id"]) == [account]


def test_transfer_listing_gets_id_payer_payee_and_time(demo_mode, fake):
    client = make_client(fake)
    customer = client.create_customer({"first_name": "A", "last_name": "B"})
    payer = client.create_account(customer["_id"], {"type": "Checking", "nickname": "payer"})["_id"]
    payee = client.create_account(customer["_id"], {"type": "Checking", "nickname": "payee"})["_id"]
    created = client.create_transfer(payer, {"transaction_date": "2026-11-08", "status": None, "amount": 900, "description": "x"})
    assert created["payer_id"] == payer and created["payee_id"] is None  # Nessie can't record a payee

    raw = fake.handle(httpx.Request("GET", f"https://x/accounts/{payer}/transfers?key={API_KEY}")).json()[0]
    assert "id" in raw and "payee_id" not in raw

    seed = {"transfers": {"planted": {"id": created["_id"], "payer_id": payer, "payee_id": payee, "at": "2026-11-08T09:31:00-06:00"}}}
    listed = make_client(fake, transfer_details=transfer_details_from_seed(seed)).get_transfers(payer)
    assert listed == [
        {
            "_id": created["_id"],
            "amount": 900,
            "description": "x",
            "status": None,
            "transaction_date": "2026-11-08",
            "payer_id": payer,
            "payee_id": payee,
            "at": "2026-11-08T09:31:00-06:00",
        }
    ]

    unknown = make_client(fake).get_transfers(payer)[0]
    assert unknown["payee_id"] is None and unknown["at"] is None


def test_transfer_with_a_payee_field_is_rejected_like_live_nessie(demo_mode, fake):
    client = make_client(fake)
    customer = client.create_customer({"first_name": "A", "last_name": "B"})
    payer = client.create_account(customer["_id"], {"type": "Checking", "nickname": "payer"})["_id"]
    body = {"transaction_date": "2026-11-08", "status": "completed", "amount": 1, "description": "x"}
    for extra in ({"payee_id": "someone"}, {"medium": "balance"}):
        with pytest.raises(NessieError, match="extra fields not permitted"):
            client.create_transfer(payer, {**body, **extra})


def test_purchases_get_their_manifest_time(demo_mode, fake):
    client = make_client(fake)
    customer = client.create_customer({"first_name": "A", "last_name": "B"})
    account = client.create_account(customer["_id"], {"type": "Checking", "nickname": "c"})["_id"]
    timed = client.create_purchase(account, {"purchase_date": "2026-11-08", "amount": 900, "description": "Online payment"})
    plain = client.create_purchase(account, {"purchase_date": "2026-11-07", "amount": 5, "description": "Coffee"})
    seed = {"purchase_times": {timed["_id"]: "2026-11-08T09:31:00-06:00"}}
    listed = {p["_id"]: p["at"] for p in make_client(fake, purchase_times=purchase_times_from_seed(seed)).get_purchases(account)}
    assert listed == {timed["_id"]: "2026-11-08T09:31:00-06:00", plain["_id"]: None}


def test_there_is_no_purchase_delete(demo_mode, fake):
    assert not hasattr(NessieClient, "delete_purchase")
    r = fake.handle(httpx.Request("DELETE", f"https://x/purchases/abc?key={API_KEY}"))
    assert r.status_code == 403


def test_empty_list_404_returns_an_empty_list(demo_mode):
    def handler(request):
        return httpx.Response(404, json={"code": 404, "message": "No transfers found for this account"})

    client = NessieClient(API_KEY, "https://api.nessieisreal.com", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.get_transfers("acct") == []


def test_other_404s_still_raise(demo_mode, fake):
    with pytest.raises(NessieError, match="404"):
        make_client(fake).get_transfers("no-such-account")

    def no_merchant(request):
        return httpx.Response(404, json={"code": 404, "message": "No merchant found"})

    client = NessieClient(API_KEY, "https://api.nessieisreal.com", http=httpx.Client(transport=httpx.MockTransport(no_merchant)))
    with pytest.raises(NessieError, match="404"):
        client.get_merchant("m1")


def test_http_base_url_is_upgraded_to_https():
    assert NessieClient("k", "http://api.nessieisreal.com").base_url == "https://api.nessieisreal.com"
    assert NessieClient("k", "http://localhost:9000/").base_url == "http://localhost:9000"


def test_errors_never_contain_the_key(demo_mode, fake):
    client = NessieClient("wrong-secret-key", "https://api.nessieisreal.com", http=fake.client())
    with pytest.raises(NessieError) as exc:
        client.get_customers()
    assert "401" in str(exc.value) and "wrong-secret-key" not in str(exc.value)

    def offline(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    broken = NessieClient("wrong-secret-key", "https://api.nessieisreal.com", http=httpx.Client(transport=httpx.MockTransport(offline)))
    with pytest.raises(NessieError) as exc:
        broken.get_customers()
    assert "wrong-secret-key" not in str(exc.value)


def test_replay_mode_never_calls_out(demo_mode, fake):
    demo_mode("replay")
    with pytest.raises(NessieReplayMiss):
        make_client(fake).get_customers()
    assert fake.requests == []


def test_record_then_replay_without_the_key(demo_mode, fake):
    recorder = make_client(fake, mode="record")
    linda = recorder.create_customer({"first_name": "Linda", "last_name": "Sentinel"})
    assert recorder.get_customers() == [linda]
    files = cache.list_fixtures("nessie")
    assert len(files) == 2
    assert all(API_KEY not in f.read_text(encoding="utf-8") for f in files)

    calls = len(fake.requests)
    replayer = NessieClient("", "https://api.nessieisreal.com", http=fake.client(), mode="replay")
    assert replayer.get_customers() == [linda]
    assert len(fake.requests) == calls


def test_client_from_settings_needs_a_key_outside_replay(demo_mode, monkeypatch, tmp_path):
    monkeypatch.setenv("NESSIE_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(NessieError, match="NESSIE_API_KEY"):
        client_from_settings(tmp_path / "none.json")
    demo_mode("replay")
    assert client_from_settings(tmp_path / "none.json").transfer_details == {}
