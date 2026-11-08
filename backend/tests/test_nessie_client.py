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
    created = client.create_transfer(payer, {"medium": "balance", "payee_id": payee, "amount": 900, "transaction_date": "2026-11-08", "description": "x"})
    assert created["payer_id"] == payer and created["payee_id"] == payee

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
