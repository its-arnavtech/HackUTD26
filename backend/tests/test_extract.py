"""A9: new hand-written synthetic cases only; no train/test benchmark rows."""
from __future__ import annotations

import importlib
import json
import socket
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.contracts import Features, RedactedMessage, RedactionCounts, RedactionReport, UrlInfo
from app.features import extract as features
from app.privacy import redact as privacy


@pytest.fixture(autouse=True)
def local_context(monkeypatch):
    monkeypatch.setattr(privacy, "get_settings", lambda: SimpleNamespace(PHONE_HASH_SALT=SecretStr("synthetic-a9-salt")))
    features._brands.cache_clear()
    yield
    features._brands.cache_clear()


# The ten required messages exercise different claims, not verdict accuracy.
CASES = [
    ("bank_verification", "Capital One Alert: unusual sign-in for Mira Vale. Your account will be locked in 2 hours. Verify now: https://capone-verify-alert.com/session?customer=Mira",
     "Capital One", "capone-verify-alert.com", False,
     {"urgency_deadline": "2 hours", "threat": "account_lock", "requested_action": "click_link_and_verify", "asks_for": ["login"], "money_amount_claimed": None}),
    ("carrier_bill", "T-Mobile: your bill is overdue. Service will be suspended within 24 hours. Pay $84.50 at https://tmobile-pay.example/customer/1234567890",
     "T-Mobile", "tmobile-pay.example", False,
     {"urgency_deadline": "24 hours", "threat": "service_suspension", "requested_action": "click_link_and_pay", "asks_for": ["payment"], "money_amount_claimed": 84.5}),
    ("official_app", "Capital One: open the official app to review your $39.20 purchase.",
     "Capital One", None, False,
     {"urgency_deadline": None, "threat": None, "requested_action": "open_official_app", "asks_for": [], "money_amount_claimed": 39.2}),
    ("delivery_fee", "Delivery notice: pay the $1.75 redelivery fee today at https://bit.ly/demo-package.",
     None, "bit.ly", True,
     {"urgency_deadline": "today", "threat": None, "requested_action": "click_link_and_pay", "asks_for": ["payment"], "money_amount_claimed": 1.75}),
    ("code_reply", "Capital One: reply with your one-time code to unlock your account.",
     "Capital One", None, False,
     {"urgency_deadline": None, "threat": None, "requested_action": "reply_with_code", "asks_for": ["one_time_code"], "money_amount_claimed": None}),
    ("receipt", "T-Mobile: your autopay receipt is $87.00. No payment is required.",
     "T-Mobile", None, False,
     {"urgency_deadline": None, "threat": None, "requested_action": None, "asks_for": [], "money_amount_claimed": 87.0}),
    ("code_notice", "Your verification code 654321 expires in 10 minutes. Never share your password or code.",
     None, None, False,
     {"urgency_deadline": "10 minutes", "threat": None, "requested_action": None, "asks_for": [], "money_amount_claimed": None}),
    ("toll_callback", "A late fee of $12.00 is due within 3 days. Call 202-555-0132 for details.",
     None, None, False,
     {"urgency_deadline": "3 days", "threat": "payment_penalty", "requested_action": "call_number", "asks_for": [], "money_amount_claimed": 12.0}),
    ("prize", "You won $500. Claim now at https://gift.example/redeem?name=Mira.",
     None, "gift.example", False,
     {"urgency_deadline": "now", "threat": None, "requested_action": "click_link", "asks_for": [], "money_amount_claimed": 500.0}),
    ("credential_form", "Capital One: submit your card number 4111111111111111 and password at https://billing.example/form?account=1234567890.",
     "Capital One", "billing.example", False,
     {"urgency_deadline": None, "threat": None, "requested_action": "click_link_and_verify", "asks_for": ["password", "card_details"], "money_amount_claimed": None}),
]


@pytest.mark.parametrize("name,text,brand,domain,shortener,expected", CASES, ids=[case[0] for case in CASES])
def test_ten_messages(name, text, brand, domain, shortener, expected):
    redacted = privacy.redact(text)
    before = redacted.model_dump()
    urls = features.extract_urls(redacted)
    result = features.extract_features(redacted.text_redacted)
    assert isinstance(result, Features) and result.model_dump() == expected
    assert features.detect_claimed_brand(redacted.text_redacted) == brand
    assert all(isinstance(url, UrlInfo) for url in urls)
    assert [url.id for url in urls] == (["URL_1"] if domain else [])
    if domain:
        assert urls[0].registered_domain == domain
        assert urls[0].is_shortener is shortener
        assert not urls[0].is_official_brand_domain
    assert redacted.model_dump() == before
    outbound = json.dumps({"urls": [url.model_dump() for url in urls], "features": result.model_dump()})
    for private in ("customer=Mira", "/form", "1234567890", "4111111111111111", "202-555-0132"):
        assert private not in outbound


def message_with_urls(*urls, brand="Capital One"):
    return RedactedMessage(text_redacted=brand + " " + " ".join(f"<URL_{i}>" for i in range(1, len(urls)+1)),
                           report=RedactionReport(counts=RedactionCounts()), raw_urls=list(urls))


@pytest.mark.parametrize("url,expected_domain,official,term", [
    ("https://login.capitalone.com/private?token=synthetic", "capitalone.com", True, "capitalone"),
    ("HTTP://CAPITALONE.COM./", "capitalone.com", True, "capitalone"),
    ("https://capitalone.com.evil.example/", "evil.example", False, "capitalone"),
    ("https://notcapitalone.com/", "notcapitalone.com", False, "capitalone"),
    ("https://capitalone.com@evil.example/path", "evil.example", False, None),
    ("https://evil.example/capitalone.com?brand=CapitalOne", "evil.example", False, None),
    ("https://service.example.co.uk/", "example.co.uk", False, None),
    ("https://tenant.github.io/", "tenant.github.io", False, None),
    ("www.capone-alert.example/private", "capone-alert.example", False, "capone"),
    ("https://127.0.0.1:8080/private", "127.0.0.1", False, None),
    ("https://[::1]:8080/private", "::1", False, None),
])
def test_hostname_boundaries_and_registered_domains(url, expected_domain, official, term):
    info = features.extract_urls(message_with_urls(url))[0]
    assert info.registered_domain == expected_domain
    assert info.is_official_brand_domain is official
    assert info.brand_term_in_domain == term
    assert "private" not in info.model_dump_json() and "synthetic" not in info.model_dump_json()


def test_unicode_lookalike_does_not_become_an_official_domain():
    info = features.extract_urls(message_with_urls("https://c\u0430pitalone.com/"))[0]
    assert info.registered_domain.startswith("xn--")
    assert info.registered_domain != "capitalone.com" and not info.is_official_brand_domain


def test_official_flag_is_relative_to_claimed_brand():
    assert not features.extract_urls(message_with_urls("https://t-mobile.com/"))[0].is_official_brand_domain
    assert features.extract_urls(message_with_urls("https://account.t-mobile.com/", brand="T-Mobile"))[0].is_official_brand_domain
    assert features.extract_urls(message_with_urls("https://t-mobile.com/", brand="Message"))[0].is_official_brand_domain


def test_url_order_duplicates_and_shortener_boundaries():
    result = features.extract_urls(message_with_urls("https://bit.ly/a", "https://bit.ly/b", "https://bit.ly.evil.example/a"))
    assert [item.id for item in result] == ["URL_1", "URL_2", "URL_3"]
    assert [item.is_shortener for item in result] == [True, True, False]


@pytest.mark.parametrize("url", ["https://", "file:///synthetic/private", "javascript:alert(1)", "mailto:mira@example.test", "mira@example.test", "https://exa_mple.test/", "https://example.test:secret-port/", "https://example.test/\nprivate", "https://[broken/"])
def test_invalid_urls_fail_without_echoing_private_input(url):
    with pytest.raises(ValueError) as error:
        features.extract_urls(message_with_urls(url))
    assert str(error.value) == "Invalid URL metadata" and url not in str(error.value)


@pytest.mark.parametrize("text,raw_urls", [("No placeholders", ["https://example.test"]), ("<URL_2>", ["https://example.test"]), ("<URL_1> <URL_1>", ["https://example.test"]), ("<URL_01>", ["https://example.test"]), ("<URL_1>", [])])
def test_mismatched_private_url_mapping_is_rejected(text, raw_urls):
    redacted = RedactedMessage(text_redacted=text, report=RedactionReport(counts=RedactionCounts()), raw_urls=raw_urls)
    with pytest.raises(ValueError, match="placeholders"):
        features.extract_urls(redacted)


def test_first_brand_mention_and_aliases():
    assert features.detect_claimed_brand("Pay T Mobile with Capital One") == "T-Mobile"
    assert features.detect_claimed_brand("CapOne alert") == "Capital One"
    assert features.detect_claimed_brand("CapitalOne notification") == "Capital One"
    assert features.detect_claimed_brand("capitaloneish and tmobileish") is None
    assert features.detect_claimed_brand("<URL_1> only") is None


def test_registry_extends_brands_without_rules_from_message_sets(monkeypatch, tmp_path):
    (tmp_path / "brands.json").write_text(json.dumps({"brands": [{"name": "Mock Tel", "official_domains": ["mocktel.example"], "aliases": ["MockTel"]}]}))
    monkeypatch.setattr(features, "DATA_DIR", tmp_path)
    assert features.detect_claimed_brand("MockTel notice") == "Mock Tel"
    assert features.extract_urls(message_with_urls("https://account.mocktel.example/", brand="Mock Tel"))[0].is_official_brand_domain


def test_feature_extraction_does_not_make_network_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("feature extraction attempted network access")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    importlib.reload(features)  # Exercise a cold suffix parser, not a warmed cache.
    result = features.extract_urls(privacy.redact("Capital One: verify https://login.capitalone.com/private"))
    assert result[0].registered_domain == "capitalone.com"
    assert features.extract_features("Pay $12.00 within 2 hours at <URL_1>").money_amount_claimed == 12


@pytest.mark.parametrize("text", ["Never share your password or one-time code.", "Do not click <URL_1> or pay any fee.", "Your account will not be locked. You do not need to verify now.", "Your statement covers the last 30 days."])
def test_negation_and_historical_windows_do_not_become_requests(text):
    assert features.extract_features(text) == Features()


@pytest.mark.parametrize("text,deadline", [("Pay within two hours.", "2 hours"), ("Your code expires in 1 minute.", "1 minute"), ("Pay now; 3 hrs remaining.", "3 hours"), ("Pay by 2026-11-08.", "by 2026-11-08"), ("Pay by Friday.", "by friday")])
def test_deadlines_are_bounded_canonical_values(text, deadline):
    assert features.extract_features(text).urgency_deadline == deadline


@pytest.mark.parametrize("text,amount", [("Pay $1,234.56.", 1234.56), ("A refund of 2500 USD was issued.", 2500), ("Pay €9.99 today.", 9.99), ("Pay £8 now.", 8), ("Pay $1,23 now.", None), ("Nothing is due.", None)])
def test_numeric_amounts(text, amount):
    assert features.extract_features(text).money_amount_claimed == amount


def test_no_feature_is_read_from_private_url_queries():
    redacted = privacy.redact("Message: https://example.test/?pay=$900&password=synthetic&deadline=2hours")
    assert features.extract_features(redacted.text_redacted) == Features()
    assert features.detect_claimed_brand(redacted.text_redacted) is None


def test_explicit_credential_categories_and_empty_input():
    result = features.extract_features("Provide your account number, routing number, full name and address at <URL_1>.")
    assert result.asks_for == ["account_details", "personal_information"]
    assert features.extract_features("") == Features()
    assert features.extract_urls(message_with_urls(brand="")) == []
