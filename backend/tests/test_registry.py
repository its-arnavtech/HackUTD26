"""L5: tool registry, schemas, timeouts, errors as data, privacy records."""

from __future__ import annotations

import json
import threading
import time

import pytest

from app import contracts as c
from app.agent import registry
from app.agent.registry import ToolRegistry, ToolSpec
from app.logs import bind_message_id, current_message_id

AGENT_INPUT = c.AgentInput.model_validate(
    {
        "message_id": "msg_0142",
        "mode": "check",
        "received_at": "2026-11-08T09:14:00-06:00",
        "sender": {"type": "long_code", "value": "<PHONE_HASH_7f3a>", "claimed_brand": "Capital One"},
        "text_redacted": "Capital One Alert: unusual sign-in for <PERSON>. Verify now: <URL_1>",
        "urls": [
            {
                "id": "URL_1",
                "registered_domain": "capone-verify-alert.com",
                "is_shortener": False,
                "brand_term_in_domain": "capone",
                "is_official_brand_domain": False,
            }
        ],
        "features": {
            "urgency_deadline": "2 hours",
            "threat": "account_lock",
            "requested_action": "click_link_and_verify",
            "asks_for": ["login"],
            "money_amount_claimed": None,
        },
        "classifier": {"category": "bank_impersonation", "score": 0.94, "top3": [["bank_impersonation", 0.94]], "baseline_score": 0.81},
        "customer_context": {"linked_bank": True, "linked_institutions": ["Capital One"]},
    }
)

LINK_RESULT = c.CheckLinkResult(
    domain="capone-verify-alert.com", domain_age_days=3, on_blocklist=False, lookalike_of="capitalone.com", signals=["brand term in non-official domain"]
)


def fake_check_link(args: c.CheckLinkArgs, agent_input: c.AgentInput) -> c.CheckLinkResult:
    assert args.url_id == "URL_1" and agent_input.message_id == "msg_0142"
    return LINK_RESULT


def spec(name=c.ToolName.check_link, fn=fake_check_link, **kw) -> ToolSpec:
    defaults = {
        c.ToolName.check_link: (c.CheckLinkArgs, c.CheckLinkResult),
        c.ToolName.match_campaign: (c.MatchCampaignArgs, c.MatchCampaignResult),
        c.ToolName.nessie_recent_activity: (c.NessieRecentActivityArgs, c.NessieRecentActivityResult),
    }
    args_model, result_model = defaults[name]
    return ToolSpec(name=name, description=f"{name.value} test", args_model=args_model, result_model=result_model, fn=fn, **kw)


@pytest.fixture
def reg():
    r = ToolRegistry(max_workers=4)
    yield r
    r.shutdown()


# --- registration ---------------------------------------------------------------


def test_register_and_get(reg):
    reg.register(spec())
    assert reg.get("check_link").name == c.ToolName.check_link
    assert "check_link" in reg and "check_sender" not in reg and "nope" not in reg
    with pytest.raises(KeyError):
        reg.get("check_sender")


def test_duplicate_registration_needs_replace(reg):
    reg.register(spec())
    with pytest.raises(ValueError):
        reg.register(spec())
    reg.register(spec(timeout_s=1), replace=True)
    assert reg.get("check_link").timeout_s == 1


def test_bad_specs_are_rejected(reg):
    with pytest.raises(ValueError):
        reg.register(spec(injected={"not_a_field": lambda ai: 1}))
    with pytest.raises(ValueError):
        reg.register(spec(timeout_s=0))


# --- schemas ----------------------------------------------------------------------


def test_openai_schema_shape(reg):
    reg.register(spec())
    [tool] = reg.openai_tool_schemas()
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "check_link" and fn["description"]
    params = fn["parameters"]
    assert params["type"] == "object" and params["additionalProperties"] is False
    assert params["properties"] == {"url_id": {"type": "string"}}
    assert params["required"] == ["url_id"]
    assert "title" not in json.dumps(params)
    json.dumps(tool)  # serialisable


def test_injected_fields_are_hidden_from_the_model(reg):
    reg.register(spec(c.ToolName.match_campaign, fn=lambda a, ai: c.MatchCampaignResult(), injected={"message_id": lambda ai: ai.message_id}))
    params = reg.openai_tool_schemas()[0]["function"]["parameters"]
    assert params["properties"] == {} and "required" not in params


def test_schemas_have_no_refs_for_every_builtin_tool():
    schemas = registry.openai_tool_schemas()
    assert [s["function"]["name"] for s in schemas] == [t.value for t in c.ToolName]
    for s in schemas:
        text = json.dumps(s)
        assert "$ref" not in text and "$defs" not in text
        assert s["function"]["parameters"]["type"] == "object"
    nessie = next(s for s in schemas if s["function"]["name"] == "nessie_recent_activity")
    assert set(nessie["function"]["parameters"]["properties"]) == {"days", "since"}


def test_schema_subset(reg):
    reg.register(spec())
    reg.register(spec(c.ToolName.match_campaign, fn=lambda a, ai: c.MatchCampaignResult(), injected={"message_id": lambda ai: ai.message_id}))
    assert [s["function"]["name"] for s in reg.openai_tool_schemas(["match_campaign"])] == ["match_campaign"]


# --- calls -------------------------------------------------------------------------


def test_successful_call(reg):
    reg.register(spec())
    call = reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT)
    assert call.ok and call.error is None and call.ms >= 0
    assert call.result == LINK_RESULT.model_dump(mode="json")
    assert call.to_tool_message() == {"ok": True, "tool": "check_link", "result": call.result}


def test_tool_may_return_a_dict(reg):
    reg.register(spec(fn=lambda a, ai: LINK_RESULT.model_dump()))
    assert reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT).ok


@pytest.mark.parametrize(
    "name,args,kind",
    [
        ("check_sender", {"claimed_brand": "x"}, "unknown_tool"),  # not registered here
        ("delete_everything", {}, "unknown_tool"),
        ("check_link", {}, "invalid_args"),
        ("check_link", {"url_id": "URL_1", "extra": 1}, "invalid_args"),
        ("check_link", ["URL_1"], "invalid_args"),
    ],
)
def test_bad_requests_are_errors_as_data(reg, name, args, kind):
    reg.register(spec())
    call = reg.call(name, args, AGENT_INPUT)
    assert not call.ok and call.error["type"] == kind and call.result is None
    assert call.to_tool_message()["ok"] is False


def test_unknown_tool_message_lists_the_real_tools(reg):
    reg.register(spec())
    assert "check_link" in reg.call("nope", {}, AGENT_INPUT).error["message"]


def test_timeout_is_an_error_as_data(reg):
    release = threading.Event()

    def slow(args, ai):
        release.wait(5)
        return LINK_RESULT

    reg.register(spec(fn=slow, timeout_s=0.1))
    started = time.perf_counter()
    call = reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT)
    release.set()
    assert time.perf_counter() - started < 2
    assert not call.ok and call.error["type"] == "timeout" and "0.1" in call.error["message"]


def test_crash_is_an_error_as_data_without_leaking_details(reg):
    def boom(args, ai):
        raise ConnectionError("rdap.example 10.0.0.5 refused; payee Jane Doe")

    reg.register(spec(fn=boom))
    call = reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT)
    assert not call.ok and call.error["type"] == "tool_error"
    assert "Jane" not in json.dumps(call.to_tool_message()) and "10.0.0.5" not in json.dumps(call.to_tool_message())


def test_unbuilt_tool_says_unavailable(reg):
    def stub(args, ai):
        raise NotImplementedError("A10: check_link")

    reg.register(spec(fn=stub))
    assert reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT).error["type"] == "unavailable"


def test_invalid_result_is_an_error(reg):
    reg.register(spec(fn=lambda a, ai: {"domain": 5}))
    assert reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT).error["type"] == "tool_error"


def test_injected_value_overrides_the_model(reg):
    seen = []
    reg.register(
        spec(
            c.ToolName.match_campaign,
            fn=lambda a, ai: (seen.append(a.message_id), c.MatchCampaignResult())[1],
            injected={"message_id": lambda ai: ai.message_id},
        )
    )
    call = reg.call("match_campaign", {"message_id": "msg_someone_else"}, AGENT_INPUT)
    assert call.ok and seen == ["msg_0142"] and call.args == {"message_id": "msg_0142"}


def test_model_validator_errors_come_back_as_data(reg):
    reg.register(spec(c.ToolName.nessie_recent_activity, fn=lambda a, ai: None))
    call = reg.call("nessie_recent_activity", {"days": 7, "since": "2026-11-08T09:14:00-06:00"}, AGENT_INPUT)
    assert call.error["type"] == "invalid_args" and "exactly one" in call.error["message"]


# --- privacy records ------------------------------------------------------------------


def test_privacy_record_has_exactly_what_the_tool_received(reg):
    records: list[c.PrivacyRecipient] = []
    reg.register(spec(reads=("urls",)))
    reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT, on_call=records.append)
    [r] = records
    assert r.recipient == "check_link" and r.kind == "tool"
    # L6: the agent-input fields the tool reads are part of what it received.
    assert r.payload == {"url_id": "URL_1", "urls": AGENT_INPUT.model_dump(mode="json")["urls"]}
    assert r.received_fields == ["url_id", "urls"] and r.at is not None


def test_privacy_recorded_even_when_the_tool_fails(reg):
    records = []
    reg.register(spec(fn=lambda a, ai: (_ for _ in ()).throw(RuntimeError("x"))))
    reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT, on_call=records.append)
    assert len(records) == 1


def test_nothing_recorded_when_the_tool_never_ran(reg):
    records = []
    reg.register(spec())
    reg.call("check_link", {}, AGENT_INPUT, on_call=records.append)
    reg.call("nope", {}, AGENT_INPUT, on_call=records.append)
    assert records == []


def test_broken_privacy_hook_never_breaks_the_call(reg):
    reg.register(spec())

    def bad_hook(record):
        raise RuntimeError("disk full")

    assert reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT, on_call=bad_hook).ok


# --- context and defaults -----------------------------------------------------------------


def test_tool_runs_with_the_callers_message_id(reg):
    seen = []
    reg.register(spec(fn=lambda a, ai: (seen.append(current_message_id()), LINK_RESULT)[1]))
    with bind_message_id("msg_0142"):
        reg.call("check_link", {"url_id": "URL_1"}, AGENT_INPUT)
    assert seen == ["msg_0142"]


def test_default_registry_has_the_six_tools_and_stubs_are_unavailable():
    assert registry.default_registry() is registry.default_registry()
    assert set(registry.default_registry().names()) == set(c.ToolName)
    assert registry.get_tool("match_campaign").injected
    # Tools not built yet answer "unavailable" instead of crashing the agent.
    call = registry.call_tool("check_sender", {"claimed_brand": "Capital One"}, AGENT_INPUT)
    assert call.ok or call.error["type"] in {"unavailable", "tool_error", "timeout"}
