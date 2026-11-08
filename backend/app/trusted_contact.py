"""Trusted-contact alert (L15 feature 3).

The customer saves one person (name and phone) who should be told when they may
be talking to a scammer, the way banks offer a "trusted contact" for accounts.
Older adults, the main victims, often freeze; a second person who calls right
away is one of the most effective interventions.

Rules:
- It only fires on the customer's tap (AGENTS.md section 7).
- The alert never includes the message, a link, a phone number from the
  message, or an amount: only that the customer may need a call.
- The contact's phone is held in memory for this server, never logged, never
  sent to a model, and always shown masked (`•••• 4471`).
- Sending is simulated for the demo, like every other action: the API returns
  the exact text that would be sent.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

_lock = threading.Lock()
_contacts: dict[str, "TrustedContact"] = {}  # owner user id -> contact


class InvalidContact(ValueError):
    pass


@dataclass(frozen=True)
class TrustedContact:
    name: str
    phone: str  # digits with an optional leading +, memory only

    @property
    def masked(self) -> str:
        return f"•••• {self.phone[-4:]}"

    def view(self) -> dict[str, str]:
        return {"name": self.name, "phone_masked": self.masked}


def _clean(name: str, phone: str) -> TrustedContact:
    name = " ".join(name.split())
    if not name or len(name) > 40 or not re.fullmatch(r"[\w .'\-]+", name):
        raise InvalidContact("Use a first name or short name (letters, spaces, . ' -).")
    digits = re.sub(r"[^\d+]", "", phone)
    if not re.fullmatch(r"\+?\d{10,15}", digits):
        raise InvalidContact("Use a phone number with 10 to 15 digits.")
    return TrustedContact(name=name, phone=digits)


def save(owner: str, name: str, phone: str) -> TrustedContact:
    contact = _clean(name, phone)
    with _lock:
        _contacts[owner] = contact
    return contact


def get(owner: str) -> TrustedContact | None:
    with _lock:
        return _contacts.get(owner)


def remove(owner: str) -> None:
    with _lock:
        _contacts.pop(owner, None)


def clear() -> None:
    with _lock:
        _contacts.clear()


def alert_text(customer_name: str, recovery: bool) -> str:
    """What the trusted contact receives. Deliberately content-free."""
    situation = "may have shared details with a scammer" if recovery else "may be in a conversation with a scammer right now"
    return (
        f"SentinelAI: {customer_name} {situation}. Please call {customer_name} now. "
        "We have not moved any money. This alert contains none of the message."
    )


def alert_note(owner: str, customer_name: str, recovery: bool = False) -> str:
    """The `note` for the simulated alert action: who would be texted and the exact words."""
    contact = get(owner)
    if contact is None:
        return "Add a trusted contact first. Nothing was sent."
    return f"Simulated for the demo. We'd text {contact.name} ({contact.masked}): “{alert_text(customer_name, recovery)}”"
