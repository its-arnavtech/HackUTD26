from __future__ import annotations

import pytest

from app.contracts import CheckLinkArgs, CheckLinkResult
from app.tools.link import CHECK_LINK_SPEC, check_link
from tests.agent_input_factory import make_input


class FakeRdap:
    def __init__(self, record=None):
        self.record = record
        self.calls: list[str] = []

    def __call__(self, domain):
        self.calls.append(domain)
        return self.record


def run(domain: str, *, record=None, blocklist=frozenset(), **input_kwargs) -> tuple[CheckLinkResult, FakeRdap]:
    rdap = FakeRdap(record)
    result = check_link(CheckLinkArgs(url_id="URL_1"), make_input(domains=(domain,), **input_kwargs), rdap_lookup=rdap, blocklist=blocklist)
    return result, rdap


def test_scenario_1_domain_is_new_lookalike_of_capital_one():
    result, rdap = run("capone-verify-alert.com", record={"found": True, "registered_at": "2026-11-05T12:00:00Z"})
    assert result.domain == "capone-verify-alert.com"
    assert result.lookalike_of == "capitalone.com"
    assert result.domain_age_days == 3
    assert result.on_blocklist is False
    assert result.final_redirect_domain is None
    assert "Capital One brand term in a domain Capital One doesn't own" in result.signals
    assert "domain registered 3 days before the message" in result.signals
    assert "several hyphens in the domain name" in result.signals
    assert rdap.calls == ["capone-verify-alert.com"]


def test_official_domain_has_no_lookalike_and_skips_rdap():
    result, rdap = run("capitalone.com")
    assert result.lookalike_of is None
    assert result.signals == ["official Capital One domain"]
    assert result.domain_age_days is None
    assert rdap.calls == []


@pytest.mark.parametrize(
    ("domain", "imitates"),
    [
        ("capita1one-unlock.com", "capitalone.com"),  # digit for letter
        ("capitalon.com", "capitalone.com"),  # one edit away
        ("t-mobile-pastdue.info", "t-mobile.com"),
        ("tmobile-billpay-now.com", "t-mobile.com"),
    ],
)
def test_lookalikes(domain, imitates):
    result, _ = run(domain, claimed_brand=None)
    assert result.lookalike_of == imitates


def test_unrelated_domain_is_not_a_lookalike_but_is_not_official_for_claimed_brand():
    result, _ = run("weekend-deals.com")
    assert result.lookalike_of is None
    assert "not an official Capital One domain" in result.signals


def test_blocklist_tld_and_shortener_signals():
    result, _ = run("parcel-fee-payment.click", blocklist=frozenset({"parcel-fee-payment.click"}), claimed_brand=None)
    assert result.on_blocklist is True
    assert "on our list of known scam domains" in result.signals
    assert "uncommon top-level domain .click" in result.signals

    short, _ = run("bit.ly", claimed_brand=None)
    assert "link shortener hides the real destination" in short.signals


def test_unregistered_domain_and_failed_lookup():
    missing, _ = run("nothing-here-at-all.com", record={"found": False, "registered_at": None})
    assert missing.domain_age_days is None
    assert "no registration record found for this domain" in missing.signals

    failed, _ = run("nothing-here-at-all.com", record=None)
    assert failed.domain_age_days is None
    assert not any("registration" in s for s in failed.signals)


def test_old_domain_has_no_new_domain_signal():
    result, _ = run("weekend-deals.com", record={"found": True, "registered_at": "2010-01-01T00:00:00Z"})
    assert result.domain_age_days > 5000
    assert not any("registered" in s for s in result.signals)


def test_unknown_url_id_raises():
    with pytest.raises(ValueError, match="unknown url_id"):
        check_link(CheckLinkArgs(url_id="URL_9"), make_input(), rdap_lookup=FakeRdap(), blocklist=frozenset())


def test_signals_never_carry_instructions_or_full_links():
    result, _ = run("capone-verify-alert.com", record={"found": True, "registered_at": "2026-11-05T12:00:00Z"})
    for signal in result.signals:
        assert "http" not in signal and "/" not in signal


def test_spec_matches_contracts():
    assert CHECK_LINK_SPEC.name.value == "check_link"
    assert CHECK_LINK_SPEC.args_model is CheckLinkArgs
    assert CHECK_LINK_SPEC.result_model is CheckLinkResult
