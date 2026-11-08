"""Audit log (L13): tamper evidence and staying content-free."""

from __future__ import annotations

import sqlite3

import pytest

from app.audit import AuditError, AuditLog


@pytest.fixture
def log() -> AuditLog:
    db = sqlite3.connect(":memory:", isolation_level=None)
    audit = AuditLog(db)
    for i in range(5):
        audit.record("auth.signin", actor=f"user-{i}", ip_hash="abc123", details={"method": "passkey"})
    return audit


def test_intact_chain_verifies(log):
    assert log.verify_chain() == (True, None)
    assert [e.actor for e in log.recent(2)] == ["user-4", "user-3"]


def test_edited_row_is_detected(log):
    log._db.execute("UPDATE audit_events SET outcome = 'failure' WHERE id = 3")
    assert log.verify_chain() == (False, 3)


def test_edited_row_with_recomputed_own_hash_still_breaks_the_next(log):
    from app.audit import _row_hash

    r = log._db.execute("SELECT * FROM audit_events WHERE id = 2").fetchone()
    forged = _row_hash(r[8], r[1], r[2], "attacker", r[4], r[5], r[6], r[7])
    log._db.execute("UPDATE audit_events SET actor = 'attacker', hash = ? WHERE id = 2", (forged,))
    assert log.verify_chain() == (False, 3)


def test_deleted_row_is_detected(log):
    log._db.execute("DELETE FROM audit_events WHERE id = 2")
    assert log.verify_chain() == (False, 3)


@pytest.mark.parametrize("details", [{"text": "Your account is locked"}, {"password": "x"}, {"token": "y"}, {"ip": "203.0.113.7"}])
def test_content_keys_are_refused(log, details):
    with pytest.raises(AuditError):
        log.record("auth.signin", details=details)


def test_long_or_nested_details_are_refused(log):
    with pytest.raises(AuditError):
        log.record("auth.signin", details={"reason": "x" * 65})
    with pytest.raises(AuditError):
        log.record("auth.signin", details={"reason": {"nested": 1}})
    with pytest.raises(AuditError):
        log.record("auth.signin", outcome="maybe")
