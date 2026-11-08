"""Every route returns 200 with mocks on, and the result poll simulates progress."""

from __future__ import annotations

from app import contracts as c


def test_inbox(client):
    r = client.get("/api/inbox")
    assert r.status_code == 200
    items = [c.InboxItem.model_validate(i) for i in r.json()]
    assert {i.message_id for i in items} >= {"msg_0001", "msg_0003"}


def test_result_poll_progresses_to_done(client):
    statuses, trail_lengths = [], []
    for _ in range(20):
        r = client.get("/api/messages/msg_0001/result")
        assert r.status_code == 200
        poll = c.ResultPoll.model_validate(r.json())
        statuses.append(poll.status)
        trail_lengths.append(len(poll.trail))
        if poll.status == c.JobStatus.done:
            break
    assert statuses[0] == c.JobStatus.queued
    assert c.JobStatus.running in statuses
    assert statuses[-1] == c.JobStatus.done and poll.result is not None
    assert trail_lengths == sorted(trail_lengths)
    inbox = {i["message_id"]: i for i in client.get("/api/inbox").json()}
    assert inbox["msg_0001"]["status"] == "done"
    assert inbox["msg_0001"]["verdict"] == "likely_scam"


def test_unknown_message_is_404(client):
    assert client.get("/api/messages/nope/result").status_code == 404


def test_post_message(client):
    body = {"text": "T-Mobile: your bill is overdue.", "sender": "+15550100000", "received_at": "2026-11-08T10:00:00-06:00"}
    r = client.post("/api/messages", json=body)
    assert r.status_code == 200
    message_id = c.PostMessageResponse.model_validate(r.json()).message_id
    assert message_id in {i["message_id"] for i in client.get("/api/inbox").json()}
    assert client.get(f"/api/messages/{message_id}/result").status_code == 200


def test_clicked_switches_to_recovery(client):
    r = client.post("/api/messages/msg_0001/clicked")
    assert r.status_code == 200
    assert c.ClickedResponse.model_validate(r.json()).mode == c.AgentMode.recovery
    for _ in range(20):
        poll = c.ResultPoll.model_validate(client.get("/api/messages/msg_0001/result").json())
        if poll.status == c.JobStatus.done:
            break
    assert poll.mode == c.AgentMode.recovery
    assert poll.result.was_this_you == ["txn_3"]


def test_confirm(client):
    r = client.post("/api/transactions/txn_3/confirm", json={"was_me": False})
    assert r.status_code == 200
    assert c.ConfirmResponse.model_validate(r.json()).was_me is False


def test_actions(client):
    r = client.post("/api/actions", json={"message_id": "msg_0001", "action": "block_sender"})
    assert r.status_code == 200
    c.ActionResponse.model_validate(r.json())
    assert client.post("/api/actions", json={"message_id": "msg_0001", "action": "wire_money"}).status_code == 422


def test_privacy(client):
    r = client.get("/api/privacy/msg_0001")
    assert r.status_code == 200
    c.PrivacyView.model_validate(r.json())


def test_campaigns(client):
    r = client.get("/api/campaigns")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_metrics(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    c.Metrics.model_validate(r.json())


def test_demo_reset(client):
    client.post("/api/messages", json={"text": "hi", "sender": "+15550100000", "received_at": "2026-11-08T10:00:00-06:00"})
    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    assert c.DemoResetResponse.model_validate(r.json()).inbox_count == 3
