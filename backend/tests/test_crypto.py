"""AES-256-GCM key ring (L13): round trip and every way decryption must fail closed."""

from __future__ import annotations

import pytest

from app.crypto import DecryptionError, KeyRing, KeyRingError, generate_key, keyed_hash


def ring(*ids: str) -> tuple[KeyRing, dict[str, str]]:
    keys = {i: generate_key() for i in ids}
    return KeyRing.parse(",".join(f"{i}:{k}" for i, k in keys.items())), keys


def test_round_trip_and_fresh_nonce_each_time():
    kr, _ = ring("k1")
    a = kr.encrypt("JBSWY3DPEHPK3PXP", b"totp:u1")
    b = kr.encrypt("JBSWY3DPEHPK3PXP", b"totp:u1")
    assert a != b  # random nonce: same plaintext never gives the same ciphertext
    assert kr.decrypt_text(a, b"totp:u1") == "JBSWY3DPEHPK3PXP"
    assert "JBSWY3DPEHPK3PXP" not in a
    assert a.startswith("v1.k1.")


def test_tampered_ciphertext_is_rejected():
    kr, _ = ring("k1")
    token = kr.encrypt("secret", b"ctx")
    head, sealed = token.rsplit(".", 1)
    flipped = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
    with pytest.raises(DecryptionError):
        kr.decrypt(f"{head}.{flipped}", b"ctx")


def test_ciphertext_moved_to_another_row_is_rejected():
    kr, _ = ring("k1")
    token = kr.encrypt("secret", b"totp:alice")
    with pytest.raises(DecryptionError):
        kr.decrypt(token, b"totp:mallory")


def test_wrong_key_is_rejected():
    kr1, _ = ring("k1")
    kr2, _ = ring("k1")  # same id, different key
    with pytest.raises(DecryptionError):
        kr2.decrypt(kr1.encrypt("secret", b"ctx"), b"ctx")


def test_unknown_key_id_and_garbage_are_rejected():
    kr, _ = ring("k1")
    other, _ = ring("k9")
    with pytest.raises(DecryptionError):
        kr.decrypt(other.encrypt("secret", b"ctx"), b"ctx")
    for junk in ("", "v1.k1", "v2.k1.AAAA.BBBB", "v1.k1.!!!.@@@", "not.even.close.x"):
        with pytest.raises(DecryptionError):
            kr.decrypt(junk, b"ctx")


def test_rotation_new_key_encrypts_old_key_still_decrypts():
    old, keys = ring("k1")
    token = old.encrypt("secret", b"ctx")
    rotated = KeyRing.parse(f"k2:{generate_key()},k1:{keys['k1']}")
    assert rotated.decrypt_text(token, b"ctx") == "secret"
    assert rotated.needs_reencrypt(token)
    fresh = rotated.encrypt("secret", b"ctx")
    assert fresh.startswith("v1.k2.") and not rotated.needs_reencrypt(fresh)
    with pytest.raises(DecryptionError):  # once k1 is dropped, its rows no longer read
        KeyRing.parse(f"k2:{generate_key()}").decrypt(token, b"ctx")


@pytest.mark.parametrize(
    "setting",
    ["", "   ", "k1", "k1:not-base64!!", "k1:" + "QUJD", "bad id:" + "A" * 44, "k1:{k},k1:{k}"],
)
def test_bad_key_settings_fail_without_echoing_the_value(setting):
    key = generate_key()
    setting = setting.replace("{k}", key)
    with pytest.raises(KeyRingError) as exc:
        KeyRing.parse(setting)
    assert key not in str(exc.value)


def test_derived_keys_and_keyed_hash():
    kr, _ = ring("k1")
    ip_key = kr.derive("audit-ip")
    assert len(ip_key) == 32 and ip_key != kr.derive("other-purpose")
    h = keyed_hash(ip_key, "203.0.113.7")
    assert h == keyed_hash(ip_key, "203.0.113.7") and "203.0.113.7" not in h
    assert h != keyed_hash(kr.derive("other-purpose"), "203.0.113.7")
