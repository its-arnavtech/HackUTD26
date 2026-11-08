"""No NVIDIA calls: SDK requests are intercepted by an HTTP mock transport."""
import json
import logging

import httpx2 as sdk_http
import pytest
from openai import APIStatusError, OpenAI
from pydantic import SecretStr

from app.contracts import DemoMode
from app.integrations import nemotron


@pytest.fixture
def wire(monkeypatch):
    settings = nemotron.NemotronSettings(_env_file=None, NVIDIA_API_KEY="synthetic-test-key",
                                         NEMOTRON_BASE_URL="https://nvidia.example/v1", NEMOTRON_MODEL="test-bolt")
    monkeypatch.setattr(nemotron, "get_nemotron_settings", lambda: settings)
    monkeypatch.setattr(nemotron.time, "sleep", lambda _: None)
    requests = []
    responses = []
    def handler(request):
        requests.append(request)
        status, data = responses.pop(0)
        return sdk_http.Response(status, json=data, headers={"retry-after": "0"})
    def client(_settings):
        return OpenAI(api_key="synthetic-test-key", base_url=settings.NEMOTRON_BASE_URL, max_retries=0,
                      http_client=sdk_http.Client(transport=sdk_http.MockTransport(handler)))
    monkeypatch.setattr(nemotron, "_client", client)
    return settings, requests, responses


def completion(message):
    return {"id": "synthetic", "object": "chat.completion", "created": 0, "model": "test-bolt",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}]}


def test_native_body_and_response(wire, caplog):
    settings, requests, responses = wire
    call = {"id": "call_1", "type": "function", "function": {"name": "check_domain", "arguments": '{"domain":"synthetic.example"}'}}
    responses.append((200, completion({"content": None, "tool_calls": [call]})))
    tools = [{"type": "function", "function": {"name": "check_domain", "parameters": {"type": "object"}}}]
    with caplog.at_level(logging.INFO, logger=nemotron.__name__):
        result = nemotron.chat([{"role": "user", "content": "synthetic-redacted"}], tools)
    body = json.loads(requests[0].content)
    assert body["model"] == settings.NEMOTRON_MODEL
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    assert str(requests[0].url) == "https://nvidia.example/v1/chat/completions"
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"
    assert "latency_ms=" in caplog.text
    assert "synthetic-test-key" not in caplog.text and "synthetic-redacted" not in caplog.text


@pytest.mark.parametrize("status,retried", [(429, True), (500, True), (503, True), (400, False), (401, False), (408, False), (409, False)])
def test_exact_retry_policy(wire, status, retried):
    _, requests, responses = wire
    responses.extend([(status, {"error": {"message": "synthetic"}}), (200, completion({"content": "ok"}))])
    if retried:
        assert nemotron.chat([])["choices"][0]["message"]["content"] == "ok"
    else:
        with pytest.raises(APIStatusError):
            nemotron.chat([])
    assert len(requests) == (2 if retried else 1)


def test_second_transient_error_stops(wire):
    _, requests, responses = wire
    responses.extend([(503, {}), (503, {})])
    with pytest.raises(APIStatusError):
        nemotron.chat([])
    assert len(requests) == 2


def test_json_action_omits_native_tools(wire):
    settings, requests, responses = wire
    settings.NEMOTRON_PROTOCOL = "json_action"
    responses.append((200, completion({"content": '{"action":"finish","result":{}}'})))
    messages = [{"role": "system", "content": "task"}, {"role": "user", "content": "synthetic"}]
    nemotron.chat(messages, [{"type": "function", "function": {"name": "check_domain"}}])
    body = json.loads(requests[0].content)
    assert "tools" not in body and "tool_choice" not in body
    assert body["messages"][0]["content"] == "task"
    assert '"action":"call_tool"' in body["messages"][1]["content"]
    assert len(messages) == 2


def test_models_and_embeddings(wire):
    settings, requests, responses = wire
    responses.append((200, {"object": "list", "data": [{"id": "test-bolt", "object": "model", "created": 0, "owned_by": "test"}]}))
    assert nemotron.list_models() == ["test-bolt"]
    settings.NEMOTRON_EMBED_MODEL = "test-embed"
    responses.append((200, {"object": "list", "model": "test-embed", "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 1, "total_tokens": 1}}))
    assert nemotron.embed("synthetic") == [0.1, 0.2]
    assert json.loads(requests[-1].content)["input_type"] == "passage"


def test_cache_hit_makes_no_http_request(wire, monkeypatch):
    _, requests, _ = wire
    seen = []
    def hit(service, request, fn, **kwargs):
        seen.append((service, request))
        return completion({"content": "recorded"})
    monkeypatch.setattr(nemotron.cache, "cached_call", hit)
    assert nemotron.chat([])["choices"][0]["message"]["content"] == "recorded"
    assert not requests and seen[0][0] == "nemotron"
    assert "api_key" not in json.dumps(seen)


def test_record_then_replay_uses_real_cache_without_credentials(wire, monkeypatch, tmp_path):
    settings, requests, responses = wire
    monkeypatch.setattr(nemotron.cache, "FIXTURES_DIR", tmp_path)
    settings.DEMO_MODE = DemoMode.record
    responses.append((200, completion({"content": "synthetic recorded result"})))
    recorded = nemotron.chat([{"role": "user", "content": "synthetic-redacted"}])
    assert len(requests) == 1
    fixtures = list(tmp_path.glob("nemotron/*.json"))
    assert len(fixtures) == 1 and "synthetic-test-key" not in fixtures[0].read_text()
    settings.DEMO_MODE = DemoMode.replay
    settings.NVIDIA_API_KEY = None
    replayed = nemotron.chat([{"role": "user", "content": "synthetic-redacted"}])
    assert replayed == recorded and len(requests) == 1


def test_replay_cache_miss_never_calls_http(wire, monkeypatch, tmp_path):
    settings, requests, _ = wire
    monkeypatch.setattr(nemotron.cache, "FIXTURES_DIR", tmp_path)
    settings.DEMO_MODE = DemoMode.replay
    with pytest.raises(nemotron.cache.FixtureMissingError):
        nemotron.chat([])
    assert not requests


def test_client_configuration_and_missing_key(monkeypatch):
    settings = nemotron.NemotronSettings(_env_file=None, NVIDIA_API_KEY=None)
    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        nemotron._client(settings)
    settings.NEMOTRON_BASE_URL = "http://127.0.0.1:8080/v1"
    settings.NVIDIA_API_KEY = SecretStr("synthetic-hosted-key")
    with nemotron._client(settings) as client:
        assert client.max_retries == 0
        assert client.timeout == settings.NEMOTRON_TIMEOUT_SECONDS
        assert client.api_key == "local-no-key"
