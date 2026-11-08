from __future__ import annotations

import re

import pytest

from app.contracts import CheckSenderArgs, CheckSenderResult, SenderType
from app.tools.brands import find_brand, load_brands
from app.tools.sender import CHECK_SENDER_SPEC, check_sender
from tests.agent_input_factory import make_input

PHONE = re.compile(r"\d{3}")


def run(brand: str, sender_type: SenderType, value: str) -> CheckSenderResult:
    return check_sender(CheckSenderArgs(claimed_brand=brand), make_input(sender_type=sender_type, sender_value=value))


def test_scenario_1_hashed_long_code_claiming_capital_one():
    result = run("Capital One", SenderType.long_code, "<PHONE_HASH_7f3a>")
    assert result.sender_type == SenderType.long_code
    assert result.matches_official_channel is False
    assert result.official_channels_known is True
    assert "short codes" in result.note


@pytest.mark.parametrize("code", ["227898", "227-898", "61869"])
def test_capital_one_official_short_codes_match(code):
    result = run("capital one", SenderType.short_code, code)
    assert result.matches_official_channel is True
    assert result.official_channels_known is True


def test_unlisted_short_code_does_not_match():
    result = run("Capital One", SenderType.short_code, "99999")
    assert result.matches_official_channel is False
    assert result.official_channels_known is True


def test_visible_official_long_code_matches():
    assert run("Capital One", SenderType.long_code, "+1 (800) 946-0332").matches_official_channel is True


def test_email_sender_compared_with_official_domains():
    assert run("Capital One", SenderType.email, "alerts@notification.capitalone.com").matches_official_channel is True
    assert run("Capital One", SenderType.email, "alerts@capone-verify-alert.com").matches_official_channel is False


def test_t_mobile_channels_not_listed_so_unknown():
    result = run("T-Mobile", SenderType.long_code, "<PHONE_HASH_1b2c>")
    assert result.matches_official_channel is False
    assert result.official_channels_known is False


def test_unknown_brand():
    result = run("Acme Bank", SenderType.short_code, "12345")
    assert result.matches_official_channel is False
    assert result.official_channels_known is False
    assert "Acme Bank" in result.note


@pytest.mark.parametrize(
    ("brand", "sender_type", "value"),
    [
        ("Capital One", SenderType.short_code, "227898"),
        ("Capital One", SenderType.short_code, "99999"),
        ("Capital One", SenderType.long_code, "<PHONE_HASH_7f3a>"),
        ("Capital One", SenderType.long_code, "+18009460332"),
        ("T-Mobile", SenderType.long_code, "<PHONE_HASH_7f3a>"),
        ("Acme Bank", SenderType.alphanumeric, "ACME"),
    ],
)
def test_notes_never_contain_phone_numbers(brand, sender_type, value):
    assert not PHONE.search(run(brand, sender_type, value).note)


def test_brands_file_lists_only_sourced_channels():
    for brand in load_brands():
        if brand.has_official_channels:
            assert brand.sources, f"{brand.name} lists channels without a source"
            assert all(s.url.startswith("https://www.") for s in brand.sources)
    assert find_brand("CAPITAL-ONE").name == "Capital One"
    assert find_brand("tmobile").name == "T-Mobile"


def test_spec_matches_contracts():
    assert CHECK_SENDER_SPEC.name.value == "check_sender"
    assert CHECK_SENDER_SPEC.args_model is CheckSenderArgs
    assert CHECK_SENDER_SPEC.result_model is CheckSenderResult
