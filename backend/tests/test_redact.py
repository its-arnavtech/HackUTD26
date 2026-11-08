"""P5 gate: hand-written synthetic messages, never evaluation-set examples."""
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.contracts import RedactedMessage, SenderType
from app.privacy import redact as privacy


@pytest.fixture(autouse=True)
def salt(monkeypatch):
    monkeypatch.setattr(privacy, "get_settings", lambda: SimpleNamespace(PHONE_HASH_SALT=SecretStr("synthetic-test-salt")))


# Twenty independent handwritten P5 cases cover all five required categories.
@pytest.mark.parametrize("text,kind,removed", [
    ("Hi Mira Vale, your statement is ready.", "PERSON", "Mira Vale"),
    ("Dr. Nolan Finch, please verify the message.", "PERSON", "Nolan Finch"),
    ("Customer name: rhea cove; bill ready.", "PERSON", "rhea cove"),
    ("Transfer recipient Mira Vale was added.", "PERSON", "Mira Vale"),
    ("Hello María Vela, payment received.", "PERSON", "María Vela"),
    ("Call +1 (202) 555-0124 now.", "PHONE", "+1 (202) 555-0124"),
    ("Contact 202.555.0125 for details.", "PHONE", "202.555.0125"),
    ("Call 555-0126 today.", "PHONE", "555-0126"),
    ("Call +999 555 010 0123 ext 42 today.", "PHONE", "+999 555 010 0123 ext 42"),
    ("Phone 2025550127 was updated.", "PHONE", "2025550127"),
    ("Account number 1234567890 is locked.", "ACCOUNT_DIGITS", "1234567890"),
    ("Card ending in 9876 was used.", "ACCOUNT_DIGITS", "9876"),
    ("Card: 4111 1111 1111 1111 requires attention.", "ACCOUNT_DIGITS", "4111 1111 1111 1111"),
    ("Routing: 123456789, account ending in 4321.", "ACCOUNT_DIGITS", "123456789"),
    ("Code 654321 expires soon.", "ACCOUNT_DIGITS", "654321"),
    ("Send to 123 Main Street, Dallas, TX 75001.", "ADDRESS", "123 Main Street, Dallas, TX 75001"),
    ("Address: 456 Willow Ave Apt 4B.", "ADDRESS", "456 Willow Ave Apt 4B"),
    ("Mail to PO Box 1234.", "ADDRESS", "PO Box 1234"),
    ("Email mira.vale@example.test to confirm.", "EMAIL", "mira.vale@example.test"),
    ("Contact rhea+demo@example.invalid today.", "EMAIL", "rhea+demo@example.invalid"),
], ids=[f"p5_{i:02d}" for i in range(1, 21)])
def test_p5_twenty_handwritten_messages(text, kind, removed):
    result = privacy.redact(text)
    assert isinstance(result, RedactedMessage)
    assert removed not in result.text_redacted
    assert getattr(result.report.counts, kind) >= 1
    expected_tag = "<PHONE_HASH_" if kind == "PHONE" else f"<{kind}>"
    assert expected_tag in result.text_redacted


def test_full_message_report_and_overlap_resolution():
    text = ("Capital One: Hi Mira Vale, account ending in 4321. "
            "Call +1 (202) 555-0124 or email mira@example.test. "
            "Address: 123 Main Street, Dallas, TX 75001. Pay $10000.50 in 1200 hours. "
            "Verify at https://billing.example.test/path?name=Mira&account=1234567890.")
    result = privacy.redact(text)
    assert result.report.counts.model_dump() == {"PERSON": 1, "PHONE": 1, "ACCOUNT_DIGITS": 1, "ADDRESS": 1, "EMAIL": 1}
    assert result.raw_urls == ["https://billing.example.test/path?name=Mira&account=1234567890"]
    assert "Capital One" in result.text_redacted
    assert "$10000.50 in 1200 hours" in result.text_redacted
    assert result.report.kept == ["brand", "domain", "amount", "deadline"]
    assert result.text_redacted.endswith("<URL_1>.")


def test_urls_are_removed_before_email_phone_and_account_detection():
    url = "https://example.test/1234567890?email=mira@example.test&phone=2025550124"
    result = privacy.redact(f"Verify {url}, then close the message.")
    assert result.text_redacted == "Verify <URL_1>, then close the message."
    assert result.raw_urls == [url]
    assert result.report.counts.model_dump() == {"PERSON": 0, "PHONE": 0, "ACCOUNT_DIGITS": 0, "ADDRESS": 0, "EMAIL": 0}


def test_url_order_repeated_domains_and_punctuation():
    result = privacy.redact("(https://example.test/a_(b)), www.sample.test/pay! example.test?x=1.")
    assert result.raw_urls == ["https://example.test/a_(b)", "www.sample.test/pay", "example.test?x=1"]
    assert result.text_redacted == "(<URL_1>), <URL_2>! <URL_3>."


def test_keep_brands_short_codes_amounts_and_deadlines():
    text = "Capital One and T-Mobile: text STOP to 12345. Pay $10000 or 2500 USD within 1200 minutes, by 2026-11-08."
    result = privacy.redact(text)
    assert result.text_redacted == text
    assert result.report.counts.model_dump() == {"PERSON": 0, "PHONE": 0, "ACCOUNT_DIGITS": 0, "ADDRESS": 0, "EMAIL": 0}
    assert "short_code" in result.report.kept


def test_dates_do_not_turn_into_account_digits():
    text = "Due November 8, 2026 or 11/08/2026. Account 2026 is separate."
    result = privacy.redact(text)
    assert result.text_redacted == "Due November 8, 2026 or 11/08/2026. Account <ACCOUNT_DIGITS> is separate."
    assert result.report.counts.ACCOUNT_DIGITS == 1


def test_hash_is_salted_and_format_independent():
    expected = privacy.hash_phone("2025550124", "synthetic-one")
    assert expected == privacy.hash_phone("+1 (202) 555-0124 ext 33", "synthetic-one")
    assert expected != privacy.hash_phone("2025550124", "synthetic-two")
    assert "2025550124" not in expected
    assert len(expected.removeprefix("<PHONE_HASH_").removesuffix(">")) == 16


@pytest.mark.parametrize("number,salt", [("2025550124", ""), ("2025550124", " "), ("not-a-number", "synthetic"), ("12345", "synthetic")])
def test_hash_rejects_missing_salt_or_invalid_numbers(number, salt):
    with pytest.raises(ValueError):
        privacy.hash_phone(number, salt)


def test_missing_runtime_salt_fails_closed_for_phone(monkeypatch):
    monkeypatch.setattr(privacy, "get_settings", lambda: SimpleNamespace(PHONE_HASH_SALT=None))
    with pytest.raises(ValueError, match="PHONE_HASH_SALT"):
        privacy.redact("Call 202-555-0124.")
    with pytest.raises(ValueError, match="PHONE_HASH_SALT"):
        privacy.redact_sender("202-555-0124")
    assert privacy.redact("T-Mobile bill ready.").text_redacted == "T-Mobile bill ready."
    assert privacy.redact_sender("CapitalOne") == (SenderType.alphanumeric, "CapitalOne")


@pytest.mark.parametrize("raw,expected_type,expected_value", [
    (" 12345 ", SenderType.short_code, "12345"),
    ("654321", SenderType.short_code, "654321"),
    ("CapitalOne", SenderType.alphanumeric, "CapitalOne"),
    ("T-Mobile", SenderType.alphanumeric, "T-Mobile"),
    ("mira@example.test", SenderType.email, "<EMAIL>"),
    ("Mira Vale", SenderType.unknown, "<UNKNOWN_SENDER>"),
    ("Mira", SenderType.alphanumeric, "<UNKNOWN_SENDER>"),
    ("", SenderType.unknown, "<UNKNOWN_SENDER>"),
])
def test_sender_types_and_privacy(raw, expected_type, expected_value):
    assert privacy.redact_sender(raw) == (expected_type, expected_value)


def test_sender_phone_matches_message_hash():
    kind, value = privacy.redact_sender("+1 (202) 555-0124")
    assert kind == SenderType.long_code
    assert value in privacy.redact("Call 2025550124.").text_redacted


def test_known_customer_names_are_local_and_brand_aware():
    result = privacy.redact("Mira visited Capital One.", person_names=["Mira", "One"])
    assert result.text_redacted == "<PERSON> visited Capital One."
    assert result.report.counts.PERSON == 1


@pytest.mark.parametrize("text", ["<PHONE_HASH_2025550124>", "<PHONE_HASH_4111111111111111>", "<URL_2025550124>"])
def test_forged_privacy_tags_are_not_trusted(text):
    with pytest.raises(ValueError, match="not valid raw message"):
        privacy.redact(text)


def test_mixed_existing_and_raw_urls_fail_closed():
    with pytest.raises(ValueError, match="Pre-redacted URL"):
        privacy.redact("<URL_1> and https://example.test")


def test_repeated_sensitive_values_count_occurrences():
    result = privacy.redact("Email mira@example.test or mira@example.test; call 2025550124 or 2025550124.")
    assert result.report.counts.EMAIL == 2 and result.report.counts.PHONE == 2
    assert result.text_redacted.count("<PHONE_HASH_") == 2


def test_clean_or_empty_text_has_an_empty_report():
    for text in ("", "Your statement is ready."):
        result = privacy.redact(text)
        assert result.text_redacted == text and result.raw_urls == []
        assert not any(result.report.counts.model_dump().values())


@pytest.mark.parametrize("address", ["mira.vale@example.test", "mira+www.example.test@sample.invalid"])
def test_dotted_email_local_part_is_not_a_url(address):
    result = privacy.redact(address)
    assert result.text_redacted == "<EMAIL>"
    assert result.raw_urls == [] and result.report.counts.EMAIL == 1


def test_bare_url_with_sensitive_query_is_covered_as_a_whole():
    url = "example.test/form?email=mira.vale@example.test&account=1234567890"
    result = privacy.redact(url)
    assert result.text_redacted == "<URL_1>" and result.raw_urls == [url]
    assert not any(result.report.counts.model_dump().values())
