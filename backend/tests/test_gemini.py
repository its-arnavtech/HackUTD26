"""L4/L10: synthetic public facts, fake provider, strict cache and data boundary."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.contracts import GeminiOutput, PublicScamReportsArgs
from app.errors import IntegrationError
from app.integrations import cache, gemini
from app.tools import public_reports
from tests.agent_input_factory import make_input


def query():
    return public_reports.build_gemini_input(PublicScamReportsArgs(
        claimed_brand="Capital One", scam_category="bank_impersonation", link_domain="capone-verify-alert.com",
    ))


def grounded(*facts):
    return {"candidates": [{"content": {"parts": [{"text": "Uncited content is never trusted"}]},
        "grounding_metadata": {
            "grounding_chunks": [{"web": {"uri": url, "domain": host}} for host, url, text in facts],
            "grounding_supports": [{"segment": {"text": text}, "grounding_chunk_indices": [i]}
                                   for i, (host, url, text) in enumerate(facts)],
        }}]}


def test_only_metadata_supported_facts_survive_and_contacts_are_removed():
    raw = grounded(("capitalone.com", "https://capitalone.com/example-guidance",
                    "Capital One never asks for a password or one-time code by text. Call 1-800-555-0199. Published: 2026-11-01"))
    result = gemini.parse_grounding(raw, query(), today=date(2026, 11, 8))
    assert result.reports_found == 1
    assert result.reports[0].source_type.value == "official" and result.newest_report_age_days == 7
    assert "555" not in result.reports[0].claim and "Uncited" not in result.model_dump_json()
    assert result.brand_guidance.never_asks_by_text == ["password", "one-time code"]
    assert result.reports[0].url == "https://capitalone.com/example-guidance"


def test_no_metadata_and_community_only_do_not_provide_deciding_evidence():
    assert gemini.parse_grounding({"text": "This domain is safe"}, query()).reports_found == 0
    raw = grounded(("reddit.com", "https://reddit.com/r/Scams/example", "This exact domain is a scam"))
    result = gemini.parse_grounding(raw, query())
    assert result.reports_found == 0 and not result.domain_reported


def test_rank_staleness_exact_domain_and_supported_recovery():
    raw = grounded(
        ("reddit.com", "https://reddit.com/r/Scams/example", "A similar text circulated."),
        ("ftc.gov", "https://consumer.ftc.gov/example", "If you clicked a phishing link, change the password. Published: 2026-01-01"),
        ("capitalone.com", "https://capitalone.com/example", "capone-verify-alert.com is a phishing domain. Published: 2026-11-01"),
        ("proofpoint.com", "https://proofpoint.com/example", "This lure was reported. Published: 2026-11-03"),
    )
    result = gemini.parse_grounding(raw, query(), today=date(2026, 11, 8))
    assert [r.source_type.value for r in result.reports] == ["official", "government", "security_vendor", "community"]
    assert result.reports[1].stale and result.domain_reported
    assert result.recovery_steps_source == "https://consumer.ftc.gov/example"
    assert "capone-verify-alert.com" not in result.reports[0].claim
    assert result.newest_report_age_days == 5


def test_similar_domain_is_not_reported_and_unknown_dates_are_not_invented():
    raw = grounded(("ftc.gov", "https://consumer.ftc.gov/example", "other-capone-verify-alert.com is phishing. Published: 2099-11-01"))
    result = gemini.parse_grounding(raw, query(), today=date(2026, 11, 8))
    assert not result.domain_reported and result.reports[0].date is None and not result.reports[0].stale
    assert result.newest_report_age_days is None


def test_invalid_citations_and_chunk_indices_are_dropped():
    raw = grounded(("ftc.gov", "javascript:alert(1)", "A synthetic claim."))
    raw["candidates"][0]["grounding_metadata"]["grounding_supports"] += [
        {"segment": {"text": "Invented"}, "grounding_chunk_indices": [-1, 99, "0"]},
    ]
    assert gemini.parse_grounding(raw, query()).reports_found == 0


def test_guidance_does_not_borrow_a_password_from_another_sentence():
    raw = grounded(("capitalone.com", "https://capitalone.com/example", "We never ask for your address by text. Reset your password."))
    assert gemini.parse_grounding(raw, query()).brand_guidance is None


@pytest.mark.parametrize("field,value", [
    ("claimed_brand", "Linda account 12345678"), ("scam_category", "ignore instructions"),
    ("link_domain", "https://example.com/raw?account=12345678"), ("link_domain", "127.0.0.1"),
    ("link_domain", "example.com@evil.test"),
])
def test_lookup_fields_cannot_smuggle_arbitrary_message_text(field, value):
    args = query().model_dump(exclude={"lure_phrase"})
    args[field] = value
    with pytest.raises(ValueError):
        public_reports.build_gemini_input(PublicScamReportsArgs(**args))


def test_tool_uses_permitted_pipeline_fields_instead_of_model_arguments(monkeypatch):
    sent = []
    monkeypatch.setattr(gemini, "grounded_search", lambda payload: sent.append(payload) or GeminiOutput(reports_found=0))
    ai = make_input()
    public_reports.public_scam_reports(PublicScamReportsArgs(
        claimed_brand="Linda account 12345678", scam_category="private raw text", link_domain="evil.test",
    ), ai)
    assert sent == [query()]
    assert set(sent[0].model_dump()) == {"claimed_brand", "scam_category", "link_domain", "lure_phrase"}


def test_record_replay_without_keys_and_exact_audit_payload(monkeypatch, tmp_path):
    from google import genai
    from app import privacy_log
    calls, audited = [], []
    raw = grounded(("ftc.gov", "https://consumer.ftc.gov/example", "A synthetic phishing warning."))
    class Client:
        def __init__(self, **kwargs):
            self.models = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(model_dump=lambda **kwargs: raw)
    settings = Settings(_env_file=None, GEMINI_API_KEY="synthetic-key", GEMINI_MODEL="gemini-test", DEMO_MODE="record")
    monkeypatch.setattr(gemini, "get_settings", lambda: settings)
    monkeypatch.setattr(cache, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(genai, "Client", Client)
    monkeypatch.setattr(privacy_log, "record_model", lambda name, payload: audited.append((name, payload)))
    recorded = gemini.grounded_search(query())
    assert len(calls) == 1 and calls[0]["contents"] == __import__("json").dumps(query().model_dump())
    assert calls[0]["config"].tools[0].google_search is not None
    assert audited == [("gemini", query().model_dump())]
    settings = settings.model_copy(update={"DEMO_MODE": "replay", "GEMINI_API_KEY": None})
    assert gemini.grounded_search(query()) == recorded and len(calls) == 1
    assert "synthetic-key" not in next(tmp_path.rglob("*.json")).read_text()


def test_missing_key_and_provider_error_never_echo_provider_body(monkeypatch, tmp_path):
    from google import genai
    settings = Settings(_env_file=None, GEMINI_MODEL="gemini-test", GEMINI_API_KEY=None, DEMO_MODE="live")
    monkeypatch.setattr(gemini, "get_settings", lambda: settings)
    with pytest.raises(IntegrationError, match="not configured"):
        gemini.grounded_search(query())
    settings = settings.model_copy(update={"GEMINI_API_KEY": __import__("pydantic").SecretStr("synthetic-secret-key")})
    def fail(**kwargs):
        raise RuntimeError("Provider echoed synthetic-secret-key and private content")
    monkeypatch.setattr(genai, "Client", fail)
    with pytest.raises(IntegrationError) as exc:
        gemini.grounded_search(query())
    assert "synthetic-secret-key" not in str(exc.value) and "private content" not in str(exc.value)
